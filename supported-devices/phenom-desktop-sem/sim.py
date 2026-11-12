"""Simulated twin of the Phenom: a fake PyPhenom with the XL's loading time (60 s), a 100 x 100 mm stage,
the magnification range and the operational modes, writing real 8-bit TIFFs of the requested size.
Time scaled by OPENMHP_SIM_TIME_SCALE."""
from __future__ import annotations

import importlib.util
import os
import pathlib
import random
import struct
import sys
import time

_spec = importlib.util.spec_from_file_location(__name__ + "_real", pathlib.Path(__file__).with_name("driver.py"))
real = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = real
_spec.loader.exec_module(real)

LOAD_S, UNLOAD_S = 60, 20


class PpiError(Exception):
    """What the vendor library raises; the driver turns it into a DeviceFault at the backend boundary."""


def write_tiff(path: str, width: int, height: int, seed: int) -> None:
    """A minimal uncompressed 8-bit greyscale TIFF (little-endian, one strip) any reader opens."""
    rnd = random.Random(seed)
    pixels = bytes(min(255, max(0, 128 + int(60 * ((x * 7 + y * 3) % 17 / 8.5 - 1)) + rnd.randint(-20, 20)))
                   for y in range(height) for x in range(width)) if width * height <= 65536 else rnd.randbytes(width * height)
    entries = [(256, 4, 1, width), (257, 4, 1, height), (258, 3, 1, 8), (259, 3, 1, 1), (262, 3, 1, 1),
               (273, 4, 1, 8 + 2 + 12 * 9 + 4), (277, 3, 1, 1), (278, 4, 1, height), (279, 4, 1, width * height)]
    ifd = struct.pack("<H", len(entries)) + b"".join(struct.pack("<HHII", *e) for e in entries) + struct.pack("<I", 0)
    with open(path, "wb") as f:
        f.write(b"II*\x00" + struct.pack("<I", 8) + ifd + pixels)


class _Position:
    def __init__(self, x, y):
        self.x, self.y = x, y


class _Size:
    def __init__(self, w, h):
        self.width, self.height = w, h


class _ScanParams:
    size = _Size(1920, 1200)
    nFrames = 1
    dwellTime = 1e-6
    detector = "All"


class _Enum:
    def __init__(self, *names):
        for n in names:
            setattr(self, n, n)


class FakePhenom:
    """The PyPhenom surface this package uses, answered by a scaled clock."""

    def __init__(self, scale: float, log: list):
        self.scale, self.log = scale, log
        self.instrument, self.op, self.op_until, self.op_next = "Operational", "Unloaded", 0.0, None
        self.x, self.y, self.ht, self.hfw = 0.0, 0.0, -10000.0, 0.1 / 1000

    def _tick(self):
        if self.op_next and time.monotonic() >= self.op_until:
            self.op, self.op_next = self.op_next, None

    def GetInstrumentMode(self):
        return f"InstrumentMode.{self.instrument}"

    def GetOperationalMode(self):
        self._tick()
        return f"OperationalMode.{self.op}"

    def Load(self):
        self.log.append("Load")
        if self.op != "Unloaded":
            raise PpiError("holder is already loaded")
        self.instrument = "Operational"
        self.op, self.op_next, self.op_until = "Loading", "LiveSem", time.monotonic() + LOAD_S * self.scale

    def Unload(self):
        self.log.append("Unload")
        self.op, self.op_next, self.op_until = "Unloading", "Unloaded", time.monotonic() + UNLOAD_S * self.scale

    def Activate(self):
        self.log.append("Activate")
        self.instrument = "Operational"

    def Standby(self):
        self.log.append("Standby")
        self.instrument = "Standby"

    def GetStagePosition(self):
        return _Position(self.x, self.y)

    def MoveTo(self, pos):
        self.log.append(f"MoveTo {pos.x:.6f} {pos.y:.6f}")
        if abs(pos.x) > 0.05 or abs(pos.y) > 0.05:
            raise PpiError("stage position out of range")
        time.sleep(min(0.2, 2 * self.scale))
        self.x, self.y = pos.x, pos.y

    def GetSemHighTension(self):
        return self.ht

    def SetSemHighTension(self, volts):
        self.log.append(f"SetSemHighTension {volts:.0f}")
        self.ht = float(volts)

    def GetSemHfw(self):
        return self.hfw

    def SetSemHfw(self, hfw):
        self.log.append(f"SetSemHfw {hfw:.3e}")
        self.hfw = max(0.1 / 200000, min(0.1 / 160, float(hfw)))

    def GetSemMagnification(self):
        return 0.1 / self.hfw

    def SemAutoFocus(self):
        self.log.append("SemAutoFocus")
        time.sleep(min(0.2, 8 * self.scale))

    def SemAcquireImage(self, sp):
        if self.instrument != "Operational" or self.op != "LiveSem":
            raise PpiError("SEM is not live")
        t = sp.size.width * sp.size.height * sp.dwellTime * sp.nFrames
        self.log.append(f"SemAcquireImage {sp.size.width}x{sp.size.height} {sp.nFrames}f {sp.detector}")
        time.sleep(min(0.5, t * self.scale))
        return {"width": sp.size.width, "height": sp.size.height, "seed": int(self.x * 1e6 + self.y * 1e3)}


class FakePPI:
    """The module-level names PyPhenom provides."""

    def __init__(self, scale, log):
        self.scale, self.log = scale, log
        self.Position, self.Size, self.ScanParams = _Position, _Size, _ScanParams
        self.DetectorMode = _Enum("All", "TopoA", "TopoB", "Sed")

    def Phenom(self, address, instrument_id, password):
        self.log.append(f"connect {address} {instrument_id}")
        return FakePhenom(self.scale, self.log)

    def Save(self, acq, path):
        self.log.append(f"Save {pathlib.Path(path).name}")
        write_tiff(path, acq["width"], acq["height"], acq["seed"])


class SimBackend(real.PhenomBackend):
    def __init__(self, cfg, scale):
        super().__init__(cfg)
        self.scale, self.log = scale, []

    def open(self):
        self.ppi = FakePPI(self.scale, self.log)
        self.phenom = self.ppi.Phenom(self.cfg["address"], self.cfg.get("instrument_id", ""), "")


class SimPhenomSEM(real.PhenomSEM):
    def setup(self) -> None:
        super().setup()
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        self.cfg = {"address": "sim", "instrument_id": "MVE0123456789", "screen_width_m": 0.1, "load_timeout_s": 300}

    def time_scale(self) -> float:
        return self.scale

    def make_backend(self):
        return SimBackend(self.cfg, self.scale)
