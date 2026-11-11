"""Simulated twin: a fake PLC answering the template register map with a small thermal/gas model.

Simulated time runs faster than the clock: OPENMHP_SIM_TIME_SCALE real seconds per simulated
second (default 0.01, so a 10-minute CO2 recovery takes 6 s). Reading or writing an address the
map does not have raises DeviceFault, the way a real controller answers Modbus exception 02.
"""
import os
import time

from openmhp.driver import DeviceFault
from openmhp.drivers.modbus import ModbusDriver


class _Plc:
    is_open = True

    def __init__(self):
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        self.t = time.time()
        self.log = []                                       # every write: (kind, addr, values)
        self.discrete = {0: 1, 1: 0}                        # door closed, no alarm
        self.holding = {100: 3700, 101: 500, 102: 2100}     # setpoints x100
        self.pv = {"temperature": 37.0, "co2": 5.0, "o2": 21.0, "humidity": 93.0}
        self.input_addr = {0: "temperature", 1: "co2", 2: "o2", 3: "humidity"}

    def _tick(self):
        now = time.time()
        dt = (now - self.t) / self.scale                    # simulated seconds
        self.t = now
        door_open = not self.discrete[0]
        targets = {"temperature": self.holding[100] / 100, "co2": self.holding[101] / 100,
                   "o2": self.holding[102] / 100, "humidity": 93.0}
        rates = {"temperature": 0.01, "co2": 0.02, "o2": 0.01, "humidity": 0.05}     # units per sim second
        for k, tgt in targets.items():
            if door_open:                                   # gas and heating suspended, chamber drifts to room air
                tgt = {"temperature": 25.0, "co2": 0.04, "o2": 21.0, "humidity": 40.0}[k]
            step = rates[k] * dt
            self.pv[k] += max(-step, min(step, tgt - self.pv[k]))
        self.discrete[1] = 1 if abs(self.pv["temperature"] - targets["temperature"]) > 1.0 else 0

    def read(self, kind, addr, count):
        self._tick()
        if kind == "input":
            vals = []
            for i in range(count):
                name = self.input_addr.get(addr + i)
                if name is None:
                    raise DeviceFault(f"Modbus exception 02: illegal data address (input {addr + i})")
                vals.append(int(round(self.pv[name] * 100)) & 0xFFFF)
            return vals
        table = {"discrete": self.discrete, "holding": self.holding, "coil": {}}[kind]
        out = []
        for i in range(count):
            if addr + i not in table:
                raise DeviceFault(f"Modbus exception 02: illegal data address ({kind} {addr + i})")
            out.append(table[addr + i])
        return out

    def write(self, kind, addr, values):
        self._tick()
        self.log.append((kind, addr, list(values)))
        table = {"holding": self.holding, "coil": {}}.get(kind)
        if table is None or addr not in table:
            raise DeviceFault(f"Modbus exception 02: illegal data address ({kind} {addr})")
        for i, v in enumerate(values):
            table[addr + i] = v


class Sim(ModbusDriver):
    link = _Plc()
