"""MHP driver for a Thermo Scientific Phenom XL / Pharos / ProX desktop SEM through the Phenom Programming
Interface: PyPhenom, Thermo's licensed Python package, which connects over the network as
`ppi.Phenom(address, instrument_id, licence_password)` (shown in Thermo-partner PPI material) and exposes
calls such as `Unload()`, `SemAcquireImage(...)` and `SemAutoFocus()` (named in Thermo's PPI webinar) and
`ppi.Position(x, y)` in metres. The PPI reference itself is distributed with the licence and was not
readable here, so every other member used below (Load, MoveTo, GetStagePosition, GetInstrumentMode,
GetOperationalMode, Activate, Standby, GetSemHfw/SetSemHfw, GetSemMagnification, GetSemHighTension/
SetSemHighTension, ScanParams fields, Save) is marked `# unverified` and its name comes from config.json
so it can be corrected without editing code. Every PPI call sits in PhenomBackend; the twin swaps the
backend for a model of the instrument and writes real TIFFs. No vendor import at module top.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import time

from openmhp.driver import DeviceFault, Driver, InvalidValue, Job, JobCancelled

HERE = pathlib.Path(__file__).parent
LABEL = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
LIVE_MODES = ("livesem", "acquiresemimage", "semimage")             # operational modes with the holder loaded under the SEM
DEFAULT_NAMES = {"module": "PyPhenom", "phenom": "Phenom", "position": "Position", "load": "Load", "unload": "Unload",
                 "move_to": "MoveTo", "stage_position": "GetStagePosition", "instrument_mode": "GetInstrumentMode",
                 "operational_mode": "GetOperationalMode", "activate": "Activate", "standby": "Standby",
                 "get_hfw": "GetSemHfw", "set_hfw": "SetSemHfw", "get_mag": "GetSemMagnification",
                 "get_ht": "GetSemHighTension", "set_ht": "SetSemHighTension", "auto_focus": "SemAutoFocus",
                 "acquire": "SemAcquireImage", "scan_params": "ScanParams", "save": "Save"}
DETECTORS = ("bsd_all", "bsd_topo_a", "bsd_topo_b", "sed")


def load_config() -> dict:
    p = HERE / "config.json"
    return json.loads(p.read_text(encoding="utf-8") or "{}") if p.is_file() else {}


class PhenomBackend:
    """Every PPI call. Member names come from config.json `ppi` because most could not be verified."""

    def __init__(self, cfg: dict):
        self.cfg, self.ppi, self.phenom = cfg, None, None
        self.names = {**DEFAULT_NAMES, **(cfg.get("ppi") or {})}

    def _m(self, key: str):
        return getattr(self.phenom, self.names[key])

    def open(self) -> None:
        if not self.cfg.get("address"):
            raise DeviceFault("config.json is missing (copy config.example.json and fill it in)")
        import importlib
        self.ppi = importlib.import_module(self.names["module"])          # PyPhenom, Thermo's licensed package
        password = self.cfg.get("ppi_password")
        if not password and self.cfg.get("instrument_id"):
            import keyring
            password = keyring.get_password("PhenomPPI", str(self.cfg["instrument_id"])) or ""
        self.phenom = getattr(self.ppi, self.names["phenom"])(self.cfg["address"], str(self.cfg.get("instrument_id", "")), password or "")
        self.instrument_mode()

    def instrument_mode(self) -> str:
        return str(self._m("instrument_mode")()).rsplit(".", 1)[-1]        # unverified: enum InstrumentMode.<Operational|Standby|Hibernate>

    def operational_mode(self) -> str:
        return str(self._m("operational_mode")()).rsplit(".", 1)[-1]       # unverified: enum OperationalMode.<Loading|Unloading|Unloaded|LiveNavCam|LiveSem|...>

    def load(self) -> None:
        self._m("load")()                                                   # unverified

    def unload(self) -> None:
        self._m("unload")()                                                 # Unload() named in Thermo's PPI webinar

    def activate(self) -> None:
        self._m("activate")()                                               # unverified

    def standby(self) -> None:
        self._m("standby")()                                                # unverified

    def stage_position(self) -> dict:
        p = self._m("stage_position")()                                     # unverified: returns a Position in metres
        return {"x_mm": round(float(p.x) * 1000, 4), "y_mm": round(float(p.y) * 1000, 4)}

    def move_to(self, x_mm: float, y_mm: float) -> None:
        pos = getattr(self.ppi, self.names["position"])(x_mm / 1000, y_mm / 1000)   # Position(x, y) in metres
        self._m("move_to")(pos)                                             # unverified

    def high_voltage_kv(self) -> float:
        return round(abs(float(self._m("get_ht")())) / 1000, 2)            # unverified: PPI high tension is negative volts

    def set_high_voltage_kv(self, kv: float) -> None:
        self._m("set_ht")(-abs(float(kv)) * 1000)                           # unverified

    def set_magnification(self, mag: float) -> tuple[float, float]:
        """Magnification is set through the horizontal field width; returns (magnification, hfw_um) as reported."""
        screen_width_m = float(self.cfg.get("screen_width_m", 0.1))         # the reference width PPI's magnification uses (unverified)
        self._m("set_hfw")(screen_width_m / float(mag))                     # unverified: SetSemHfw(metres)
        hfw = float(self._m("get_hfw")())                                   # unverified
        return round(float(self._m("get_mag")()), 1), round(hfw * 1e6, 3)   # unverified: GetSemMagnification

    def auto_focus(self) -> None:
        self._m("auto_focus")()                                             # SemAutoFocus() named in Thermo's PPI webinar

    def acquire(self, width: int, height: int, dwell_us: float, frames: int, detector: str, path: str) -> None:
        sp = getattr(self.ppi, self.names["scan_params"])()                 # unverified: ScanParams
        sp.size = self.ppi.Size(int(width), int(height))                    # unverified
        sp.nFrames = int(frames)                                            # unverified
        sp.dwellTime = float(dwell_us) * 1e-6                               # unverified
        sp.detector = {"bsd_all": self.ppi.DetectorMode.All, "bsd_topo_a": self.ppi.DetectorMode.TopoA,
                       "bsd_topo_b": self.ppi.DetectorMode.TopoB, "sed": self.ppi.DetectorMode.Sed}[detector]   # unverified
        acq = self._m("acquire")(sp)                                        # SemAcquireImage named in Thermo's PPI webinar; argument unverified
        getattr(self.ppi, self.names["save"])(acq, path)                    # unverified: ppi.Save(acquisition, filename)


class PhenomSEM(Driver):
    def setup(self) -> None:
        self.cfg = load_config()
        self.hw = None
        self.running = False
        self.last_image = None

    def make_backend(self):
        return PhenomBackend(self.cfg)

    def time_scale(self) -> float:
        return 1.0

    def _hw(self):
        if self.hw is None:
            hw = self.make_backend()
            try:
                hw.open()
            except DeviceFault:
                raise
            except ImportError as e:
                raise DeviceFault(f"PyPhenom (Thermo's PPI package) is not installed in this Python: {e}") from None
            except Exception as e:                               # noqa: BLE001  vendor boundary
                raise DeviceFault(f"cannot open a PPI session to {self.cfg.get('address')}: {type(e).__name__}: {e}",
                                  {"transient": True}) from None
            self.hw = hw
        return self.hw

    def _vendor(self, what, fn):
        try:
            return fn()
        except (DeviceFault, InvalidValue):
            raise
        except Exception as e:                                   # noqa: BLE001  vendor boundary
            raise DeviceFault(f"PPI {what} failed: {type(e).__name__}: {e}", {"transient": True}) from None

    def _op_mode(self) -> str:
        return self._vendor("GetOperationalMode", self._hw().operational_mode)

    def _live(self, mode: str | None = None) -> bool:
        return (mode or self._op_mode()).lower() in LIVE_MODES

    def on_read(self, name: str):
        if name == "connected":
            try:
                self._vendor("GetInstrumentMode", self._hw().instrument_mode)
                return True
            except DeviceFault:
                return False
        hw = self._hw()
        if name == "instrument_mode":
            return self._vendor("GetInstrumentMode", hw.instrument_mode)
        if name == "operational_mode":
            return self._op_mode()
        if name == "vacuum_ready":
            return self._live()
        if name == "beam_on":
            return self._vendor("GetInstrumentMode", hw.instrument_mode).lower() == "operational" and self._live()
        if name == "high_voltage":
            return self._vendor("GetSemHighTension", hw.high_voltage_kv)
        if name == "stage_position":
            return self._vendor("GetStagePosition", hw.stage_position)
        if name == "robot_access_ready":
            return self._op_mode().lower() == "unloaded" and not self.running
        if name == "last_image":
            return self.last_image
        raise InvalidValue(f"unknown signal {name}")

    def on_write(self, name: str, value):
        if name != "high_voltage":
            raise InvalidValue(f"unknown setting {name}")
        self._vendor("SetSemHighTension", lambda: self._hw().set_high_voltage_kv(value))
        return None

    def validate_params(self, action: str, params: dict) -> None:
        if action == "acquire_image":
            label = params.get("label", "image")
            if not isinstance(label, str) or not LABEL.match(label):
                raise InvalidValue("acquire_image.label must be 1-64 letters, digits, dash or underscore")

    def _image_dir(self) -> pathlib.Path:
        d = pathlib.Path(self.cfg.get("image_dir") or (pathlib.Path(os.environ.get("OPENMHP_HOME") or (pathlib.Path.home() / ".openmhp")) / "sim-data" / "phenom"))
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _wait_mode(self, job: Job, hw, done, what: str, limit_s: float) -> str:
        scale = self.time_scale()
        deadline = time.time() + limit_s * scale
        while True:
            mode = self._op_mode()
            if done(mode):
                return mode
            if time.time() > deadline:
                raise DeviceFault(f"{what} did not finish within {limit_s:.0f} s (operational mode {mode})", {"transient": True})
            time.sleep(min(0.5, 2 * scale))

    def on_invoke(self, job: Job):
        hw, p, scale = self._hw(), job.params, self.time_scale()
        started = time.time()
        if job.action == "load_sample":
            self.running = True
            try:
                self._vendor("Load", hw.load)
                mode = self._wait_mode(job, hw, lambda m: self._live(m), "loading", float(self.cfg.get("load_timeout_s", 300)))
            finally:
                self.running = False
            return {"loaded": True, "operational_mode": mode, "duration_s": round((time.time() - started) / scale, 1)}
        if job.action == "unload_sample":
            self.running = True
            try:
                self._vendor("Unload", hw.unload)
                mode = self._wait_mode(job, hw, lambda m: m.lower() == "unloaded", "unloading", float(self.cfg.get("load_timeout_s", 300)))
            finally:
                self.running = False
            return {"loaded": False, "operational_mode": mode, "duration_s": round((time.time() - started) / scale, 1)}
        if job.action == "move_stage":
            self._vendor("MoveTo", lambda: hw.move_to(p["x_mm"], p["y_mm"]))
            return self._vendor("GetStagePosition", hw.stage_position)
        if job.action == "auto_focus":
            self._vendor("SemAutoFocus", hw.auto_focus)
            return {"focused": True}
        if job.action != "acquire_image":
            raise InvalidValue(f"unhandled action {job.action}")
        self.running = True
        try:
            mag, hfw_um = self._vendor("SetSemHfw", lambda: hw.set_magnification(p["magnification"]))
            self.checkpoint(job, 0.1, phase="field of view set")
            if p["auto_focus"]:
                self._vendor("SemAutoFocus", hw.auto_focus)
            self.checkpoint(job, 0.3, phase="focused")
            path = self._image_dir() / f"{time.strftime('%Y%m%d_%H%M%S')}_{p['label']}_{int(mag)}x.tif"
            self._vendor("SemAcquireImage", lambda: hw.acquire(p["width_px"], p["height_px"], p["dwell_us"], p["frames"], p["detector"], str(path)))
            self.progress(job, 0.9)
            result = {"file": str(path), "magnification": mag, "hfw_um": hfw_um, "width_px": int(p["width_px"]),
                      "height_px": int(p["height_px"]), "high_voltage_kv": self._vendor("GetSemHighTension", hw.high_voltage_kv),
                      "dwell_us": float(p["dwell_us"]), "frames": int(p["frames"]), "detector": p["detector"],
                      "stage": self._vendor("GetStagePosition", hw.stage_position),
                      "duration_s": round((time.time() - started) / scale, 1)}
        except JobCancelled:
            raise
        finally:
            self.running = False
        self.last_image = result
        self.emit_signal("last_image", result)
        return result

    def on_estop(self) -> None:
        try:
            if self.hw is not None:
                self.hw.standby()                                # beam off: source to standby (unverified name)
        except Exception:                                        # noqa: BLE001  must not raise
            pass
        self.running = False

    @classmethod
    def probe(cls, cfg: dict) -> str:
        hw = PhenomBackend(cfg)
        hw.open()
        return f"PPI session to {cfg.get('address')} ({cfg.get('instrument_id')}): instrument mode {hw.instrument_mode()}, operational mode {hw.operational_mode()}"
