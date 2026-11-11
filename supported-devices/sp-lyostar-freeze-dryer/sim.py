"""Simulated twin: a fake lyophiliser controller answering the template register map.

Simulated time runs faster than the clock: OPENMHP_SIM_TIME_SCALE real seconds per simulated
second (default 0.01, so a 6-hour simulated cycle takes about 4 minutes). Setting the run coil
starts a short recipe (freeze, primary, secondary drying) that moves the phase code, pulls the
chamber down and lets the Pirani converge; the hold coil freezes it; the defrost coil warms the
condenser and clears itself. An address the map does not have raises DeviceFault, the way a
real controller answers Modbus exception 02.
"""
import os
import time

from openmhp.driver import DeviceFault
from openmhp.drivers.modbus import ModbusDriver, decode, encode

RUN, HOLD, DEFROST, HEATER = 0, 1, 2, 3
# recipe steps: (phase_code, shelf setpoint degC, chamber setpoint mbar, duration in simulated s)
RECIPE = [(2, -45.0, 1000.0, 3600), (4, -20.0, 0.1, 10800), (5, 25.0, 0.05, 7200), (7, 25.0, 1000.0, 600)]


class _Plc:
    is_open = True

    def __init__(self):
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        self.t = time.time()
        self.log = []                                       # every write: (kind, addr, values)
        self.coils = {RUN: 0, HOLD: 0, DEFROST: 0, HEATER: 1}
        self.discrete = {0: 1, 1: 1, 2: 1}                  # door closed, vacuum ok, idle
        self.holding = {100: 200, 110: 0}                   # shelf setpoint x10, recipe number
        self._set_f(101, 0.1)                               # chamber pressure setpoint
        self.shelf, self.cond, self.pressure, self.pirani = 20.0, -85.0, 1000.0, 1000.0
        self.product = [20.0, 20.0, 20.0]
        self.phase, self.step, self.step_t = 0, -1, 0.0

    def _set_f(self, addr, value):
        w = encode(value, "float32")
        self.holding[addr], self.holding[addr + 1] = w[0], w[1]

    def _tick(self):
        now = time.time()
        dt = (now - self.t) / self.scale
        self.t = now
        running, held = self.coils[RUN], self.coils[HOLD]
        if running and self.step < 0:                       # the run coil was just set
            self.step, self.step_t, self.phase = 0, 0.0, RECIPE[0][0]
        if not running and self.step >= 0:                  # stopped
            self.step, self.phase, self.coils[HOLD] = -1, 0, 0
        if running and not held:
            self.step_t += dt
            if self.step_t >= RECIPE[self.step][3]:
                self.step += 1
                self.step_t = 0.0
                if self.step >= len(RECIPE):                # cycle complete: controller clears the coil
                    self.coils[RUN], self.step, self.phase = 0, -1, 0
                else:
                    self.phase = RECIPE[self.step][0]
        if running and held:
            self.phase = 6
        if self.step >= 0:
            _, shelf_tgt, p_tgt, _ = RECIPE[self.step]
            self.holding[100] = int(shelf_tgt * 10) & 0xFFFF
        else:
            shelf_tgt = decode([self.holding[100]], "int16") / 10 if self.coils[HEATER] else 20.0
            p_tgt = 1000.0
        self.shelf += max(-0.02 * dt, min(0.02 * dt, shelf_tgt - self.shelf))            # ~1 degC/min
        rate = 0.02 * dt
        self.pressure += max(-rate * self.pressure, min(rate * self.pressure, p_tgt - self.pressure))
        self.pirani = self.pressure * (1.6 if self.phase == 4 and self.step_t < RECIPE[1][3] * 0.8 else 1.0)
        for i in range(3):
            tgt = self.shelf - (6.0 if self.phase == 4 else 0.0)
            self.product[i] += max(-0.03 * dt, min(0.03 * dt, tgt - self.product[i]))
        if self.coils[DEFROST]:
            self.phase = 8
            self.cond += min(0.05 * dt, 20.0 - self.cond)
            if self.cond >= 19.0:
                self.coils[DEFROST] = 0
        else:
            self.cond += max(-0.05 * dt, -85.0 - self.cond)
        self.discrete[1] = 1 if (self.phase not in (4, 5) or self.pressure < 1.0) else 0
        self.discrete[2] = 1 if (not self.coils[RUN] and not self.coils[DEFROST]) else 0
        if not self.coils[DEFROST] and self.step < 0:
            self.phase = 0

    def _inputs(self):
        pf, qf = encode(self.pressure, "float32"), encode(self.pirani, "float32")
        vals = {0: self.shelf, 1: self.cond, 2: self.product[0], 3: self.product[1], 4: self.product[2]}
        out = {a: int(round(v * 10)) & 0xFFFF for a, v in vals.items()}
        out[5] = self.phase
        out[10], out[11], out[12], out[13] = pf[0], pf[1], qf[0], qf[1]
        return out

    def read(self, kind, addr, count):
        self._tick()
        table = {"coil": self.coils, "discrete": self.discrete, "holding": self.holding, "input": self._inputs()}[kind]
        out = []
        for i in range(count):
            if addr + i not in table:
                raise DeviceFault(f"Modbus exception 02: illegal data address ({kind} {addr + i})")
            out.append(table[addr + i])
        return out

    def write(self, kind, addr, values):
        self._tick()
        self.log.append((kind, addr, list(values)))
        table = {"coil": self.coils, "holding": self.holding}.get(kind)
        if table is None or addr not in table:
            raise DeviceFault(f"Modbus exception 02: illegal data address ({kind} {addr})")
        for i, v in enumerate(values):
            table[addr + i] = v
        self._tick()


class Sim(ModbusDriver):
    link = _Plc()
