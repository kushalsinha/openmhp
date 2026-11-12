"""Simulated twin of an EasyMax under iControl: a fake OPC UA address space with a jacket/reactor thermal model.

Tj follows its setpoint at the thermostat's rate; Tr follows Tj with a first-order lag; Tr control is a simple
cascade. Time is scaled by OPENMHP_SIM_TIME_SCALE (default 0.01).
"""
from __future__ import annotations

import importlib.util
import os
import pathlib
import sys
import threading
import time

_spec = importlib.util.spec_from_file_location(__name__ + "_real", pathlib.Path(__file__).with_name("driver.py"))
real = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = real
_spec.loader.exec_module(real)

NODES = {k: f"ns=2;s=SIM.{k}" for k in real.READ_NODES + real.WRITE_NODES + real.METHOD_NODES}
TJ_RATE_K_PER_S = 5 / 60            # jacket thermostat: about 5 K/min
TR_TAU_S = 180.0                     # reactor contents lag the jacket by ~3 min at 400 rpm
ROOM_C = 22.0


class SimOpcUa:
    def __init__(self, scale: float):
        self.scale, self.lock, self.log, self.online = scale, threading.Lock(), [], True
        self.nodes = dict(NODES)
        self.v = {"tr": ROOM_C, "tj": ROOM_C, "stirrer_rpm": 0.0, "stirrer_running": False, "dosing_total_ml": 0.0,
                  "ph": 7.0, "phase": "idle", "connection_status": True,
                  "tr_setpoint": ROOM_C, "tj_setpoint": ROOM_C, "stirrer_setpoint": 0.0, "ramp_rate": 5.0,
                  "thermostat_mode": real.IDLE_MODE}
        self.dosing = None                                       # (ml_left, rate_ml_min)
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
        # stirrer
        v["stirrer_rpm"] += max(-200 * dt, min(200 * dt, v["stirrer_setpoint"] - v["stirrer_rpm"]))
        v["stirrer_running"] = v["stirrer_rpm"] > 1
        # thermostat demand
        mode = v["thermostat_mode"]
        if mode == real.TJ_MODE:
            tj_target = v["tj_setpoint"]
        elif mode == real.TR_MODE:
            tj_target = max(v["tr_setpoint"] - 60, min(v["tr_setpoint"] + 60, v["tr_setpoint"] + 2.5 * (v["tr_setpoint"] - v["tr"])))
        else:
            tj_target = ROOM_C
        rate = min(TJ_RATE_K_PER_S, v["ramp_rate"] / 60) if mode != real.IDLE_MODE else 0.5 / 60
        v["tj"] += max(-rate * dt, min(rate * dt, tj_target - v["tj"]))
        tau = TR_TAU_S if v["stirrer_rpm"] > 50 else TR_TAU_S * 4
        v["tr"] += (v["tj"] - v["tr"]) * min(1.0, dt / tau)
        # dosing
        if self.dosing:
            left, rate_ml_min = self.dosing
            d = min(left, rate_ml_min / 60 * dt)
            v["dosing_total_ml"] += d
            left -= d
            self.dosing = (left, rate_ml_min) if left > 1e-6 else None
            v["ph"] = max(1.0, v["ph"] - 0.02 * d)
        v["phase"] = "dosing" if self.dosing else ("running" if v["phase"] not in ("idle",) else "idle")

    def read(self, key):
        with self.lock:
            self._tick()
            if key not in self.v:
                raise real.DeviceFault(f"no such node {key!r}")
            val = self.v[key]
            return round(val, 3) if isinstance(val, float) else val

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
            if key == "start_experiment":
                self.v["phase"] = "running"
            elif key == "end_experiment":
                self.v["phase"] = "idle"
            elif key == "dose":
                self.dosing = (float(args[0]), float(args[1]))
            elif key == "stop_dosing":
                self.dosing = None
            elif key == "safe_state":
                self.v["thermostat_mode"] = real.IDLE_MODE
                self.v["stirrer_setpoint"] = 0.0
                self.v["phase"] = "idle"
            return None


class Sim(real.Device):
    def setup(self) -> None:
        super().setup()
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        self.cfg = {"url": "opc.tcp://SIM:4840", "username": None, "nodes": dict(NODES)}

    def time_scale(self) -> float:
        return self.scale

    def make_backend(self):
        return SimOpcUa(self.scale)
