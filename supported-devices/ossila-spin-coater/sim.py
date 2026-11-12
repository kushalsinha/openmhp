"""Simulated twin: an Ossila Spin Coater on the placeholder serial protocol, with a chuck that spins.

The chuck follows each step's speed at the step's acceleration, holds it for the duration and moves on; a
run ends after the last step. Opening the lid (`lid = False` on the fake port) stops the run as the unit's
interlock does. Simulated time runs faster than the clock: OPENMHP_SIM_TIME_SCALE is the number of real
seconds per simulated second (default 0.01).
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
        self.lid = True
        self.programs = {n: [] for n in range(1, 11)}
        self.programs[1] = [(1000, 500, 10), (4000, 1000, 30), (0, 1000, 3)]
        self.program, self.running, self.step, self.step_t = 1, False, 0, 0.0
        self.rpm, self.sp = 0.0, 0.0
        self.t = time.time()
        self._reply = b""
        self.sent = []

    def _tick(self):
        now = time.time()
        dt = (now - self.t) / self.scale
        self.t = now
        if self.running and not self.lid:
            self.running, self.sp, self.step = False, 0.0, 0            # the lid interlock
        if self.running:
            steps = self.programs[self.program]
            speed, acc, dur = steps[self.step - 1]
            self.sp = float(speed)
            self.step_t += dt
            if self.step_t >= dur:
                self.step += 1; self.step_t = 0.0
                if self.step > len(steps):
                    self.running, self.step, self.sp = False, 0, 0.0
        acc = 1000.0
        if self.running:
            acc = float(self.programs[self.program][self.step - 1][1])
        step = acc * dt
        self.rpm += max(-step, min(step, self.sp - self.rpm))
        if abs(self.rpm - self.sp) < 1:
            self.rpm = self.sp

    def _time_left(self):
        if not self.running:
            return 0.0
        return max(0.0, self.programs[self.program][self.step - 1][2] - self.step_t)

    def write(self, b):
        cmd = b.decode().strip()
        self.sent.append(cmd)
        self._tick()
        parts = cmd.split()
        if cmd == "?RPM": self._reply = f"RPM {self.rpm:.0f}\n".encode()
        elif cmd == "?LID": self._reply = b"LID 1\n" if self.lid else b"LID 0\n"
        elif cmd == "?RUN": self._reply = b"RUN 1\n" if self.running else b"RUN 0\n"
        elif cmd == "?PRG": self._reply = f"PRG {self.program}\n".encode()
        elif cmd == "?STEP": self._reply = f"STEP {self.step}\n".encode()
        elif cmd == "?TIME": self._reply = f"TIME {self._time_left():.0f}\n".encode()
        elif parts[0] == "PRG" and len(parts) == 2:
            self.program = max(1, min(10, int(parts[1]))); self._reply = b"OK\n"
        elif parts[0] == "STEP" and len(parts) == 6:
            slot, n, speed, acc, dur = (int(p) for p in parts[1:])
            prog = self.programs[slot]
            if n == 1: prog.clear()
            prog.append((speed, acc, dur)); self._reply = b"OK\n"
        elif cmd == "RUN":
            if not self.lid: self._reply = b"ERR LID\n"
            elif not self.programs[self.program]: self._reply = b"ERR EMPTY\n"
            else: self.running, self.step, self.step_t = True, 1, 0.0; self._reply = b"OK\n"
        elif cmd == "STOP": self.running, self.sp, self.step = False, 0.0, 0; self._reply = b"OK\n"
        else: self._reply = b"ERR\n"                                   # the real reply to an unknown command is unverified

    def readline(self):
        return self._reply


class Sim(Device):
    link = _FakePort()
