"""Simulated twin of an R-Series under Flow Commander: a fake OPC UA address space with pumps, four reactor
channels and a back-pressure model. Time is scaled by OPENMHP_SIM_TIME_SCALE (default 0.01)."""
from __future__ import annotations

import importlib.util
import os
import pathlib
import random
import sys
import threading
import time

_spec = importlib.util.spec_from_file_location(__name__ + "_real", pathlib.Path(__file__).with_name("driver.py"))
real = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = real
_spec.loader.exec_module(real)

NODES = {k: f"ns=2;s=SIM.{k}" for k in real.READ_NODES + real.WRITE_NODES + real.METHOD_NODES}
HEAT_RATE_K_PER_S = 40 / 60          # R4 heats a coil at tens of K/min; cooling is slower
COOL_RATE_K_PER_S = 8 / 60
ROOM_C = 22.0


class SimOpcUa:
    def __init__(self, scale: float):
        self.scale, self.lock, self.log, self.online = scale, threading.Lock(), [], True
        self.nodes = dict(NODES)
        self.v = {"pump_a_flow": 0.0, "pump_b_flow": 0.0, "system_pressure": 0.0, "system_state": 0, "collection_valve": False,
                  "pump_a_flow_setpoint": 0.0, "pump_b_flow_setpoint": 0.0, "bpr_pressure": 5.0, "collection_valve_set": False}
        for n in real.REACTORS:
            self.v[f"reactor_{n}_temperature"] = ROOM_C
            self.v[f"reactor_{n}_setpoint"] = ROOM_C
            self.v[f"reactor_{n}_enable"] = False
        self.last = time.monotonic()

    def open(self) -> None:
        if not self.online:
            raise real.DeviceFault("twin offline", {"transient": True})

    def close(self) -> None: pass

    def _tick(self) -> None:
        now = time.monotonic()
        dt = (now - self.last) / self.scale
        self.last = now
        v = self.v
        for p in ("pump_a_flow", "pump_b_flow"):
            v[p] += max(-2 * dt, min(2 * dt, v[p + "_setpoint"] - v[p]))
        for n in real.REACTORS:
            t, sp = v[f"reactor_{n}_temperature"], v[f"reactor_{n}_setpoint"] if v[f"reactor_{n}_enable"] else ROOM_C
            rate = HEAT_RATE_K_PER_S if sp > t else COOL_RATE_K_PER_S
            v[f"reactor_{n}_temperature"] = t + max(-rate * dt, min(rate * dt, sp - t))
        total = v["pump_a_flow"] + v["pump_b_flow"]
        target = (v["bpr_pressure"] + 0.3 * total) if total > 0 else 0.0
        v["system_pressure"] += max(-3 * dt, min(3 * dt, target - v["system_pressure"]))
        v["collection_valve"] = v["collection_valve_set"]
        if v["system_state"] in (2,) and total == 0 and all(not v[f"reactor_{n}_enable"] for n in real.REACTORS):
            v["system_state"] = 0

    def read(self, key):
        with self.lock:
            self._tick()
            if key not in self.v:
                raise real.DeviceFault(f"no such node {key!r}")
            val = self.v[key]
            return round(val + (random.gauss(0, 0.01) if key == "system_pressure" and val > 0 else 0), 3) if isinstance(val, float) else val

    def write(self, key, value):
        with self.lock:
            self._tick()
            self.log.append(("write", key, value))
            if key not in self.v:
                raise real.DeviceFault(f"OPC UA write to unknown node {key!r}")
            self.v[key] = value

    def call(self, key, *args):
        with self.lock:
            self._tick()
            self.log.append(("call", key, *args))
            if key == "start":
                self.v["system_state"] = 2
            elif key == "stop":
                self.v["system_state"] = 0
                self.v["pump_a_flow_setpoint"] = self.v["pump_b_flow_setpoint"] = 0.0
            return None


class Sim(real.Device):
    def setup(self) -> None:
        super().setup()
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        self.cfg = {"url": "opc.tcp://SIM:4840", "username": None, "max_pressure_bar": 20, "nodes": dict(NODES)}

    def time_scale(self) -> float:
        return self.scale

    def make_backend(self):
        return SimOpcUa(self.scale)
