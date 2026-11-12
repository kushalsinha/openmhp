"""MHP driver template for a ZEISS EVO / Sigma / GeminiSEM under SmartSEM through the SmartSEM Remote API, the
COM automation object ZEISS installs with SmartSEM on the microscope PC (Windows only; reached with pywin32).

ZEISS's knowledge base documents installing the "Remote API Client" and a "SmartSEM API Test" application but
not the API itself, which is given to licensees. Every member below is therefore written against the shape
such a remote API must have (initialise, Get/Set of named parameters, Execute of named commands, an image grab,
a stage move) and marked `# unverified`; the ProgID, member, parameter and command names come from config.json
`smartsem` so a lab with the reference corrects them without editing code. Every COM call sits in ZeissBackend;
the twin swaps it for a model with realistic pump, vent, run-up and grab times. No vendor import at module top:
`connected` reads False with a plain reason when pywin32 or the API is absent.
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
DEFAULT_NAMES = {"progid": "CZ.EMApiCtrl.1", "initialise": "InitialiseRemoting", "close": "ClosingControl",
                 "get": "Get", "set": "Set", "execute": "Execute", "grab": "Grab", "move_stage": "MoveStage",
                 "vac_status": "DP_VAC_STATUS", "vac_ready_word": "Ready", "vac_atm_word": "At atmosphere",
                 "cmd_pump": "CMD_PUMP", "cmd_vent": "CMD_VENT",
                 "runup_state": "DP_RUNUPSTATE", "runup_on_word": "On", "actual_kv": "AP_ACTUALKV", "manual_kv": "AP_MANUALKV",
                 "cmd_eht_on": "CMD_EHT_ON", "cmd_eht_off": "CMD_EHT_OFF",
                 "stage_x": "AP_STAGE_AT_X", "stage_y": "AP_STAGE_AT_Y", "stage_z": "AP_STAGE_AT_Z",
                 "stage_r": "AP_STAGE_AT_R", "stage_t": "AP_STAGE_AT_T", "stage_is": "DP_STAGE_IS", "stage_busy_word": "Busy",
                 "cmd_stage_stop": "CMD_STAGE_STOP", "mag": "AP_MAG", "scan_rate": "DP_SCAN_RATE",
                 "detector": "DP_DETECTOR_CHANNEL", "cmd_auto_focus": "CMD_AUTO_FOCUS", "cmd_freeze": "CMD_FREEZE_ALL"}
DETECTOR_NAMES = {"se2": "SE2", "inlens": "InLens", "bsd": "BSD"}       # unverified: SmartSEM detector names


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


def read_tiff_pixels(path: str) -> bytes:
    """The strip of an 8-bit single-strip TIFF this package (or the twin) wrote; used to average frames."""
    data = pathlib.Path(path).read_bytes()
    return data[8 + 2 + 12 * 9 + 4:]


class ZeissBackend:
    """Every SmartSEM Remote API call. Names come from config.json `smartsem` because none could be verified."""

    def __init__(self, cfg: dict):
        self.cfg, self.api = cfg, None
        self.names = {**DEFAULT_NAMES, **(cfg.get("smartsem") or {})}

    def _call(self, key: str, *args):
        return getattr(self.api, self.names[key])(*args)

    def open(self) -> None:
        if not self.cfg.get("image_dir"):
            raise DeviceFault("config.json is missing (copy config.example.json and fill it in)")
        import win32com.client                                               # pywin32, Windows
        self.api = win32com.client.Dispatch(self.names["progid"])            # unverified ProgID
        rc = self._call("initialise")                                        # unverified: 0 on success
        if isinstance(rc, int) and rc != 0:
            raise DeviceFault(f"SmartSEM InitialiseRemoting returned {rc}", {"transient": True})
        self.vacuum_status()

    def close(self) -> None:
        if self.api is not None:
            try:
                self._call("close")                                          # unverified
            except Exception:                                                # noqa: BLE001
                pass
            self.api = None

    def get(self, key: str):
        return self._call("get", self.names[key])                            # unverified: Get(parameter) -> value

    def set(self, key: str, value) -> None:
        self._call("set", self.names[key], value)                            # unverified: Set(parameter, value)

    def execute(self, key: str) -> None:
        self._call("execute", self.names[key])                               # unverified: Execute(command)

    def vacuum_status(self) -> str:
        return str(self.get("vac_status"))

    def pump(self) -> None:
        self.execute("cmd_pump")

    def vent(self) -> None:
        self.execute("cmd_vent")

    def beam_on(self) -> bool:
        return str(self.get("runup_state")).lower() == self.names["runup_on_word"].lower()

    def set_beam(self, on: bool) -> None:
        self.execute("cmd_eht_on" if on else "cmd_eht_off")

    def high_voltage_kv(self) -> float:
        return round(float(self.get("actual_kv")), 3)                       # unverified: kV

    def set_high_voltage_kv(self, kv: float) -> None:
        self.set("manual_kv", float(kv))                                     # unverified: kV

    def stage_position(self) -> dict:
        return {"x_mm": round(float(self.get("stage_x")), 4), "y_mm": round(float(self.get("stage_y")), 4),
                "z_mm": round(float(self.get("stage_z")), 4), "rotation_deg": round(float(self.get("stage_r")), 3),
                "tilt_deg": round(float(self.get("stage_t")), 3)}           # unverified: mm and degrees

    def stage_busy(self) -> bool:
        return str(self.get("stage_is")).lower() == self.names["stage_busy_word"].lower()

    def move_stage(self, x, y, z, rot, tilt) -> None:
        self._call("move_stage", float(x), float(y), float(z), float(tilt), float(rot), 0.0)   # unverified: MoveStage(x, y, z, t, r, m)

    def stage_stop(self) -> None:
        self.execute("cmd_stage_stop")

    def set_magnification(self, mag: float) -> float:
        self.set("mag", float(mag))                                          # unverified: AP_MAG
        return float(self.get("mag"))

    def set_scan_rate(self, speed: int) -> None:
        self.set("scan_rate", int(speed))                                    # unverified

    def select_detector(self, name: str) -> None:
        self.set("detector", DETECTOR_NAMES[name])                          # unverified

    def auto_focus(self) -> None:
        self.execute("cmd_auto_focus")

    def grab(self, width: int, height: int, path: str) -> None:
        self._call("grab", 0, 0, int(width), int(height), 0, path)           # unverified: Grab(x, y, width, height, reduction, filename) writes a TIFF

    def freeze(self) -> None:
        self.execute("cmd_freeze")


class ZeissSEM(Driver):
    def setup(self) -> None:
        self.cfg = load_config()
        self.hw = None
        self.running = False
        self.high_voltage = None
        self.last_image = None

    def make_backend(self):
        return ZeissBackend(self.cfg)

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
                raise DeviceFault("pywin32 (win32com) is not installed or this is not the SmartSEM PC (Windows only)") from None
            except Exception as e:                               # noqa: BLE001  vendor boundary
                raise DeviceFault(f"cannot open the SmartSEM Remote API ({self.cfg.get('smartsem', {}).get('progid', 'CZ.EMApiCtrl.1')}): "
                                  f"{type(e).__name__}: {e}", {"transient": True}) from None
            self.hw = hw
        return self.hw

    def _vendor(self, what, fn):
        try:
            return fn()
        except (DeviceFault, InvalidValue):
            raise
        except Exception as e:                                   # noqa: BLE001  vendor boundary
            raise DeviceFault(f"SmartSEM {what} failed: {type(e).__name__}: {e}", {"transient": True}) from None

    def _vac(self) -> str:
        return self._vendor("Get DP_VAC_STATUS", self._hw().vacuum_status)

    def _vac_ready(self, word: str | None = None) -> bool:
        return (word or self._vac()).lower() == self._hw().names["vac_ready_word"].lower()

    def _vac_atm(self, word: str | None = None) -> bool:
        return (word or self._vac()).lower() == self._hw().names["vac_atm_word"].lower()

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
            return self._vac_ready()
        if name == "beam_on":
            return self._vendor("Get DP_RUNUPSTATE", hw.beam_on)
        if name == "high_voltage":
            return self._vendor("Get AP_ACTUALKV", hw.high_voltage_kv)
        if name == "stage_position":
            return self._vendor("Get AP_STAGE_AT_*", hw.stage_position)
        if name == "stage_busy":
            return self._vendor("Get DP_STAGE_IS", hw.stage_busy)
        if name == "robot_access_ready":
            return self._vac_atm() and not self._vendor("Get DP_STAGE_IS", hw.stage_busy) and not self.running
        if name == "last_image":
            return self.last_image
        raise InvalidValue(f"unknown signal {name}")

    def on_write(self, name: str, value):
        if name != "high_voltage":
            raise InvalidValue(f"unknown setting {name}")
        hw = self._hw()
        if self._vendor("Get DP_RUNUPSTATE", hw.beam_on):
            self._vendor("Set AP_MANUALKV", lambda: hw.set_high_voltage_kv(value))
        self.high_voltage = float(value)
        return None

    def validate_params(self, action: str, params: dict) -> None:
        if action == "acquire_image":
            label = params.get("label", "image")
            if not isinstance(label, str) or not LABEL.match(label):
                raise InvalidValue("acquire_image.label must be 1-64 letters, digits, dash or underscore")

    def _image_dir(self) -> pathlib.Path:
        d = pathlib.Path(self.cfg.get("image_dir") or (pathlib.Path(os.environ.get("OPENMHP_HOME") or (pathlib.Path.home() / ".openmhp")) / "sim-data" / "zeiss"))
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
                self._vendor("Execute CMD_PUMP", hw.pump)
                self._wait(job, self._vac_ready, "pumping", float(self.cfg.get("pump_timeout_s", 900)))
            finally:
                self.running = False
            st = self._vac()
            return {"vacuum_status": st, "vacuum_ready": self._vac_ready(st), "duration_s": dur()}
        if job.action == "unload_sample":
            self.running = True
            try:
                self._vendor("Execute CMD_EHT_OFF", lambda: hw.set_beam(False))
                self._wait(job, lambda: not self._vendor("Get DP_STAGE_IS", hw.stage_busy), "stage", 120)
                self._vendor("Execute CMD_VENT", hw.vent)
                self._wait(job, self._vac_atm, "venting", float(self.cfg.get("pump_timeout_s", 900)))
            finally:
                self.running = False
            st = self._vac()
            return {"vacuum_status": st, "vacuum_ready": self._vac_ready(st), "beam_on": self._vendor("Get DP_RUNUPSTATE", hw.beam_on), "duration_s": dur()}
        if job.action == "set_beam":
            if p["enable"]:
                if self.high_voltage is not None:
                    self._vendor("Set AP_MANUALKV", lambda: hw.set_high_voltage_kv(self.high_voltage))
                self._vendor("Execute CMD_EHT_ON", lambda: hw.set_beam(True))
                self._wait(job, lambda: self._vendor("Get DP_RUNUPSTATE", hw.beam_on), "EHT run-up", 300)
            else:
                self._vendor("Execute CMD_EHT_OFF", lambda: hw.set_beam(False))
            return {"beam_on": self._vendor("Get DP_RUNUPSTATE", hw.beam_on), "high_voltage_kv": self._vendor("Get AP_ACTUALKV", hw.high_voltage_kv), "duration_s": dur()}
        if job.action == "move_stage":
            cur = self._vendor("Get AP_STAGE_AT_*", hw.stage_position)
            z = cur["z_mm"] if p.get("z_mm") is None else p["z_mm"]
            rot = cur["rotation_deg"] if p.get("rotation_deg") is None else p["rotation_deg"]
            tilt = cur["tilt_deg"] if p.get("tilt_deg") is None else p["tilt_deg"]
            self._vendor("MoveStage", lambda: hw.move_stage(p["x_mm"], p["y_mm"], z, rot, tilt))
            try:
                self._wait(job, lambda: not self._vendor("Get DP_STAGE_IS", hw.stage_busy), "stage move", 300, cancellable=True)
            except JobCancelled:
                self._vendor("Execute CMD_STAGE_STOP", hw.stage_stop)
                raise
            return self._vendor("Get AP_STAGE_AT_*", hw.stage_position)
        if job.action == "auto_focus":
            self._vendor("Execute CMD_AUTO_FOCUS", hw.auto_focus)
            return {"focused": True}
        if job.action != "acquire_image":
            raise InvalidValue(f"unhandled action {job.action}")
        self.running = True
        try:
            mag = self._vendor("Set AP_MAG", lambda: hw.set_magnification(p["magnification"]))
            self._vendor("Set DP_DETECTOR_CHANNEL", lambda: hw.select_detector(p["detector"]))
            self._vendor("Set DP_SCAN_RATE", lambda: hw.set_scan_rate(p["scan_speed"]))
            self.checkpoint(job, 0.1, phase="magnification set")
            if p["auto_focus"]:
                self._vendor("Execute CMD_AUTO_FOCUS", hw.auto_focus)
            self.checkpoint(job, 0.2, phase="focused")
            w, h, n = int(p["width_px"]), int(p["height_px"]), int(p["frames"])
            stem = f"{time.strftime('%Y%m%d_%H%M%S')}_{p['label']}_{int(mag)}x"
            path = self._image_dir() / f"{stem}.tif"
            acc = [0] * (w * h) if n > 1 else None
            for i in range(n):
                try:
                    self.checkpoint(job, 0.2 + 0.7 * i / n, phase=f"frame {i + 1}/{n}")
                except JobCancelled:
                    self._vendor("Execute CMD_FREEZE_ALL", hw.freeze)
                    raise
                target = path if n == 1 else self._image_dir() / f"{stem}_f{i + 1}.tif"
                self._vendor("Grab", lambda: hw.grab(w, h, str(target)))
                if acc is not None:
                    frame = read_tiff_pixels(str(target))
                    if len(frame) != w * h:
                        raise DeviceFault(f"Grab wrote {len(frame)} pixel bytes for a {w}x{h} frame")
                    for k, b in enumerate(frame):
                        acc[k] += b
                    target.unlink()
            if acc is not None:
                write_tiff(str(path), w, h, bytes(v // n for v in acc))
            result = {"file": str(path), "magnification": round(mag, 1), "width_px": w, "height_px": h,
                      "high_voltage_kv": self._vendor("Get AP_ACTUALKV", hw.high_voltage_kv),
                      "scan_speed": int(p["scan_speed"]), "frames": n, "detector": p["detector"],
                      "stage": self._vendor("Get AP_STAGE_AT_*", hw.stage_position), "duration_s": dur()}
        finally:
            self.running = False
        self.last_image = result
        self.emit_signal("last_image", result)
        return result

    def on_estop(self) -> None:
        if self.hw is not None:
            for stop in (self.hw.freeze, self.hw.stage_stop, lambda: self.hw.set_beam(False)):
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
        import sys
        if sys.platform != "win32":
            raise DeviceFault("the SmartSEM Remote API is a COM object on the microscope PC; this is not Windows")
        hw = ZeissBackend(cfg)
        hw.open()
        try:
            return f"SmartSEM Remote API opened: vacuum {hw.vacuum_status()}, EHT {'on' if hw.beam_on() else 'off'}, {hw.high_voltage_kv()} kV"
        finally:
            hw.close()
