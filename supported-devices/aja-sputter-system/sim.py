"""Simulated twin: a fake PLC answering the template register map with a small vacuum and plasma model.

Time runs at OPENMHP_SIM_TIME_SCALE real seconds per simulated second (default 0.01). The chamber starts
pumped to base pressure; `vent` raises it to atmosphere in minutes and `pump_down` brings it back over
about three hours (exponential in log pressure). Process pressure is the chamber pressure plus the argon
flow's contribution while the gate valve is open; the plasma strikes a few seconds after the supply is
enabled when the pressure is in the ignition window, otherwise the PLC clears the plasma coil. Power follows
the setpoint once struck; the substrate heater ramps at 0.5 degC/s; thickness accumulates at a rate
proportional to power while the shutter is open (readable as `link.thickness_nm`). An address outside the
map raises DeviceFault, as a real PLC answers Modbus exception 02.
"""
from __future__ import annotations

import math
import os
import time

from openmhp.driver import DeviceFault
from openmhp.drivers.modbus import decode, encode

import importlib.util
import pathlib
import sys

_spec = importlib.util.spec_from_file_location(__name__ + "_real", pathlib.Path(__file__).with_name("driver.py"))
real = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = real
_spec.loader.exec_module(real)

P_BASE, P_PROC, PWR, T_SUB, FLOW = 100, 102, 104, 106, 108
PWR_SP, T_SP, FLOW_SP = 200, 202, 204
SHUTTER, PLASMA, ROTATION, HEATER, PUMP, VENT = 10, 11, 12, 13, 20, 21
DOOR, BASE_OK, WATER, ROBOT = 0, 1, 2, 3
BASE_THRESHOLD = 5e-6                   # mbar: the PLC's base-pressure permissive (placeholder)
ATM = 1000.0


class _Plc:
    is_open = True

    def __init__(self):
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        self.t = time.monotonic()
        self.log: list[tuple] = []
        self.coils = {SHUTTER: 0, PLASMA: 0, ROTATION: 0, HEATER: 0, PUMP: 0, VENT: 0}
        self.discrete = {DOOR: 1, BASE_OK: 1, WATER: 1, ROBOT: 0}
        self.holding: dict[int, int] = {}
        self.input: dict[int, int] = {}
        self.chamber = 2e-7                 # mbar, pumped overnight
        self.pumped = True                  # gate valve open, turbo at speed
        self.temp = 22.0
        self.power = 0.0
        self.plasma_since = None
        self.thickness_nm = 0.0
        for a, v in ((PWR_SP, 0.0), (T_SP, 22.0), (FLOW_SP, 0.0)):
            self._set(self.holding, a, v)
        self._refresh()

    @staticmethod
    def _set(table, addr, value):
        w = encode(value, "float32")
        table[addr], table[addr + 1] = w[0], w[1]

    @staticmethod
    def _get(table, addr):
        return decode([table[addr], table[addr + 1]], "float32")

    def _tick(self):
        now = time.monotonic()
        dt = (now - self.t) / self.scale
        self.t = now
        if dt <= 0:
            return
        # vacuum: pump-down is exponential in log pressure (about 3 h from atmosphere to base); venting takes ~3 min
        if self.coils[VENT]:
            self.pumped = False
            self.chamber = min(ATM, self.chamber + (ATM - self.chamber) * (1 - math.exp(-dt / 60.0)))
            if self.chamber > 0.99 * ATM:
                self.coils[VENT] = 0
        elif self.coils[PUMP] or self.pumped:
            self.pumped = True
            self.coils[PUMP] = 0 if self.chamber < BASE_THRESHOLD else self.coils[PUMP]
            lp = math.log10(self.chamber)
            lp += (math.log10(2e-7) - lp) * (1 - math.exp(-dt / 1200.0))
            self.chamber = 10 ** lp
        flow_sp = self._get(self.holding, FLOW_SP)
        flow = flow_sp if self.pumped else 0.0
        process = self.chamber + (2.0e-4 * flow if self.pumped else 0.0)
        # plasma: strikes 3 s after the coil is set when the pressure is in the window; otherwise the PLC clears the coil
        psp = self._get(self.holding, PWR_SP)
        if self.coils[PLASMA] and psp > 0 and 1e-3 <= process <= 2e-1 and self.discrete[WATER] and self.discrete[DOOR]:
            self.plasma_since = self.plasma_since if self.plasma_since is not None else 0.0
            self.plasma_since += dt
            self.power = psp if self.plasma_since >= 3.0 else 0.0
        else:
            if self.coils[PLASMA] and (self.plasma_since or 0.0) >= 10.0 and self.power == 0.0:
                self.coils[PLASMA] = 0                               # ignition failed
            elif self.coils[PLASMA] and not (1e-3 <= process <= 2e-1):
                self.plasma_since = (self.plasma_since or 0.0) + dt
            else:
                self.plasma_since = None
            self.power = 0.0
            if not self.coils[PLASMA]:
                self.plasma_since = None
        if self.power > 0 and self.coils[SHUTTER]:
            self.thickness_nm += 0.085 * self.power * dt / 60.0     # 8.5 nm/min at 100 W (placeholder rate)
        # substrate heater
        tsp = self._get(self.holding, T_SP) if self.coils[HEATER] else 22.0
        self.temp += max(-0.2 * dt, min(0.5 * dt, tsp - self.temp))
        self._refresh(process, flow)

    def _refresh(self, process=None, flow=None):
        if process is None:
            process = self.chamber + 2.0e-4 * self._get(self.holding, FLOW_SP)
            flow = self._get(self.holding, FLOW_SP)
        self._set(self.input, P_BASE, self.chamber)
        self._set(self.input, P_PROC, process)
        self._set(self.input, PWR, self.power)
        self._set(self.input, T_SUB, self.temp)
        self._set(self.input, FLOW, flow)
        self.discrete[BASE_OK] = 1 if self.chamber < BASE_THRESHOLD else 0

    def read(self, kind, addr, count):
        self._tick()
        table = {"discrete": self.discrete, "holding": self.holding, "coil": self.coils, "input": self.input}[kind]
        out = []
        for i in range(count):
            if addr + i not in table:
                raise DeviceFault(f"Modbus exception 02: illegal data address ({kind} {addr + i})")
            out.append(table[addr + i])
        if kind == "coil" and addr == PLASMA:
            out[0] = 1 if self.power > 0 else 0                  # the read-back says whether the plasma has struck
        return out

    def write(self, kind, addr, values):
        self._tick()
        self.log.append((kind, addr, list(values)))
        if kind == "coil" and addr in self.coils:
            self.coils[addr] = 1 if values[0] else 0
            if addr == PLASMA and not values[0]:
                self.plasma_since, self.power = None, 0.0
            if addr == VENT and values[0] and self.power > 0:
                self.coils[VENT] = 0                                  # the PLC refuses to vent with the plasma on
        elif kind == "holding" and addr in self.holding:
            for i, v in enumerate(values):
                self.holding[addr + i] = v
        else:
            raise DeviceFault(f"Modbus exception 02: illegal data address ({kind} {addr})")
        self._refresh()


class Sim(real.Device):
    link = _Plc()

    def time_scale(self) -> float:
        return self.link.scale
