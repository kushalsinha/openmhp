"""Simulated twin: a fake MB2 answering the template register map with 32-bit floats.

Simulated time runs faster than the clock: OPENMHP_SIM_TIME_SCALE real seconds per simulated
second (default 0.01). Temperature and humidity ramp toward their setpoints; an open door drops
humidity toward room air and raises the collective alarm. An address the map does not have
raises DeviceFault, the way a real controller answers Modbus exception 02.
"""
import os
import time

from openmhp.driver import DeviceFault
from openmhp.drivers.modbus import ModbusDriver, decode, encode

T_SP, H_SP, T_PV, H_PV = 4270, 4276, 4096, 4106


class _Plc:
    is_open = True

    def __init__(self):
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        self.t = time.time()
        self.log = []                                       # every write: (kind, addr, values)
        self.discrete = {0: 1, 1: 0, 2: 0}                  # door closed, no alarm, light off
        self.holding = {}
        self._set(T_SP, 25.0); self._set(H_SP, 60.0); self._set(T_PV, 25.0); self._set(H_PV, 60.0)

    def _set(self, addr, value):
        w = encode(value, "float32")
        self.holding[addr], self.holding[addr + 1] = w[0], w[1]

    def _get(self, addr):
        return decode([self.holding[addr], self.holding[addr + 1]], "float32")

    def _tick(self):
        now = time.time()
        dt = (now - self.t) / self.scale
        self.t = now
        door_open = not self.discrete[0]
        t_tgt = 22.0 if door_open else self._get(T_SP)
        h_tgt = 45.0 if door_open else self._get(H_SP)
        t, h = self._get(T_PV), self._get(H_PV)
        t += max(-0.005 * dt, min(0.005 * dt, t_tgt - t))         # about 0.3 degC/min
        h += max(-0.02 * dt, min(0.02 * dt, h_tgt - h))           # about 1.2 % rH/min
        self._set(T_PV, t); self._set(H_PV, h)
        self.discrete[1] = 1 if door_open or abs(t - self._get(T_SP)) > 2 or abs(h - self._get(H_SP)) > 5 else 0

    def read(self, kind, addr, count):
        self._tick()
        table = {"discrete": self.discrete, "holding": self.holding, "coil": {}, "input": {}}[kind]
        out = []
        for i in range(count):
            if addr + i not in table:
                raise DeviceFault(f"Modbus exception 02: illegal data address ({kind} {addr + i})")
            out.append(table[addr + i])
        return out

    def write(self, kind, addr, values):
        self._tick()
        self.log.append((kind, addr, list(values)))
        if kind != "holding" or addr not in self.holding:
            raise DeviceFault(f"Modbus exception 02: illegal data address ({kind} {addr})")
        for i, v in enumerate(values):
            self.holding[addr + i] = v


class Sim(ModbusDriver):
    link = _Plc()
