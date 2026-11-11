"""Simulated twin of an Alicat MC-10SLPM-D: the polling protocol with a first-order valve response.

Mass flow follows the setpoint with a 0.3 s simulated time constant, limited to what 14.7 psia of
supply can deliver (12 SLPM); temperature sits at 25 degC. Time runs at OPENMHP_SIM_TIME_SCALE real
seconds per simulated second (default 0.01). Unknown commands answer `?`, as the firmware does.
"""
from __future__ import annotations

import importlib.util
import math
import os
import pathlib
import sys
import time

_spec = importlib.util.spec_from_file_location(__name__ + "_real", pathlib.Path(__file__).with_name("driver.py"))
real = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = real
_spec.loader.exec_module(real)


class _FakePort:
    is_open = True

    def __init__(self):
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        self.t = time.time()
        self.unit, self.gas = "A", "N2"
        self.pressure, self.temperature = 14.70, 25.0
        self.setpoint = self.flow = 0.0
        self.hold = False
        self.tare_offset = 0.0
        self.sent: list[str] = []
        self._reply = b""

    def _tick(self):
        now = time.time()
        dt = (now - self.t) / self.scale
        self.t = now
        target = 0.0 if self.hold else min(self.setpoint, 12.0)
        self.flow += (target - self.flow) * (1 - math.exp(-dt / 0.3))

    def _frame(self) -> str:
        self._tick()
        f = self.flow + self.tare_offset
        flags = []
        if self.hold:
            flags.append("HLD")
        if self.setpoint > 10.0 * 1.28:
            flags.append("MOV")
        return (f"{self.unit} {self.pressure:+07.2f} {self.temperature:+07.2f} {f:+07.3f} {f:+07.3f} "
                f"{self.setpoint:+07.3f} {self.gas:>6}" + ("".join(" " + x for x in flags)))

    def write(self, b: bytes):
        cmd = b.decode(errors="replace").strip()
        self.sent.append(cmd)
        if not cmd or cmd[0].upper() != self.unit:
            self._reply = b""                                   # another unit id: silence
            return
        body = cmd[1:].strip()
        up = body.upper()
        if body == "":
            reply = self._frame()
        elif up.startswith("S") and up[1:].strip().replace(".", "", 1).replace("-", "", 1).isdigit():
            self.setpoint = max(0.0, min(float(body[1:]), 10.0 * 1.28))
            reply = self._frame()
        elif up == "HC":
            self.hold = True
            reply = self._frame()
        elif up == "HP":
            self.hold = True
            reply = self._frame()
        elif up == "C":
            self.hold = False
            reply = self._frame()
        elif up == "V":
            self._tick()
            self.tare_offset = -self.flow
            reply = self._frame()
        elif up == "VE":
            reply = f"{self.unit}   10v20.0-R24 Jan  9 2025,15:04:07"
        else:
            reply = "?"
        self._reply = (reply + "\r").encode()

    def readline(self) -> bytes:
        r, self._reply = self._reply, b""
        return r


class Sim(real.Device):
    link = _FakePort()
