"""Simulated twin: a Laurell 650 controller on the placeholder serial protocol, with a chuck that spins.

The chuck follows each step's speed at the step's acceleration, holds it for the step's duration and moves
on; a run ends after the last step. Opening the lid (`lid = False` on the fake port) or losing vacuum
(`vacuum_inhg` below 15) stops the run as the controller's interlocks do. Simulated time runs faster than
the clock: OPENMHP_SIM_TIME_SCALE is the number of real seconds per simulated second (default 0.01).
"""
from __future__ import annotations

import os
import time

try:
    from .driver import Device
except ImportError:                                          # loaded by path (load_driver): driver.py sits beside this file
    import importlib.util as _ilu
    import pathlib as _pl
    import sys as _sys
    _spec = _ilu.spec_from_file_location(__name__ + "_real", _pl.Path(__file__).with_name("driver.py"))
    _real = _ilu.module_from_spec(_spec)
    _sys.modules[_spec.name] = _real
    _spec.loader.exec_module(_real)
    Device = _real.Device


class _FakePort:
    is_open = True

    def __init__(self):
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        self.lid, self.vacuum_valve, self.vacuum_inhg = True, False, 0.0
        self.programs = {n: [] for n in range(1, 21)}
        self.programs[1] = [(500, 500, 5), (3000, 1500, 30), (0, 1500, 5)]
        self.program, self.running, self.step, self.step_t = 1, False, 0, 0.0
        self.rpm, self.sp = 0.0, 0.0
        self.t = time.time()
        self._reply = b""
        self.sent = []

    def _tick(self):
        now = time.time()
        dt = (now - self.t) / self.scale
        self.t = now
        target_vac = 22.0 if self.vacuum_valve else 0.0
        self.vacuum_inhg += max(-10 * dt, min(10 * dt, target_vac - self.vacuum_inhg))
        if self.running and (not self.lid or self.vacuum_inhg < 15):
            self.running, self.sp = False, 0.0                        # the controller's interlocks halt the run
        if self.running:
            steps = self.programs[self.program]
            if self.step > len(steps):
                self.running, self.sp = False, 0.0
            else:
                speed, acc, dur = steps[self.step - 1]
                self.sp = float(speed)
                self.step_t += dt
                if self.step_t >= dur:
                    self.step += 1; self.step_t = 0.0
                    if self.step > len(steps):
                        self.running, self.step, self.sp = False, 0, 0.0
        acc = 1500.0 if not self.running else float(self.programs[self.program][min(self.step, len(self.programs[self.program])) - 1][1])
        step = acc * dt
        self.rpm += max(-step, min(step, self.sp - self.rpm))
        if abs(self.rpm - self.sp) < 1:
            self.rpm = self.sp

    def write(self, b):
        cmd = b.decode().strip()
        self.sent.append(cmd)
        self._tick()
        parts = cmd.split()
        if cmd == "?RPM": self._reply = f"RPM {self.rpm:.0f}\r".encode()
        elif cmd == "?SP": self._reply = f"SP {self.sp:.0f}\r".encode()
        elif cmd == "?LID": self._reply = b"LID 1\r" if self.lid else b"LID 0\r"
        elif cmd == "?VOK": self._reply = b"VOK 1\r" if self.vacuum_inhg >= 15 else b"VOK 0\r"
        elif cmd == "?VAC": self._reply = f"VAC {self.vacuum_inhg:.1f}\r".encode()
        elif cmd == "?RUN": self._reply = b"RUN 1\r" if self.running else b"RUN 0\r"
        elif cmd == "?PRG": self._reply = f"PRG {self.program}\r".encode()
        elif cmd == "?STEP": self._reply = f"STEP {self.step}\r".encode()
        elif parts[0] == "PRG" and len(parts) == 2:
            self.program = max(1, min(20, int(parts[1]))); self._reply = b"OK\r"
        elif parts[0] == "STEP" and len(parts) == 6:
            slot, n, speed, acc, dur = (int(p) for p in parts[1:])
            prog = self.programs[slot]
            if n == 1: prog.clear()
            prog.append((speed, acc, dur)); self._reply = b"OK\r"
        elif cmd == "RUN":
            if not self.lid: self._reply = b"ERR LID OPEN\r"
            elif self.vacuum_inhg < 15: self._reply = b"ERR NEED VACUUM\r"
            elif not self.programs[self.program]: self._reply = b"ERR EMPTY\r"
            else: self.running, self.step, self.step_t = True, 1, 0.0; self._reply = b"OK\r"
        elif cmd == "STOP": self.running, self.sp, self.step = False, 0.0, 0; self._reply = b"OK\r"
        elif cmd == "VAC 1": self.vacuum_valve = True; self._reply = b"OK\r"
        elif cmd == "VAC 0":
            if self.rpm > 0: self._reply = b"ERR SPINNING\r"
            else: self.vacuum_valve = False; self._reply = b"OK\r"
        else: self._reply = b"ERR\r"                                   # the real reply to an unknown command is unverified

    def readline(self):
        return self._reply


class Sim(Device):
    link = _FakePort()
