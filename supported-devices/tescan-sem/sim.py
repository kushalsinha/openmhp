"""Simulated twin of a TESCAN SEM: a fake SharkSEM client with a 180 s pump, 90 s vent, 30 s beam run-up,
a five-axis stage that takes time to arrive, and frames whose scan time follows the scan speed. Time scaled
by OPENMHP_SIM_TIME_SCALE."""
from __future__ import annotations

import importlib.util
import os
import pathlib
import random
import sys
import time

_spec = importlib.util.spec_from_file_location(__name__ + "_real", pathlib.Path(__file__).with_name("driver.py"))
real = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = real
_spec.loader.exec_module(real)

PUMP_S, VENT_S, RUNUP_S = 180, 90, 30
DWELL_US = {1: 0.1, 2: 0.2, 3: 0.32, 4: 0.5, 5: 1.0, 6: 2.0, 7: 3.2, 8: 5.0, 9: 10.0, 10: 20.0}


class SharkSemError(Exception):
    """What the vendor library raises; the driver turns it into a DeviceFault at the backend boundary."""


class FakeSem:
    """The SharkSEM client surface this package uses, answered by a scaled clock."""

    def __init__(self, scale: float, log: list):
        self.scale, self.log = scale, log
        self.vac, self.vac_next, self.vac_until = 3, None, 0.0           # 3 = vented
        self.beam, self.beam_until, self.volts = False, 0.0, 10000.0
        self.pos, self.target, self.stage_until = [0.0, 0.0, 15.0, 0.0, 0.0], None, 0.0
        self.view_field, self.speed, self.channel = 0.1, 5, {}
        self.scanning = False

    def _tick(self):
        now = time.monotonic()
        if self.vac_next is not None and now >= self.vac_until:
            self.vac, self.vac_next = self.vac_next, None
        if self.target and now >= self.stage_until:
            self.pos, self.target = self.target, None

    def Connect(self, host, port):
        self.log.append(f"Connect {host} {port}")
        return 0

    def Disconnect(self):
        self.log.append("Disconnect")

    def VacGetStatus(self):
        self._tick()
        return self.vac

    def VacPump(self):
        self.log.append("VacPump")
        self.vac, self.vac_next, self.vac_until = 1, 0, time.monotonic() + PUMP_S * self.scale

    def VacVent(self):
        self.log.append("VacVent")
        if self.beam:
            raise SharkSemError("cannot vent with the high voltage on")
        self.vac, self.vac_next, self.vac_until = 2, 3, time.monotonic() + VENT_S * self.scale

    def HVBeamOn(self):
        self.log.append("HVBeamOn")
        self._tick()
        if self.vac != 0:
            raise SharkSemError("vacuum not ready")
        self.beam, self.beam_until = True, time.monotonic() + RUNUP_S * self.scale

    def HVBeamOff(self):
        self.log.append("HVBeamOff")
        self.beam = False

    def HVGetBeam(self):
        return self.beam and time.monotonic() >= self.beam_until

    def HVGetVoltage(self):
        return self.volts

    def HVSetVoltage(self, volts):
        self.log.append(f"HVSetVoltage {volts:.0f}")
        self.volts = float(volts)

    def StgGetPosition(self):
        self._tick()
        return tuple(self.pos)

    def StgIsBusy(self):
        self._tick()
        return self.target is not None

    def StgMoveTo(self, x, y, z, rot, tilt):
        self.log.append(f"StgMoveTo {x:.3f} {y:.3f} {z:.3f} {rot:.2f} {tilt:.2f}")
        dist = max(abs(x - self.pos[0]), abs(y - self.pos[1]), abs(z - self.pos[2]))
        self.target = [float(x), float(y), float(z), float(rot), float(tilt)]
        self.stage_until = time.monotonic() + (2 + dist / 5) * self.scale   # ~5 mm/s plus settling

    def StgStop(self):
        self.log.append("StgStop")
        if self.target:
            self.pos, self.target = self.target, None

    def SetViewField(self, mm):
        self.log.append(f"SetViewField {mm:.6f}")
        self.view_field = max(0.00012, min(60.0, float(mm)))

    def GetViewField(self):
        return self.view_field

    def DtSelect(self, channel, detector):
        self.log.append(f"DtSelect {channel} {detector}")
        self.channel[channel] = detector

    def DtEnable(self, channel, enable, bpp=8):
        self.log.append(f"DtEnable {channel} {enable} {bpp}")

    def AutoWD(self, channel):
        self.log.append("AutoWD")
        time.sleep(min(0.2, 6 * self.scale))

    def ScSetSpeed(self, speed):
        self.speed = int(speed)

    def ScScanXY(self, frame_id, w, h, x0, y0, x1, y1, single):
        if not self.HVGetBeam():
            raise SharkSemError("beam is off")
        self.log.append(f"ScScanXY {w}x{h} speed {self.speed}")
        self.scanning = True
        time.sleep(min(0.5, w * h * DWELL_US[self.speed] * 1e-6 * self.scale))
        self.scanning = False
        self._frame = (w, h)

    def ScStopScan(self):
        self.log.append("ScStopScan")
        self.scanning = False

    def FetchImage(self, channel, nbytes):
        rnd = random.Random(int(self.pos[0] * 1000 + self.pos[1]) + self.channel.get(channel, 0))
        return rnd.randbytes(nbytes)


class SimBackend(real.TescanBackend):
    def __init__(self, cfg, scale):
        super().__init__(cfg)
        self.scale, self.log = scale, []

    def open(self):
        self.sem = FakeSem(self.scale, self.log)
        self.sem.Connect(self.cfg["host"], self.cfg.get("port", 8300))


class SimTescanSEM(real.TescanSEM):
    def setup(self) -> None:
        super().setup()
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        self.cfg = {"host": "sim", "port": 8300, "reference_width_mm": 120.0, "pump_timeout_s": 900}

    def time_scale(self) -> float:
        return self.scale

    def make_backend(self):
        return SimBackend(self.cfg, self.scale)
