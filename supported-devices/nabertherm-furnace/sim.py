"""Simulated twin: a Nabertherm series 400 controller's Modbus TCP register map with a furnace that heats.

The chamber follows the program setpoint with a first-order lag (time constant ~3 simulated minutes)
limited to ~25 degC/min heating and ~8 degC/min free cooling. A stored program (1-50) is a canned
ramp/dwell/cool profile; program 51 is whatever was transferred into registers 200-404. Simulated time
runs faster than the clock: OPENMHP_SIM_TIME_SCALE is the number of real seconds per simulated second
(default 0.01).
"""
from __future__ import annotations

import math
import os
import time

from openmhp.driver import DeviceFault

try:
    from .driver import Device                               # the package's own driver, when imported as a package
except ImportError:                                          # loaded by path (load_driver): find driver.py beside this file
    import importlib.util as _ilu
    import pathlib as _pl
    import sys as _sys
    _spec = _ilu.spec_from_file_location(__name__ + "_real", _pl.Path(__file__).with_name("driver.py"))
    _real = _ilu.module_from_spec(_spec)
    _sys.modules[_spec.name] = _real
    _spec.loader.exec_module(_real)
    Device = _real.Device

STORED = {1: [(300, 10, 2), (300, 60, 0), (20, 0, 0)],                 # (target, time-or-rate, flags) as the controller stores them
          2: [(650, 300, 2), (650, 60, 0), (300, 0, 0)],
          3: [(1100, 600, 2), (1100, 120, 0), (20, 0, 0)]}


class _Plc:
    is_open = True

    def __init__(self):
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        self.holding = {r: 0 for r in list(range(100, 152)) + list(range(200, 410))}
        self.holding.update({100: 250, 101: 250, 111: 250, 125: 0, 136: 4, 137: 13000, 151: 0})
        serial = "N22080075L1".ljust(20, "\x00")                   # ASCII, two characters per register (138-147)
        for i in range(10):
            self.holding[138 + i] = (ord(serial[2 * i]) << 8) | ord(serial[2 * i + 1])
        self.log: list[tuple] = []
        self.t = time.time()
        self.pv = 25.0
        self.program: list[tuple] = []
        self.seg = 0
        self.seg_elapsed = 0.0
        self.seg_start_temp = 25.0

    def _tenths(self, reg, value):
        self.holding[reg] = int(round(value * 10)) & 0xFFFF

    def _load(self, number):
        if number == 51:
            n = self.holding[402]
            self.program = [(self.holding[200 + i], self.holding[240 + i], self.holding[360 + i]) for i in range(n)]
        else:
            self.program = list(STORED.get(number, STORED[1]))
        self.seg, self.seg_elapsed, self.seg_start_temp = 0, 0.0, self.pv

    def _program_setpoint(self, dt):
        """Setpoint of the active segment: a rate ramp, a timed ramp or a dwell, in degC; advances segments."""
        if self.seg >= len(self.program):
            self.holding[125] = 4; self.holding[127] = 0
            return self.pv
        target, t, flags = self.program[self.seg]
        self.holding[127] = self.seg + 1
        self.seg_elapsed += dt
        if flags & 0b10 and t > 0:                               # rate in degC/h
            span = abs(target - self.seg_start_temp)
            duration = span / (t / 60.0) * 60.0 if t else 0.0    # seconds
        else:
            duration = t * 60.0                                  # minutes
        if duration <= 0 or self.seg_elapsed >= duration:
            sp = float(target)
            if duration <= 0 and abs(self.pv - target) > 2:      # "as fast as possible": wait for the furnace
                return sp
            self.seg += 1; self.seg_elapsed = 0.0; self.seg_start_temp = self.pv
            return sp
        frac = self.seg_elapsed / duration
        return self.seg_start_temp + (target - self.seg_start_temp) * frac if self.seg_start_temp != target else float(target)

    def _tick(self):
        now = time.time()
        dt = (now - self.t) / self.scale
        self.t = now
        status = self.holding[125]
        if status == 2:
            sp = self._program_setpoint(dt)
            remaining = sum((t if not (f & 0b10) else 0) for _, t, f in self.program[self.seg + 1:])
            self.holding[128], self.holding[129] = int(remaining) & 0xFFFF, (int(remaining) >> 16) & 0xFFFF
        elif status == 7:
            sp = float(self.holding[406])
        elif status == 3:
            sp = self.holding[111] / 10.0
        else:
            sp = 25.0
        self._tenths(111, sp)
        tau = 180.0
        step = (sp - self.pv) * (1 - math.exp(-dt / tau))
        step = max(-8.0 / 60 * dt, min(25.0 / 60 * dt, step))
        self.pv += step
        power = 0.0 if status in (0, 4) else max(0.0, min(100.0, (sp - self.pv) * 5 + (sp - 25) / 13))
        self._tenths(100, self.pv); self._tenths(101, self.pv - 3); self._tenths(119, power)

    def read(self, kind, addr, count):
        self._tick()
        if kind != "holding":
            raise DeviceFault(f"Modbus exception 02: illegal data address ({kind} {addr})")
        out = []
        for i in range(count):
            if addr + i not in self.holding:
                raise DeviceFault(f"Modbus exception 02: illegal data address (holding {addr + i})")
            out.append(self.holding[addr + i])
        return out

    def write(self, kind, addr, values):
        self._tick()
        self.log.append((kind, addr, list(values)))
        if kind != "holding" or addr not in self.holding or addr < 148:
            raise DeviceFault(f"Modbus exception 02: illegal data address ({kind} {addr})")
        for i, v in enumerate(values):
            self.holding[addr + i] = v & 0xFFFF
        if addr == 149 and values[0]:
            self.holding[126] = values[0]
        if addr == 403 and values[0] == 1:                       # release: the controller takes the program
            self.holding[126] = 51; self.holding[404] = 1
        if addr == 148:
            cmd = values[0]
            if cmd == 1 and self.holding[125] in (0, 4):
                self._load(self.holding[126] or 1); self.holding[125] = 2
            elif cmd == 2:
                self.holding[125] = 0; self.holding[127] = 0; self.holding[404] = 0
            elif cmd == 3 and self.holding[125] == 2:
                self.holding[125] = 3
        if addr == 405:
            self.holding[125] = 7 if values[0] == 1 else (0 if self.holding[125] == 7 else self.holding[125])
        if addr == 150 and values[0]:
            jump = values[0] - 0x10000 if values[0] >= 0x8000 else values[0]
            self.seg = max(0, min(len(self.program), self.seg + jump)); self.seg_elapsed = 0.0; self.seg_start_temp = self.pv


class Sim(Device):
    link = _Plc()
