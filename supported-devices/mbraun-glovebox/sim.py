"""Simulated twin: an MBRAUN glovebox PLC on the placeholder Modbus map, with box gas and antechamber physics.

O2 and H2O fall toward 0.3 ppm with a ~10 simulated-minute time constant while the blower runs and rise
during purge, regeneration or with the inner door open; box pressure breathes +-1 mbar around its
setpoint. An antechamber cycle evacuates to 1 mbar in ~90 s and refills in ~60 s, `purges` times, then
reports at_box_pressure and idle. Set `discrete[1]` / `discrete[2]` on the fake PLC to open the doors.
Simulated time runs faster than the clock: OPENMHP_SIM_TIME_SCALE is the number of real seconds per
simulated second (default 0.01).
"""
from __future__ import annotations

import math
import os
import struct
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


class _Plc:
    is_open = True

    def __init__(self):
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        self.holding = {r: 0 for r in range(0, 24)}
        self.discrete = {0: 1, 1: 1, 2: 1, 3: 0, 4: 0}
        self.coils = {c: 0 for c in range(0, 8)}
        self.o2, self.h2o, self.pressure, self.ante_p = 0.4, 0.6, 2.0, 1000.0
        self.setpoint, self.purges = 2.0, 3
        self._set_f(20, self.setpoint); self.holding[22] = self.purges
        self.ante_state, self.ante_phase_t, self.purges_left = 0, 0.0, 0
        self.log: list[tuple] = []
        self.t = time.time()
        self._sync()

    def _set_f(self, reg, value):
        self.holding[reg], self.holding[reg + 1] = struct.unpack(">HH", struct.pack(">f", float(value)))

    def _get_f(self, reg):
        return struct.unpack(">f", struct.pack(">HH", self.holding[reg], self.holding[reg + 1]))[0]

    def _sync(self):
        self._set_f(0, self.o2); self._set_f(2, self.h2o); self._set_f(4, self.pressure); self._set_f(6, self.ante_p)
        self.holding[10] = self.ante_state
        self.holding[11] = 2 if self.discrete[4] else (1 if self.coils[2] else 0)
        self.discrete[3] = 1 if self.ante_state in (1, 2) else 0

    def _tick(self):
        now = time.time()
        dt = (now - self.t) / self.scale
        self.t = now
        self.setpoint = self._get_f(20)
        blower = bool(self.discrete[0])
        inner_open, outer_open = not self.discrete[1], not self.discrete[2]
        purge, regen = bool(self.coils[2]), bool(self.discrete[4])
        floor = 0.3 if blower and not regen else 5.0
        rate = 1 - math.exp(-dt / 600.0)
        self.o2 += (floor - self.o2) * rate
        self.h2o += (floor * 1.5 - self.h2o) * rate
        if inner_open and self.ante_state != 3:
            self.o2 += 0.5 * dt / 60; self.h2o += 0.8 * dt / 60
        if purge:
            self.o2 += 0.2 * dt / 60
        self.pressure += (self.setpoint - self.pressure) * (1 - math.exp(-dt / 20.0)) + 0.8 * math.sin(now / self.scale / 7.0) * dt / 10
        if self.ante_state == 1:                                 # evacuating: 1000 -> 1 mbar in ~90 s
            self.ante_phase_t += dt
            self.ante_p = max(1.0, 1000.0 * math.exp(-self.ante_phase_t / 13.0))
            if self.ante_phase_t >= 90:
                self.ante_state, self.ante_phase_t = 2, 0.0
        elif self.ante_state == 2:                               # refilling with box gas: ~60 s
            self.ante_phase_t += dt
            self.ante_p = min(1000.0 + self.pressure, 1.0 + (999.0 + self.pressure) * self.ante_phase_t / 60.0)
            if self.ante_phase_t >= 60:
                self.purges_left -= 1
                self.ante_state, self.ante_phase_t = (1, 0.0) if self.purges_left > 0 else (3, 0.0)
        elif self.ante_state == 3:                               # at box pressure, then idle
            self.ante_phase_t += dt
            if self.ante_phase_t >= 5:
                self.ante_state = 0
        else:
            self.ante_p = 1000.0 + self.pressure if not outer_open else 1013.0
        self._sync()

    def read(self, kind, addr, count):
        self._tick()
        table = {"discrete": self.discrete, "holding": self.holding, "coil": self.coils, "input": {}}[kind]
        out = []
        for i in range(count):
            if addr + i not in table:
                raise DeviceFault(f"Modbus exception 02: illegal data address ({kind} {addr + i})")
            out.append(table[addr + i])
        return out

    def write(self, kind, addr, values):
        self._tick()
        self.log.append((kind, addr, list(values)))
        if kind == "holding" and addr in (20, 22):
            for i, v in enumerate(values):
                self.holding[addr + i] = v
            return
        if kind != "coil" or addr not in self.coils:
            raise DeviceFault(f"Modbus exception 02: illegal data address ({kind} {addr})")
        v = 1 if values[0] else 0
        self.coils[addr] = v
        if addr == 0 and v and self.ante_state == 0 and self.discrete[1] and self.discrete[2]:
            self.purges_left = max(1, int(self.holding[22]))
            self.ante_state, self.ante_phase_t = 1, 0.0
            self.coils[0] = 0                                    # the PLC resets the start command
        if addr == 1 and v and self.ante_state in (1, 2):
            self.ante_state, self.ante_phase_t, self.purges_left = 2, 0.0, 1
            self.coils[1] = 0
        if addr == 3:
            self.discrete[4] = v
        if addr in (4, 5):
            self.coils[addr] = 0                                 # a release is momentary; the door bit is a person's act
        self._sync()


class Sim(Device):
    link = _Plc()
