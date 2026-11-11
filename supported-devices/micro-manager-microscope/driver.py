"""MHP driver for any microscope under Micro-Manager, through pymmcore-plus (CMMCorePlus).

Every Micro-Manager call lives in MMCoreBackend so the simulated twin can replace it. The core API used
(loadSystemConfiguration, setExposure/getExposure, snapImage/getImage, get/setXYPosition, get/setPosition,
setConfig/getAvailableConfigs, getCameraDevice, stop, waitForDevice) is the MMCore API as pymmcore-plus
documents it; see references/pymmcore.md. Images are written as uncompressed grayscale TIFF by this module
so neither numpy nor tifffile is needed to read the result.
"""
from __future__ import annotations

import json
import pathlib
import struct
import time

from openmhp.driver import DeviceFault, Driver, InvalidValue, Job, JobCancelled, LimitViolation

HERE = pathlib.Path(__file__).parent
MAX_STACK = 500


def load_config() -> dict:
    p = HERE / "config.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def write_tiff(path: pathlib.Path, width: int, height: int, bytes_per_pixel: int, pixels: bytes) -> None:
    """Minimal baseline TIFF: one strip, little-endian, 8- or 16-bit grayscale, no compression."""
    if bytes_per_pixel not in (1, 2):
        raise InvalidValue(f"cannot write {bytes_per_pixel * 8}-bit pixels as grayscale TIFF")
    if len(pixels) != width * height * bytes_per_pixel:
        raise InvalidValue(f"image buffer is {len(pixels)} bytes, expected {width * height * bytes_per_pixel}")
    entries = [(256, 4, 1, width), (257, 4, 1, height), (258, 3, 1, 8 * bytes_per_pixel), (259, 3, 1, 1),
               (262, 3, 1, 1), (273, 4, 1, 0), (277, 3, 1, 1), (278, 4, 1, height), (279, 4, 1, len(pixels))]
    ifd_offset = 8
    data_offset = ifd_offset + 2 + 12 * len(entries) + 4
    entries[5] = (273, 4, 1, data_offset)
    out = bytearray(b"II*\x00" + struct.pack("<I", ifd_offset) + struct.pack("<H", len(entries)))
    for tag, typ, count, value in entries:
        out += struct.pack("<HHI", tag, typ, count)
        out += struct.pack("<HH", value, 0) if typ == 3 else struct.pack("<I", value)
    out += struct.pack("<I", 0)
    out += pixels
    path.write_bytes(bytes(out))


class MMCoreBackend:
    """pymmcore-plus calls, nothing else."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.core = None

    def open(self) -> None:
        if not self.cfg.get("config_file"):
            raise DeviceFault("config.json is missing or has no config_file (copy config.example.json and fill it in)")
        from pymmcore_plus import CMMCorePlus
        self.core = CMMCorePlus()
        if self.cfg["config_file"] == "demo":
            self.core.loadSystemConfiguration()                          # pymmcore-plus ships MMConfig_demo.cfg
        else:
            self.core.loadSystemConfiguration(self.cfg["config_file"])

    def close(self) -> None:
        if self.core is not None:
            self.core.unloadAllDevices()

    def camera(self) -> str:
        return str(self.core.getCameraDevice())

    def exposure(self) -> float:
        return float(self.core.getExposure())

    def set_exposure(self, ms: float) -> None:
        self.core.setExposure(float(ms))

    def xy(self) -> tuple[float, float]:
        x, y = self.core.getXYPosition()
        return float(x), float(y)

    def move_xy(self, x: float, y: float) -> None:
        self.core.setXYPosition(float(x), float(y))
        self.core.waitForDevice(self.core.getXYStageDevice())

    def z(self) -> float:
        return float(self.core.getPosition())

    def move_z(self, z: float) -> None:
        self.core.setPosition(float(z))
        self.core.waitForDevice(self.core.getFocusDevice())

    def configs(self, group: str) -> list[str]:
        if group not in list(self.core.getAvailableConfigGroups()):
            return []
        return [str(c) for c in self.core.getAvailableConfigs(group)]

    def current_config(self, group: str):
        c = self.core.getCurrentConfig(group) if group in list(self.core.getAvailableConfigGroups()) else ""
        return str(c) or None

    def set_config(self, group: str, preset: str) -> None:
        self.core.setConfig(group, preset)
        self.core.waitForConfig(group, preset)                                   # unverified: waitForConfig exists in MMCore

    def snap(self) -> tuple[int, int, int, bytes]:
        """(width, height, bytes per pixel, little-endian pixel bytes)."""
        core = self.core
        core.snapImage()
        img = core.getImage()                                                    # numpy array
        bpp = int(img.dtype.itemsize)
        raw = img.astype("<u2" if bpp == 2 else "u1").tobytes()
        return int(core.getImageWidth()), int(core.getImageHeight()), bpp, raw

    def stop(self) -> None:
        core = self.core
        for label in (core.getXYStageDevice(), core.getFocusDevice()):
            if label:
                core.stop(label)


class MicroManagerMicroscope(Driver):
    def setup(self) -> None:
        self.cfg = load_config()
        self.hw = None
        self.group = str(self.cfg.get("channel_group") or "Channel")
        self.last_image = None

    def make_backend(self):
        return MMCoreBackend(self.cfg)

    def time_scale(self) -> float:
        return 1.0

    def _hw(self):
        if self.hw is None:
            hw = self.make_backend()
            try:
                hw.open()
            except DeviceFault:
                raise
            except Exception as e:                       # noqa: BLE001  pymmcore / config errors
                raise DeviceFault(f"cannot load the Micro-Manager configuration: {type(e).__name__}: {e}") from None
            self.hw = hw
        return self.hw

    def _call(self, what: str, fn, *args):
        try:
            return fn(*args)
        except (DeviceFault, InvalidValue, LimitViolation, JobCancelled):
            raise
        except Exception as e:                           # noqa: BLE001
            raise DeviceFault(f"{what} failed: {type(e).__name__}: {e}") from None

    def on_read(self, name: str):
        if name == "connected":
            try:
                self._hw()
                return True
            except DeviceFault:
                return False
        if name == "config_loaded":
            return self.hw is not None
        hw = self._hw()
        if name == "xy_position":
            x, y = self._call("getXYPosition", hw.xy)
            return {"x_um": round(x, 3), "y_um": round(y, 3)}
        if name == "z_um":
            return round(self._call("getPosition", hw.z), 3)
        if name == "exposure_ms":
            return self._call("getExposure", hw.exposure)
        if name == "camera":
            return self._call("getCameraDevice", hw.camera)
        if name == "channel":
            return self._call("getCurrentConfig", hw.current_config, self.group)
        if name == "channels":
            return self._call("getAvailableConfigs", hw.configs, self.group)
        if name == "last_image":
            return self.last_image
        raise InvalidValue(f"unknown signal {name}")

    def on_write(self, name: str, value) -> None:
        hw = self._hw()
        if name == "exposure_ms":
            self._call("setExposure", hw.set_exposure, value)
        elif name == "z_um":
            self._soft_limit("z_um", value)
            self._call("setPosition", hw.move_z, value)
        elif name == "channel":
            presets = self._call("getAvailableConfigs", hw.configs, self.group)
            if value not in presets:
                raise InvalidValue(f"channel {value!r} is not a preset of config group {self.group!r}; available: {presets}",
                                   {"enum": presets})
            self._call("setConfig", hw.set_config, self.group, value)
        else:
            raise InvalidValue(f"unknown setting {name}")

    def _soft_limit(self, axis: str, value: float) -> None:
        """The lab's travel limits from config.json (soft_limits_um: {x: [lo, hi], y: ..., z: ...}), if given."""
        lim = (self.cfg.get("soft_limits_um") or {}).get(axis[0])
        if lim and not lim[0] <= value <= lim[1]:
            raise LimitViolation(f"{axis}={value} outside the lab's soft limits {lim}", {"min": lim[0], "max": lim[1]})

    def validate_params(self, action: str, params: dict) -> None:
        if action == "move_xy":
            self._soft_limit("x_um", params["x_um"])
            self._soft_limit("y_um", params["y_um"])
        if action == "acquire_z_stack":
            n = int(abs(params["z_end_um"] - params["z_start_um"]) / params["step_um"]) + 1
            if n > MAX_STACK:
                raise LimitViolation(f"acquire_z_stack: {n} planes exceeds the maximum of {MAX_STACK}", {"max": MAX_STACK})
            for z in (params["z_start_um"], params["z_end_um"]):
                self._soft_limit("z_um", z)

    # ---- images ----------------------------------------------------------------------------- #
    def _folder(self, job: Job) -> pathlib.Path:
        root = pathlib.Path(self.cfg.get("data_dir") or HERE / "data")
        folder = root / f"{time.strftime('%Y%m%d-%H%M%S')}_{job.action}_{job.id}"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _snap(self, hw, folder: pathlib.Path, index: int) -> dict:
        w, h, bpp, raw = self._call("snapImage/getImage", hw.snap)
        file = folder / f"image_{index:04d}.tif"
        write_tiff(file, w, h, bpp, raw)
        return {"file": str(file), "width": w, "height": h, "bit_depth": 8 * bpp}

    def on_invoke(self, job: Job):
        hw = self._hw()
        p = job.params
        if job.action == "snap":
            folder = self._folder(job)
            img = self._snap(hw, folder, 0)
            result = {**img, "exposure_ms": self._call("getExposure", hw.exposure), "z_um": round(self._call("getPosition", hw.z), 3),
                      "channel": self._call("getCurrentConfig", hw.current_config, self.group), "label": p.get("label")}
            self.last_image = result
            self.emit_signal("last_image", result)
            return result
        if job.action == "move_xy":
            self.checkpoint(job, 0.0, phase="moving")
            self._call("setXYPosition", hw.move_xy, p["x_um"], p["y_um"])
            x, y = self._call("getXYPosition", hw.xy)
            self.emit_signal("xy_position", {"x_um": round(x, 3), "y_um": round(y, 3)})
            return {"x_um": round(x, 3), "y_um": round(y, 3)}
        if job.action == "acquire_z_stack":
            z0, z1, step = p["z_start_um"], p["z_end_um"], p["step_um"]
            n = int(abs(z1 - z0) / step) + 1
            sign = 1 if z1 >= z0 else -1
            folder, files, z_home = self._folder(job), [], self._call("getPosition", hw.z)
            try:
                for k in range(n):
                    self.checkpoint(job, k / n, phase=f"plane {k + 1}/{n}")
                    z = z0 + sign * k * step
                    self._call("setPosition", hw.move_z, z)
                    files.append(self._snap(hw, folder, k)["file"])
            finally:
                if p.get("return_to_start"):
                    try:
                        hw.move_z(z_home)
                    except Exception:                    # noqa: BLE001  best effort after a cancel or fault
                        pass
            return {"files": files, "count": len(files), "folder": str(folder), "z_start_um": z0, "z_end_um": z1,
                    "step_um": step, "channel": self._call("getCurrentConfig", hw.current_config, self.group),
                    "exposure_ms": self._call("getExposure", hw.exposure), "label": p.get("label")}
        raise InvalidValue(f"unhandled action {job.action}")

    def on_estop(self) -> None:
        try:
            if self.hw is not None:
                self.hw.stop()
        except Exception:                                # noqa: BLE001  must not raise
            pass

    # ---- setup-time checks (`mhp node setup`) ------------------------------------------------ #
    @classmethod
    def discover(cls, cfg: dict, what: str) -> list:
        if what != "configs":
            return []
        folder = pathlib.Path(cfg.get("config_dir") or "")
        out = [str(f) for f in sorted(folder.glob("*.cfg"))] if folder.is_dir() else []
        return out + [("demo", "pymmcore-plus's built-in MMConfig_demo.cfg (DemoCamera, no hardware)")]

    @classmethod
    def probe(cls, cfg: dict) -> str:
        try:
            import pymmcore_plus                         # noqa: F401
        except ImportError:
            raise DeviceFault("pymmcore-plus is not installed (pip install pymmcore-plus; then mmcore install)") from None
        hw = MMCoreBackend(cfg)
        hw.open()
        try:
            return f"configuration loaded; camera {hw.camera()}, exposure {hw.exposure()} ms, z {hw.z():.2f} um"
        finally:
            hw.close()
