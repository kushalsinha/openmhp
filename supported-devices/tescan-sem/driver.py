"""MHP driver template for a TESCAN VEGA / MIRA / CLARA through SharkSEM, TESCAN's remote-control TCP interface.

SharkSEM is documented in TESCAN's SharkSEM manual, which is given to customers and was not readable here,
and its client library (a `sem` module with a `Sem` class and `Connect(host, port)`, as public example
scripts use it) ships with the microscope software rather than on PyPI. Every function below is therefore
written against the shape of a SharkSEM session and marked `# unverified`; the names come from config.json
`sharksem` so a lab with the manual corrects them without editing code. Every SharkSEM call sits in
TescanBackend; the twin swaps it for a model with realistic pump, vent, run-up and scan times. No vendor
import at module top: `connected` reads False with a plain reason when the client library is absent.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import struct
import time

from openmhp.driver import DeviceFault, Driver, InvalidValue, Job, JobCancelled

HERE = pathlib.Path(__file__).parent
LABEL = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
VAC_READY, VAC_VENTED = ("ready",), ("vented",)
DEFAULT_NAMES = {"module": "sem", "client": "Sem", "connect": "Connect", "disconnect": "Disconnect",
                 "vac_status": "VacGetStatus", "vac_pump": "VacPump", "vac_vent": "VacVent",
                 "hv_beam_on": "HVBeamOn", "hv_beam_off": "HVBeamOff", "hv_get_beam": "HVGetBeam",
                 "hv_get_voltage": "HVGetVoltage", "hv_set_voltage": "HVSetVoltage",
                 "stg_move_to": "StgMoveTo", "stg_get_position": "StgGetPosition", "stg_is_busy": "StgIsBusy", "stg_stop": "StgStop",
                 "sc_set_speed": "ScSetSpeed", "sc_scan_xy": "ScScanXY", "sc_stop_scan": "ScStopScan", "fetch_image": "FetchImage",
                 "set_view_field": "SetViewField", "get_view_field": "GetViewField",
                 "dt_select": "DtSelect", "dt_enable": "DtEnable", "auto_wd": "AutoWD"}
DETECTOR_INDEX = {"se": 0, "bse": 1}                                     # unverified: detector numbering is per microscope
VAC_WORDS = {0: "ready", 1: "pumping", 2: "venting", 3: "vented", 4: "error"}   # unverified: VacGetStatus codes


def load_config() -> dict:
    p = HERE / "config.json"
    return json.loads(p.read_text(encoding="utf-8") or "{}") if p.is_file() else {}


def write_tiff(path: str, width: int, height: int, pixels: bytes) -> None:
    """A minimal uncompressed 8-bit greyscale TIFF (little-endian, one strip) any reader opens."""
    entries = [(256, 4, 1, width), (257, 4, 1, height), (258, 3, 1, 8), (259, 3, 1, 1), (262, 3, 1, 1),
               (273, 4, 1, 8 + 2 + 12 * 9 + 4), (277, 3, 1, 1), (278, 4, 1, height), (279, 4, 1, width * height)]
    ifd = struct.pack("<H", len(entries)) + b"".join(struct.pack("<HHII", *e) for e in entries) + struct.pack("<I", 0)
    with open(path, "wb") as f:
        f.write(b"II*\x00" + struct.pack("<I", 8) + ifd + pixels)


class TescanBackend:
    """Every SharkSEM call. Function names come from config.json `sharksem` because none could be verified."""

    def __init__(self, cfg: dict):
        self.cfg, self.sem = cfg, None
        self.names = {**DEFAULT_NAMES, **(cfg.get("sharksem") or {})}

    def _f(self, key: str):
        return getattr(self.sem, self.names[key])

    def open(self) -> None:
        if not self.cfg.get("host"):
            raise DeviceFault("config.json is missing (copy config.example.json and fill it in)")
        import importlib
        mod = importlib.import_module(self.names["module"])                 # TESCAN's SharkSEM client library (unverified module name)
        self.sem = getattr(mod, self.names["client"])()                      # unverified
        rc = self._f("connect")(self.cfg["host"], int(self.cfg.get("port", 8300)))   # unverified: negative return = failure
        if isinstance(rc, int) and rc < 0:
            raise DeviceFault(f"SharkSEM Connect to {self.cfg['host']}:{self.cfg.get('port', 8300)} returned {rc}", {"transient": True})
        self.vacuum_status()

    def close(self) -> None:
        if self.sem is not None:
            try:
                self._f("disconnect")()                                      # unverified
            except Exception:                                                # noqa: BLE001
                pass
            self.sem = None

    def vacuum_status(self) -> str:
        v = self._f("vac_status")()                                          # unverified: an integer code or a word
        return VAC_WORDS.get(v, str(v)).lower() if isinstance(v, int) else str(v).lower()

    def pump(self) -> None:
        self._f("vac_pump")()                                                # unverified

    def vent(self) -> None:
        self._f("vac_vent")()                                                # unverified

    def beam_on(self) -> bool:
        return bool(self._f("hv_get_beam")())                                # unverified

    def set_beam(self, on: bool) -> None:
        (self._f("hv_beam_on") if on else self._f("hv_beam_off"))()          # unverified

    def high_voltage_kv(self) -> float:
        return round(float(self._f("hv_get_voltage")()) / 1000, 3)           # unverified: volts

    def set_high_voltage_kv(self, kv: float) -> None:
        self._f("hv_set_voltage")(float(kv) * 1000)                          # unverified: volts

    def stage_position(self) -> dict:
        x, y, z, rot, tilt = self._f("stg_get_position")()                   # unverified: mm, mm, mm, deg, deg
        return {"x_mm": round(float(x), 4), "y_mm": round(float(y), 4), "z_mm": round(float(z), 4),
                "rotation_deg": round(float(rot), 3), "tilt_deg": round(float(tilt), 3)}

    def stage_busy(self) -> bool:
        return bool(self._f("stg_is_busy")())                                # unverified

    def move_stage(self, x, y, z, rot, tilt) -> None:
        self._f("stg_move_to")(float(x), float(y), float(z), float(rot), float(tilt))   # unverified

    def stage_stop(self) -> None:
        self._f("stg_stop")()                                                # unverified

    def set_view_field(self, mm: float) -> float:
        self._f("set_view_field")(float(mm))                                 # unverified: mm
        return float(self._f("get_view_field")())                            # unverified

    def select_detector(self, name: str) -> None:
        idx = DETECTOR_INDEX[name]
        self._f("dt_select")(0, idx)                                         # unverified: channel 0 <- detector idx
        self._f("dt_enable")(0, 1, 8)                                        # unverified: channel, enable, bits per pixel

    def auto_focus(self) -> None:
        self._f("auto_wd")(0)                                                # unverified

    def acquire_frame(self, width: int, height: int, speed: int) -> bytes:
        self._f("sc_set_speed")(int(speed))                                  # unverified
        self._f("sc_scan_xy")(0, int(width), int(height), 0, 0, int(width) - 1, int(height) - 1, 1)   # unverified: single frame
        data = self._f("fetch_image")(0, int(width) * int(height))           # unverified: channel, byte count
        return bytes(data)

    def stop_scan(self) -> None:
        self._f("sc_stop_scan")()                                            # unverified


class TescanSEM(Driver):
    def setup(self) -> None:
        self.cfg = load_config()
        self.hw = None
        self.running = False
        self.high_voltage = None
        self.last_image = None

    def make_backend(self):
        return TescanBackend(self.cfg)

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
                raise DeviceFault(f"the SharkSEM client library is not importable in this Python: {e}") from None
            except Exception as e:                               # noqa: BLE001  vendor boundary
                raise DeviceFault(f"cannot connect to SharkSEM at {self.cfg.get('host')}:{self.cfg.get('port', 8300)}: {type(e).__name__}: {e}",
                                  {"transient": True}) from None
            self.hw = hw
        return self.hw

    def _vendor(self, what, fn):
        try:
            return fn()
        except (DeviceFault, InvalidValue):
            raise
        except Exception as e:                                   # noqa: BLE001  vendor boundary
            raise DeviceFault(f"SharkSEM {what} failed: {type(e).__name__}: {e}", {"transient": True}) from None

    def _vac(self) -> str:
        return self._vendor("VacGetStatus", self._hw().vacuum_status)

    def on_read(self, name: str):
        if name == "connected":
            try:
                self._vac()
                return True
            except DeviceFault:
                return False
        hw = self._hw()
        if name == "vacuum_status":
            return self._vac()
        if name == "vacuum_ready":
            return self._vac() in VAC_READY
        if name == "beam_on":
            return self._vendor("HVGetBeam", hw.beam_on)
        if name == "high_voltage":
            return self._vendor("HVGetVoltage", hw.high_voltage_kv)
        if name == "stage_position":
            return self._vendor("StgGetPosition", hw.stage_position)
        if name == "stage_busy":
            return self._vendor("StgIsBusy", hw.stage_busy)
        if name == "robot_access_ready":
            return self._vac() in VAC_VENTED and not self._vendor("StgIsBusy", hw.stage_busy) and not self.running
        if name == "last_image":
            return self.last_image
        raise InvalidValue(f"unknown signal {name}")

    def on_write(self, name: str, value):
        if name != "high_voltage":
            raise InvalidValue(f"unknown setting {name}")
        hw = self._hw()
        if self._vendor("HVGetBeam", hw.beam_on):
            self._vendor("HVSetVoltage", lambda: hw.set_high_voltage_kv(value))
        self.high_voltage = float(value)
        return None

    def validate_params(self, action: str, params: dict) -> None:
        if action == "acquire_image":
            label = params.get("label", "image")
            if not isinstance(label, str) or not LABEL.match(label):
                raise InvalidValue("acquire_image.label must be 1-64 letters, digits, dash or underscore")

    def _image_dir(self) -> pathlib.Path:
        d = pathlib.Path(self.cfg.get("image_dir") or (pathlib.Path(os.environ.get("OPENMHP_HOME") or (pathlib.Path.home() / ".openmhp")) / "sim-data" / "tescan"))
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _wait(self, job: Job, done, what: str, limit_s: float, cancellable: bool = False) -> None:
        scale = self.time_scale()
        deadline = time.time() + limit_s * scale
        while not done():
            if cancellable:
                self.checkpoint(job)
            if time.time() > deadline:
                raise DeviceFault(f"{what} did not finish within {limit_s:.0f} s", {"transient": True})
            time.sleep(min(0.5, 2 * scale))

    def on_invoke(self, job: Job):
        hw, p, scale = self._hw(), job.params, self.time_scale()
        started = time.time()
        dur = lambda: round((time.time() - started) / scale, 1)     # noqa: E731
        if job.action == "load_sample":
            self.running = True
            try:
                self._vendor("VacPump", hw.pump)
                self._wait(job, lambda: self._vac() in VAC_READY, "pumping", float(self.cfg.get("pump_timeout_s", 900)))
            finally:
                self.running = False
            st = self._vac()
            return {"vacuum_status": st, "vacuum_ready": st in VAC_READY, "duration_s": dur()}
        if job.action == "unload_sample":
            self.running = True
            try:
                self._vendor("HVBeamOff", lambda: hw.set_beam(False))
                self._wait(job, lambda: not self._vendor("StgIsBusy", hw.stage_busy), "stage", 120)
                self._vendor("VacVent", hw.vent)
                self._wait(job, lambda: self._vac() in VAC_VENTED, "venting", float(self.cfg.get("pump_timeout_s", 900)))
            finally:
                self.running = False
            st = self._vac()
            return {"vacuum_status": st, "vacuum_ready": st in VAC_READY, "beam_on": self._vendor("HVGetBeam", hw.beam_on), "duration_s": dur()}
        if job.action == "set_beam":
            if p["enable"]:
                if self.high_voltage is not None:
                    self._vendor("HVSetVoltage", lambda: hw.set_high_voltage_kv(self.high_voltage))
                self._vendor("HVBeamOn", lambda: hw.set_beam(True))
                self._wait(job, lambda: self._vendor("HVGetBeam", hw.beam_on), "beam run-up", 300)
            else:
                self._vendor("HVBeamOff", lambda: hw.set_beam(False))
            return {"beam_on": self._vendor("HVGetBeam", hw.beam_on), "high_voltage_kv": self._vendor("HVGetVoltage", hw.high_voltage_kv), "duration_s": dur()}
        if job.action == "move_stage":
            cur = self._vendor("StgGetPosition", hw.stage_position)
            z = cur["z_mm"] if p.get("z_mm") is None else p["z_mm"]
            rot = cur["rotation_deg"] if p.get("rotation_deg") is None else p["rotation_deg"]
            tilt = cur["tilt_deg"] if p.get("tilt_deg") is None else p["tilt_deg"]
            self._vendor("StgMoveTo", lambda: hw.move_stage(p["x_mm"], p["y_mm"], z, rot, tilt))
            try:
                self._wait(job, lambda: not self._vendor("StgIsBusy", hw.stage_busy), "stage move", 300, cancellable=True)
            except JobCancelled:
                self._vendor("StgStop", hw.stage_stop)
                raise
            return self._vendor("StgGetPosition", hw.stage_position)
        if job.action == "auto_focus":
            self._vendor("AutoWD", hw.auto_focus)
            return {"focused": True}
        if job.action != "acquire_image":
            raise InvalidValue(f"unhandled action {job.action}")
        self.running = True
        try:
            ref_mm = float(self.cfg.get("reference_width_mm", 120.0))       # unverified: the width TESCAN's magnification refers to
            vf_mm = self._vendor("SetViewField", lambda: hw.set_view_field(ref_mm / float(p["magnification"])))
            self._vendor("DtSelect", lambda: hw.select_detector(p["detector"]))
            self.checkpoint(job, 0.1, phase="view field set")
            if p["auto_focus"]:
                self._vendor("AutoWD", hw.auto_focus)
            self.checkpoint(job, 0.2, phase="focused")
            w, h, n = int(p["width_px"]), int(p["height_px"]), int(p["frames"])
            acc = [0] * (w * h) if n > 1 else None
            frame = b""
            for i in range(n):
                try:
                    self.checkpoint(job, 0.2 + 0.7 * i / n, phase=f"frame {i + 1}/{n}")
                except JobCancelled:
                    self._vendor("ScStopScan", hw.stop_scan)
                    raise
                frame = self._vendor("FetchImage", lambda: hw.acquire_frame(w, h, p["scan_speed"]))
                if len(frame) != w * h:
                    raise DeviceFault(f"FetchImage returned {len(frame)} bytes for a {w}x{h} frame")
                if acc is not None:
                    for k, b in enumerate(frame):
                        acc[k] += b
            pixels = bytes(v // n for v in acc) if acc is not None else frame
            path = self._image_dir() / f"{time.strftime('%Y%m%d_%H%M%S')}_{p['label']}_{int(p['magnification'])}x.tif"
            write_tiff(str(path), w, h, pixels)
            result = {"file": str(path), "magnification": round(ref_mm / vf_mm, 1), "view_field_um": round(vf_mm * 1000, 3),
                      "width_px": w, "height_px": h, "high_voltage_kv": self._vendor("HVGetVoltage", hw.high_voltage_kv),
                      "scan_speed": int(p["scan_speed"]), "frames": n, "detector": p["detector"],
                      "stage": self._vendor("StgGetPosition", hw.stage_position), "duration_s": dur()}
        finally:
            self.running = False
        self.last_image = result
        self.emit_signal("last_image", result)
        return result

    def on_estop(self) -> None:
        if self.hw is not None:
            for stop in (self.hw.stop_scan, self.hw.stage_stop, lambda: self.hw.set_beam(False)):
                try:
                    stop()
                except Exception:                                # noqa: BLE001  must not raise
                    pass
        self.running = False

    def close(self) -> None:
        try:
            if self.hw is not None:
                self.hw.close()
        except Exception:                                        # noqa: BLE001
            pass
        super().close()

    @classmethod
    def probe(cls, cfg: dict) -> str:
        hw = TescanBackend(cfg)
        hw.open()
        try:
            return f"SharkSEM at {cfg.get('host')}:{cfg.get('port', 8300)}: vacuum {hw.vacuum_status()}, beam {'on' if hw.beam_on() else 'off'}, {hw.high_voltage_kv()} kV"
        finally:
            hw.close()
