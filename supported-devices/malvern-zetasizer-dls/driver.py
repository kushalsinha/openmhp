"""MHP driver for a Malvern Panalytical Zetasizer Ultra / Pro under ZS Xplorer (and, by the same shape, a
Zetasizer Nano under the classic Zetasizer software) through the vendor's .NET SDK via pythonnet (Windows).

No public reference for the "ZS Xplorer SDK" or the "Zetasizer Nano SDK" could be found (Malvern
Panalytical's GitHub organisation has no public repositories, and the ZS Xplorer release notes mention no
API), so every member of ZetasizerBackend below is written against the shape such an SDK must have (open the
software, load a SOP, start a size or zeta measurement, poll, abort, read the result record) and marked
`# unverified`. The assembly name and member names come from config.json so they can be corrected without
editing code. The twin runs the same driver against a fake SDK with plausible DLS and ELS results.

Requires on the instrument PC: pip install pythonnet, ZS Xplorer with the SDK option.
"""
from __future__ import annotations

import json
import pathlib
import re
import time

from openmhp.driver import DeviceFault, Driver, InvalidValue, Job, JobCancelled

HERE = pathlib.Path(__file__).parent
SOP_RE = re.compile(r"^[A-Za-z0-9 _.\-]+\.(zsop|sop)$", re.I)


def load_config() -> dict:
    p = HERE / "config.json"
    return json.loads(p.read_text(encoding="utf-8") or "{}") if p.is_file() else {}


def plain(s, what: str) -> str:
    if not isinstance(s, str) or not s.strip() or re.search(r'[\\/"\x00-\x1f]', s) or ".." in s:
        raise InvalidValue(f"{what} must be a plain name without folders, got {s!r}")
    return s.strip()


class ZetasizerBackend:
    """Every SDK call. The assembly and member names are configuration because none could be verified."""

    def __init__(self, cfg: dict):
        self.cfg, self.app, self.measurement = cfg, None, None
        self.names = {"assembly": "Malvern.ZsXplorer.Sdk", "app": "Malvern.ZsXplorer.Sdk.ZsXplorerApplication",
                      "connect": "Connect", "disconnect": "Disconnect", "status": "InstrumentStatus",
                      "cell_temperature": "CellTemperature", "set_temperature": "SetTemperature",
                      "set_equilibration": "SetEquilibrationTime", "load_sop": "LoadSop", "start": "StartMeasurement",
                      "is_running": "IsRunning", "abort": "AbortMeasurement", "result": "LastResult",
                      "export": "ExportResult", **(cfg.get("sdk") or {})}

    def _m(self, key: str):
        return getattr(self.app, self.names[key])

    def open(self) -> None:
        if not self.cfg.get("sop_dir"):
            raise DeviceFault("config.json is missing (copy config.example.json and fill it in)")
        import clr                                               # pythonnet, Windows
        clr.AddReference(self.names["assembly"])                 # unverified assembly name
        import importlib
        mod, _, cls = self.names["app"].rpartition(".")
        self.app = getattr(importlib.import_module(mod), cls)()  # unverified class
        self._m("connect")()                                     # unverified

    def status(self) -> str:
        return str(self._m("status"))                            # unverified property

    def cell_temperature(self) -> float:
        return float(self._m("cell_temperature"))                # unverified property

    def set_temperature(self, c: float) -> None:
        self._m("set_temperature")(float(c))                     # unverified

    def set_equilibration(self, s: float) -> None:
        self._m("set_equilibration")(float(s))                   # unverified

    def start(self, kind: str, sop: str, sample_name: str) -> None:
        self._m("load_sop")(str(pathlib.PureWindowsPath(self.cfg["sop_dir"]) / sop))   # unverified
        self.measurement = self._m("start")(sample_name)         # unverified: returns a measurement handle

    def running(self) -> bool:
        return bool(self._m("is_running"))                       # unverified property

    def abort(self) -> None:
        self._m("abort")()                                       # unverified

    def result(self, kind: str) -> dict:
        r = self._m("result")                                    # unverified: a result record
        g = lambda k: getattr(r, k, None)                        # noqa: E731
        if kind == "size":
            peaks = [{"diameter_nm": float(p.Mean), "intensity_pct": float(p.Area), "width_nm": float(p.Width)}
                     for p in (g("IntensityPeaks") or [])]      # unverified fields
            return {"z_average_nm": g("ZAverage"), "pdi": g("PolydispersityIndex"), "peaks": peaks,
                    "temperature_c": g("Temperature"), "attenuator": g("Attenuator")}
        return {"zeta_mv": g("ZetaPotential"), "conductivity_ms_cm": g("Conductivity"), "mobility": g("Mobility"),
                "quality": str(g("QualityReport") or "")}

    def export(self, path: str) -> None:
        self._m("export")(path)                                  # unverified


class Zetasizer(Driver):
    def setup(self) -> None:
        self.cfg = load_config()
        self.hw = None
        self.measuring = False
        self.setpoint, self.equilibration_s = None, None
        self.last_result = None

    def make_backend(self):
        return ZetasizerBackend(self.cfg)

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
                raise DeviceFault("pythonnet (clr) is not installed or the ZS Xplorer SDK assembly was not found") from None
            except Exception as e:                               # noqa: BLE001  vendor boundary
                raise DeviceFault(f"cannot open the Zetasizer SDK: {type(e).__name__}: {e}", {"transient": True}) from None
            self.hw = hw
        return self.hw

    def _vendor(self, what, fn):
        try:
            return fn()
        except (DeviceFault, InvalidValue):
            raise
        except Exception as e:                                   # noqa: BLE001  vendor boundary
            raise DeviceFault(f"Zetasizer {what} failed: {type(e).__name__}: {e}", {"transient": True}) from None

    def on_read(self, name: str):
        if name == "connected":
            try:
                self._hw()
                return True
            except DeviceFault:
                return False
        if name == "status":
            return self._vendor("status", self._hw().status)
        if name == "cell_temperature":
            return round(float(self._vendor("cell_temperature", self._hw().cell_temperature)), 2)
        if name == "temperature_setpoint":
            return self.setpoint
        if name == "equilibration_s":
            return self.equilibration_s
        if name == "last_result":
            return self.last_result
        raise InvalidValue(f"unknown signal {name}")

    def on_write(self, name: str, value):
        if name == "temperature_setpoint":
            self._vendor("set_temperature", lambda: self._hw().set_temperature(value))
            self.setpoint = value
            return None
        if name == "equilibration_s":
            self._vendor("set_equilibration", lambda: self._hw().set_equilibration(value))
            self.equilibration_s = value
            return None
        raise InvalidValue(f"unknown setting {name}")

    def validate_params(self, action: str, params: dict) -> None:
        if action not in ("measure_size", "measure_zeta"):
            return
        sop = plain(params.get("sop"), f"{action}.sop")
        if not SOP_RE.match(sop):
            raise InvalidValue(f"{action}.sop must be a SOP file name ending in .zsop (ZS Xplorer) or .sop (Nano)")
        plain(params.get("sample_name"), f"{action}.sample_name")
        allowed = self.cfg.get("allowed_sops") or []
        if allowed and sop not in allowed:
            raise InvalidValue(f"SOP {sop!r} is not in allowed_sops")

    def on_invoke(self, job: Job):
        if job.action not in ("measure_size", "measure_zeta"):
            raise InvalidValue(f"unhandled action {job.action}")
        kind = "size" if job.action == "measure_size" else "zeta"
        hw, p, scale = self._hw(), job.params, self.time_scale()
        export_dir = pathlib.Path(self.cfg.get("export_dir") or (pathlib.Path.home() / ".openmhp" / "sim-data" / "zetasizer"))
        export_dir.mkdir(parents=True, exist_ok=True)
        path = export_dir / f"{time.strftime('%Y%m%d_%H%M%S')}_{p['sample_name']}_{kind}.csv"
        started = time.time()
        self._vendor("start", lambda: hw.start(kind, p["sop"], p["sample_name"]))
        self.measuring = True
        limit = float(self.cfg.get("max_minutes", 60)) * 60 * scale
        try:
            time.sleep(min(1.0, 2 * scale))
            while self._vendor("running", hw.running):
                try:
                    self.checkpoint(job, phase="measuring")
                except JobCancelled:
                    self._vendor("abort", hw.abort)
                    raise
                if time.time() - started > limit:
                    raise DeviceFault(f"measurement still running after {limit / scale / 60:.0f} min (max_minutes)")
                time.sleep(min(1.0, 2 * scale))
            res = self._vendor("result", lambda: hw.result(kind))
            self._vendor("export", lambda: hw.export(str(path)))
        finally:
            self.measuring = False
        if kind == "size":
            result = {"sample_name": p["sample_name"], "z_average_nm": res.get("z_average_nm"), "pdi": res.get("pdi"),
                      "peaks": res.get("peaks") or [], "temperature_c": res.get("temperature_c"),
                      "attenuator": res.get("attenuator"), "file": str(path)}
        else:
            result = {"sample_name": p["sample_name"], "zeta_mv": res.get("zeta_mv"), "conductivity_ms_cm": res.get("conductivity_ms_cm"),
                      "mobility": res.get("mobility"), "quality": res.get("quality") or "", "file": str(path)}
        self.last_result = result
        self.emit_signal("last_result", result)
        return result

    def on_estop(self) -> None:
        try:
            if self.hw is not None and (self.measuring or self.hw.running()):
                self.hw.abort()
        except Exception:                                        # noqa: BLE001  must not raise
            pass
        self.measuring = False

    @classmethod
    def probe(cls, cfg: dict) -> str:
        import sys
        if sys.platform != "win32":
            raise DeviceFault("the ZS Xplorer SDK is a .NET assembly on the instrument PC; this is not Windows")
        hw = ZetasizerBackend(cfg)
        hw.open()
        return f"ZS Xplorer SDK opened; instrument status {hw.status()}"
