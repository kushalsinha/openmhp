"""MHP driver for the Beckman Coulter Vi-CELL BLU through its OPC UA automation interface.

The interface is documented in Beckman's "Vi-CELL BLU Automation Software Integration Guide for
Developer Use" (doc 21.09.2613.PCC Rev A): properties CurrentStatus, CurrentLockState,
ReagentUsesRemaining, CellTypes, CurrentSamplePosition; methods RequestLock, ReleaseLock, StartSample,
StartSampleSet, Pause, Resume, Stop, EjectStage, GetSampleResults. The OPC UA node ids are not in the
public guide (they come with the automation kit's SDK), so they are config.json placeholders marked
unverified. Every vendor call is behind ViCellBackend; the twin swaps in a fake server.

Requires: pip install asyncua keyring (or python-opcua).
"""
from __future__ import annotations

import json
import pathlib
import time

from openmhp.driver import DeviceFault, Driver, InvalidValue, Job, JobCancelled, LimitViolation

HERE = pathlib.Path(__file__).parent
STATUS = ("Unknown", "Idle", "Initializing", "Cleaning", "Running", "Error", "Warning", "RequiresUserInteraction")
WASH = {"normal": 0, "fast": 1}                                  # WashType enum order from the guide
RESULT_OK = 1                                                    # VcbResult {Error=0, Success=1, NoConnection=2, NotLocked=3}

# every id unverified: browse the server with UaExpert and copy the real ones into config.json
DEFAULT_NODES = {
    "object": "ns=2;s=ViCellBlu", "status": "ns=2;s=ViCellBlu.CurrentStatus", "lock_state": "ns=2;s=ViCellBlu.CurrentLockState",
    "reagent": "ns=2;s=ViCellBlu.ReagentUsesRemaining", "cell_types": "ns=2;s=ViCellBlu.CellTypes",
    "sample_position": "ns=2;s=ViCellBlu.CurrentSamplePosition", "carousel_present": "ns=2;s=ViCellBlu.CarouselPresent",
    "request_lock": "ns=2;s=ViCellBlu.RequestLock", "release_lock": "ns=2;s=ViCellBlu.ReleaseLock",
    "start_sample": "ns=2;s=ViCellBlu.StartSample", "stop": "ns=2;s=ViCellBlu.Stop", "pause": "ns=2;s=ViCellBlu.Pause",
    "resume": "ns=2;s=ViCellBlu.Resume", "eject_stage": "ns=2;s=ViCellBlu.EjectStage",
    "get_results": "ns=2;s=ViCellBlu.GetSampleResults", "prime": "ns=2;s=ViCellBlu.Prime", "clean": "ns=2;s=ViCellBlu.Clean",
}


def load_config() -> dict:
    p = HERE / "config.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


class ViCellBackend:
    """asyncua sync client against the Vi-CELL BLU OPC UA server; node ids from config.json."""

    def __init__(self, cfg: dict):
        self.cfg, self.client = cfg, None
        self.nodes = {**DEFAULT_NODES, **(cfg.get("nodes") or {})}

    def open(self) -> None:
        if not self.cfg.get("url"):
            raise DeviceFault("config.json is missing (copy config.example.json and fill it in)")
        try:
            from asyncua.sync import Client
        except ImportError:
            from opcua import Client
        c = Client(self.cfg["url"])
        user = self.cfg.get("user")
        if user:
            import keyring
            c.set_user(user)
            c.set_password(keyring.get_password("ViCellBLU", user) or "")
        c.connect()
        self.client = c

    def _node(self, key: str):
        return self.client.get_node(self.nodes[key])

    def _call(self, key: str, *args):
        return self._node("object").call_method(self.nodes[key], *args)

    def status(self) -> str:
        v = self._node("status").get_value()
        return STATUS[v] if isinstance(v, int) and 0 <= v < len(STATUS) else str(v)

    def reagent_remaining(self):
        v = self._node("reagent").get_value()
        return int(v) if v is not None else None

    def carousel_present(self) -> bool:
        return bool(self._node("carousel_present").get_value())             # unverified property

    def cell_types(self) -> list:
        v = self._node("cell_types").get_value() or []
        return [str(getattr(x, "Name", x)) for x in v]

    def lock(self) -> None:
        r = self._call("request_lock")
        if r not in (RESULT_OK, "Success", None, 1, [1]):
            raise DeviceFault(f"RequestLock refused: {r}; the operator UI holds the instrument")

    def unlock(self) -> None:
        self._call("release_lock")

    def start_sample(self, cfg: dict) -> None:
        # SampleConfig {Name, Position{Row, Column}, Dilution, Tag, CellTypeName, QCName, SaveEveryNthImage, WashType}
        # passed as positional scalars: the OPC UA structure encoding is in the kit's SDK, unverified
        pos = cfg["position"]
        row, col = ("A", 0) if pos == "cup" else ("Z", int(pos))                 # carousel row letter unverified
        r = self._call("start_sample", cfg["name"], row, col, int(cfg["dilution"]), "", cfg["cell_type"], "",
                       1 if cfg["save_images"] else 0, WASH[cfg["wash"]])
        if r in (0, "Error", 3, "NotLocked"):
            raise DeviceFault(f"StartSample returned {r}")

    def stop(self) -> None:
        self._call("stop")

    def eject_stage(self) -> None:
        self._call("eject_stage")

    def prime(self) -> None:
        self._call("prime")                                      # unverified: no prime method in the public guide

    def clean(self) -> None:
        self._call("clean")                                      # unverified: no clean method in the public guide

    def results(self, name: str) -> dict | None:
        """GetSampleResults(FilterType, FromDate, ToDate, Username, SearchString, SampleTag, CellTypeOrQCName)."""
        out = self._call("get_results", 0, 0, 0, "", name, "", "")
        if not out:
            return None
        r = out[-1] if isinstance(out, list) else out
        g = lambda k: getattr(r, k, None) if not isinstance(r, dict) else r.get(k)   # noqa: E731
        return {"cell_count": g("CellCount"), "viable_cell_count": g("ViableCellCount"),
                "viability_pct": g("ViabilityPercent"), "avg_diameter_um": g("AverageDiameter"),
                "viable_cells_per_ml": g("ViableCellsPerMl"), "total_cells_per_ml": g("TotalCellsPerMl"),   # unverified fields (Rev A lists counts only)
                "images": g("ImagePath")}                                                                   # unverified


class ViCellBlu(Driver):
    def setup(self) -> None:
        self.cfg = load_config()
        self.hw = None
        self.counting = False
        self.last_result = None

    def make_backend(self):
        return ViCellBackend(self.cfg)

    def time_scale(self) -> float:
        return 1.0

    def _hw(self):
        if self.hw is None:
            hw = self.make_backend()
            try:
                hw.open()
            except DeviceFault:
                raise
            except ImportError:
                raise DeviceFault("asyncua is not installed (pip install asyncua keyring)") from None
            except Exception as e:                               # noqa: BLE001  vendor boundary
                raise DeviceFault(f"cannot reach the Vi-CELL BLU OPC UA server at {self.cfg.get('url')}: {type(e).__name__}: {e}",
                                  {"transient": True}) from None
            self.hw = hw
        return self.hw

    def _vendor(self, what, fn):
        try:
            return fn()
        except (DeviceFault, InvalidValue):
            raise
        except Exception as e:                                   # noqa: BLE001  vendor boundary
            raise DeviceFault(f"Vi-CELL BLU {what} failed: {type(e).__name__}: {e}", {"transient": True}) from None

    def on_read(self, name: str):
        if name == "connected":
            try:
                self._hw()
                return True
            except DeviceFault:
                return False
        if name == "status":
            return self._vendor("CurrentStatus", self._hw().status)
        if name == "reagent_remaining":
            return self._vendor("ReagentUsesRemaining", self._hw().reagent_remaining)
        if name == "carousel_present":
            return bool(self._vendor("CarouselPresent", self._hw().carousel_present))
        if name == "robot_access_ready":
            return (not self.counting) and self._vendor("CurrentStatus", self._hw().status) == "Idle"
        if name == "last_result":
            return self.last_result
        raise InvalidValue(f"unknown signal {name}")

    def validate_params(self, action: str, params: dict) -> None:
        if action != "count":
            return
        pos = params.get("position")
        if pos != "cup":
            try:
                n = int(pos)
            except (TypeError, ValueError):
                raise InvalidValue("count.position must be 'cup' or a carousel slot '1'..'24'") from None
            if not 1 <= n <= 24:
                raise LimitViolation(f"count.position={pos} outside the carousel's 1..24", {"min": 1, "max": 24})
        ct = params.get("cell_type")
        if not isinstance(ct, str) or not ct.strip():
            raise InvalidValue("count.cell_type must name a cell type defined on the instrument")
        allowed = self.cfg.get("allowed_cell_types") or []
        if allowed and ct not in allowed:
            raise InvalidValue(f"cell type {ct!r} is not in allowed_cell_types")

    def on_invoke(self, job: Job):
        hw = self._hw()
        scale = self.time_scale()
        if job.action in ("prime", "clean"):
            self._vendor("RequestLock", hw.lock)
            try:
                self._vendor(job.action, getattr(hw, job.action))
                started = time.time()
                self._follow(job, hw, started, float(self.cfg.get("max_minutes", 20)) * 60 * scale, job.action)
            finally:
                self._vendor("ReleaseLock", hw.unlock)
            return {"action": job.action, "duration_s": round((time.time() - started) / scale, 1),
                    "status": self._vendor("CurrentStatus", hw.status)}
        if job.action != "count":
            raise InvalidValue(f"unhandled action {job.action}")
        p = job.params
        name = f"mhp_{time.strftime('%Y%m%d_%H%M%S')}_{job.id}"
        self._vendor("RequestLock", hw.lock)
        started = time.time()
        self.counting = True
        try:
            self._vendor("StartSample", lambda: hw.start_sample({"name": name, "position": p["position"], "dilution": p["dilution"],
                                                                 "cell_type": p["cell_type"], "wash": p["wash"],
                                                                 "save_images": p["save_images"]}))
            self._follow(job, hw, started, float(self.cfg.get("max_minutes", 20)) * 60 * scale, "counting")
            res = self._vendor("GetSampleResults", lambda: hw.results(name))
        finally:
            self.counting = False
            self._vendor("ReleaseLock", hw.unlock)
        if not res:
            raise DeviceFault(f"the instrument reports no result for sample {name}")
        result = {"position": str(p["position"]), "cell_type": p["cell_type"],
                  "viability_pct": res.get("viability_pct"), "viable_cells_per_ml": res.get("viable_cells_per_ml"),
                  "total_cells_per_ml": res.get("total_cells_per_ml"), "avg_diameter_um": res.get("avg_diameter_um"),
                  "images": res.get("images") if p["save_images"] else None,
                  "duration_s": round((time.time() - started) / scale, 1)}
        self.last_result = result
        self.emit_signal("last_result", result)
        return result

    def _follow(self, job: Job, hw, started: float, limit: float, phase: str) -> None:
        seen = False
        time.sleep(min(1.0, 2 * self.time_scale()))
        while True:
            try:
                self.checkpoint(job, phase=phase)
            except JobCancelled:
                self._vendor("Stop", hw.stop)
                raise
            st = self._vendor("CurrentStatus", hw.status)
            if st in ("Error", "RequiresUserInteraction"):
                raise DeviceFault(f"Vi-CELL BLU reports {st}; a person must attend the instrument")
            if st != "Idle":
                seen = True
            elif seen or time.time() - started > 30 * self.time_scale():
                return
            if time.time() - started > limit:
                raise DeviceFault(f"still {st} after {limit / self.time_scale() / 60:.0f} min (max_minutes)")
            time.sleep(min(1.0, 2 * self.time_scale()))

    def on_estop(self) -> None:
        try:
            if self.hw is not None:
                self.hw.stop()
        except Exception:                                        # noqa: BLE001  must not raise
            pass
        self.counting = False

    @classmethod
    def discover(cls, cfg: dict, what: str) -> list:
        if what != "cell_types":
            return []
        hw = ViCellBackend(cfg)
        hw.open()
        return hw.cell_types()

    @classmethod
    def probe(cls, cfg: dict) -> str:
        hw = ViCellBackend(cfg)
        try:
            hw.open()
        except ImportError:
            raise DeviceFault("asyncua is not installed (pip install asyncua keyring)") from None
        return f"Vi-CELL BLU at {cfg.get('url')} answers; status {hw.status()}, {hw.reagent_remaining()} reagent uses left"
