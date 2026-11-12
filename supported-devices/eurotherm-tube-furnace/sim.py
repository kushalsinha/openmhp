"""Simulated twin: a Eurotherm 2416's Modbus holding registers in front of a tube furnace that heats.

The process value follows the working setpoint with a first-order lag (time constant ~2 simulated
minutes), limited to ~30 degC/min heating and ~6 degC/min free cooling toward 25 degC. Program slots
1-4 live at 8328 + 136 x (n - 1) exactly as the handbook lays them out; slot 1 ships with a ramp to
500 degC, a 30 min dwell and a ramp down. Simulated time runs faster than the clock:
OPENMHP_SIM_TIME_SCALE is the number of real seconds per simulated second (default 0.01).
"""
from __future__ import annotations

import math
import os
import time

from openmhp.driver import DeviceFault

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

BASE, STRIDE, SEG = 8328, 136, 8


class _Plc:
    is_open = True

    def __init__(self):
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        regs = [1, 2, 3, 5, 22, 23, 29, 36, 56, 58, 59, 75, 160, 161, 163, 273]
        self.holding = {r: 0 for r in regs}
        self.holding.update({1: 25, 2: 25, 5: 25, 22: 1, 23: 1, 163: 25})
        for r in range(BASE, BASE + 4 * STRIDE):
            self.holding[r] = 0
        b = BASE                                             # slot 1: ramp 10/min to 500, dwell 30 min, ramp down, end
        self.holding[b + 2] = 1; self.holding[b + 3] = 1; self.holding[b + 4] = 1
        for i, (typ, tgt, val) in enumerate([(1, 500, 10), (3, 500, 30), (1, 30, 10), (0, 0, 0)]):
            o = b + SEG * (i + 1)
            self.holding[o], self.holding[o + 1], self.holding[o + 2] = typ, tgt, val
        self.log: list[tuple] = []
        self.t = time.time()
        self.pv, self.psp = 25.0, 25.0
        self.program: list[tuple] = []
        self.seg, self.seg_elapsed = 0, 0.0

    def _signed(self, v):
        return v - 0x10000 if v >= 0x8000 else v

    def _load(self, n):
        b = BASE + STRIDE * (max(1, n) - 1)
        self.program = []
        for i in range(16):
            o = b + SEG * (i + 1)
            typ = self.holding[o]
            self.program.append((typ, self._signed(self.holding[o + 1]), self.holding[o + 2]))
            if typ == 0:
                break
        self.seg, self.seg_elapsed, self.psp = 0, 0.0, self.pv

    def _step_program(self, dt):
        if self.seg >= len(self.program):
            self.holding[23] = 16; self.holding[29] = 0; return
        typ, target, value = self.program[self.seg]
        self.holding[56], self.holding[29], self.holding[160], self.holding[161] = self.seg + 1, typ, target & 0xFFFF, value if typ == 1 else 0
        self.seg_elapsed += dt
        if typ == 0:                                         # end: dwell at the last setpoint
            self.holding[23] = 16; self.holding[36] = 0; self.holding[58] = 0
            self.seg += 1
            return
        if typ == 1:                                         # ramp at value degC/min
            step = value / 60.0 * dt
            self.psp += max(-step, min(step, target - self.psp))
            left = abs(target - self.psp) / (value / 60.0) if value else 0
            self.holding[36] = int(left / 60)
            if abs(self.psp - target) < 1e-6:
                self.seg += 1; self.seg_elapsed = 0.0
        elif typ == 3:                                       # dwell value minutes
            self.psp = float(target)
            self.holding[36] = max(0, int(value - self.seg_elapsed / 60))
            if self.seg_elapsed >= value * 60:
                self.seg += 1; self.seg_elapsed = 0.0
        else:
            self.seg += 1
        self.holding[58] = sum(v for t_, _, v in self.program[self.seg:] if t_ == 3) + self.holding[36]

    def _tick(self):
        now = time.time()
        dt = (now - self.t) / self.scale
        self.t = now
        status = self.holding[23]
        if status in (2, 8):
            self._step_program(dt)
            wsp = self.psp
        elif status == 4:
            wsp = self.psp
        else:
            wsp = float(self._signed(self.holding[2]))
        self.holding[5] = int(round(wsp)) & 0xFFFF; self.holding[163] = int(round(self.psp)) & 0xFFFF
        if self.holding[273] == 1:
            power = float(self._signed(self.holding[3]))
        else:
            power = max(0.0, min(100.0, (wsp - self.pv) * 4 + (wsp - 25) / 12))
            self.holding[3] = int(round(power)) & 0xFFFF
        target = self.pv + (power / 100.0) * 1300 * (1 - math.exp(-dt / 120.0)) if power > 0 else self.pv
        heat = min(target - self.pv, 30.0 / 60 * dt, max(0.0, wsp - self.pv) if self.holding[273] == 0 else 1e9)
        cool = (25.0 - self.pv) * (1 - math.exp(-dt / 300.0))
        self.pv += heat + cool
        self.holding[1] = int(round(self.pv)) & 0xFFFF
        self.holding[75] = 1 if self.pv > 1250 else 0

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
        if kind != "holding" or addr not in self.holding:
            raise DeviceFault(f"Modbus exception 02: illegal data address ({kind} {addr})")
        if addr >= BASE and self.holding[23] in (2, 8):
            raise DeviceFault("Modbus exception 03: illegal data value (program segments cannot be written while the program runs)")
        v = values[0] & 0xFFFF
        if addr == 23:
            if v == 2 and self.holding[23] in (1, 16):
                self._load(self.holding[22])
            elif v == 1:
                self.program, self.seg = [], 0; self.holding[56] = 0; self.holding[29] = 0
            self.holding[23] = v
        else:
            self.holding[addr] = v


class Sim(Device):
    link = _Plc()
