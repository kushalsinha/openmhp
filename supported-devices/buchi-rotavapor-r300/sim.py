"""Simulated twin of the R-300 / I-300 Pro: a fake OpenInterface with a bath, pump, lift and vapour model.

Time behaviour is scaled by OPENMHP_SIM_TIME_SCALE (default 0.01: one simulated minute passes in 0.6 s).
"""
from __future__ import annotations

import copy
import importlib.util
import math
import os
import pathlib
import sys
import threading
import time

_spec = importlib.util.spec_from_file_location(__name__ + "_real", pathlib.Path(__file__).with_name("driver.py"))
real = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = real
_spec.loader.exec_module(real)

BATH_RATE_C_PER_S = 0.08          # water bath heats about 5 K/min
PUMP_RATE_MBAR_PER_S = 25.0       # V-300 pumping a 1 L flask down
LIFT_MM_PER_S = 30.0
ROOM_C = 22.0
# a rough Antoine-like boiling point of dichloromethane as a function of pressure, for the vapour probe
def boiling_c(mbar: float) -> float:
    if mbar <= 0:
        return -60.0
    return 1225.4 / (7.409 - math.log10(max(mbar, 1.0) * 0.75006)) - 230.3


class SimBackend:
    def __init__(self, scale: float):
        self.scale, self.lock, self.log = scale, threading.Lock(), []
        self.online = True
        self.p = {"heating": {"set": 40.0, "act": ROOM_C, "running": False},
                  "cooling": {"set": 10.0, "act": 12.0, "running": False},
                  "vacuum": {"set": 300.0, "act": 1013.0, "aerateValveOpen": True, "aerateValvePulse": False,
                             "vacuumValveOpen": False, "vaporTemp": ROOM_C, "powerPercentAct": 0, "running": False},
                  "rotation": {"set": 100.0, "act": 0.0, "running": False},
                  "lift": {"set": 0, "act": 0, "limit": 220},
                  "program": {"type": "Manual"},
                  "globalStatus": {"timeStamp": "", "processTime": 0, "runId": 0, "onHold": False,
                                   "foamActive": False, "currentError": 0, "running": False}}
        self.last = time.monotonic()
        self.solvent_ml = 150.0

    def open(self) -> None:
        if not self.online:
            raise real.DeviceFault("twin offline", {"transient": True})

    def info(self) -> dict:
        return {"systemClass": "Rotavapor", "systemLine": "R-300", "systemName": "SIM R-300",
                "controller": {"model": "I-300 Pro", "serial": "SIM0001", "firmware": "sim", "operatingTimeCounter": 0,
                               "runCounters": {"totalRuns": 0}}}

    def _tick(self) -> None:
        now = time.monotonic()
        dt = (now - self.last) / self.scale
        self.last = now
        p = self.p
        # bath
        target = p["heating"]["set"] if p["heating"]["running"] else ROOM_C
        rate = BATH_RATE_C_PER_S if p["heating"]["running"] else 0.02
        p["heating"]["act"] += max(-rate * dt, min(rate * dt, target - p["heating"]["act"]))
        # chiller
        ctarget = p["cooling"]["set"] if p["cooling"]["running"] else ROOM_C
        p["cooling"]["act"] += max(-0.05 * dt, min(0.05 * dt, ctarget - p["cooling"]["act"]))
        # rotation
        rtarget = p["rotation"]["set"] if p["rotation"]["running"] else 0.0
        p["rotation"]["act"] += max(-50 * dt, min(50 * dt, rtarget - p["rotation"]["act"]))
        # lift
        p["lift"]["act"] += max(-LIFT_MM_PER_S * dt, min(LIFT_MM_PER_S * dt, p["lift"]["set"] - p["lift"]["act"]))
        # vacuum: the pump runs while the global process runs and the aerate valve is closed
        v = p["vacuum"]
        pumping = p["globalStatus"]["running"] and not v["aerateValveOpen"]
        v["running"] = pumping
        if v["aerateValveOpen"]:
            v["act"] += min(200 * dt, 1013.0 - v["act"])
        elif pumping:
            v["act"] += max(-PUMP_RATE_MBAR_PER_S * dt, min(5 * dt, v["set"] - v["act"]))
        else:
            v["act"] += min(0.5 * dt, 1013.0 - v["act"])          # a slow leak
        v["powerPercentAct"] = 100 if pumping and v["act"] > v["set"] + 2 else (30 if pumping else 0)
        # vapour: once the bath is above the boiling point at this pressure, solvent distils and the probe reads bp
        bp = boiling_c(v["act"])
        in_bath = p["lift"]["act"] > 200
        if in_bath and self.solvent_ml > 0 and p["heating"]["act"] > bp + 2 and p["rotation"]["act"] > 10:
            v["vaporTemp"] += max(-2 * dt, min(2 * dt, bp - v["vaporTemp"]))
            self.solvent_ml -= 0.4 * dt / 60                          # about 0.4 mL per simulated minute
        else:
            v["vaporTemp"] += max(-0.5 * dt, min(0.5 * dt, ROOM_C - v["vaporTemp"]))
        if p["globalStatus"]["running"]:
            p["globalStatus"]["processTime"] += dt

    def process(self) -> dict:
        with self.lock:
            self._tick()
            return copy.deepcopy(self.p)

    def patch(self, body: dict) -> dict:
        with self.lock:
            self._tick()
            self.log.append(copy.deepcopy(body))
            for section, fields in body.items():
                if section not in self.p or not isinstance(fields, dict):
                    raise real.DeviceFault(f"OpenInterface PUT /process answered 400 BadParameters: unknown section {section!r}",
                                           {"status": 400})
                for k, val in fields.items():
                    if section == "lift" and k == "set" and val not in (0, 220):
                        raise real.DeviceFault("OpenInterface PUT /process answered 400 BadParameters: lift.set must be 0 or 220",
                                               {"status": 400})
                    self.p[section][k] = val
            if body.get("globalStatus", {}).get("running") is True:
                self.p["globalStatus"]["runId"] += 1
                self.p["globalStatus"]["processTime"] = 0
            return copy.deepcopy(self.p)


class Sim(real.Device):
    def setup(self) -> None:
        super().setup()
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        self.cfg = {"host": "SIM", "user": "rw", "verify_tls": False, "timeout_s": 10}

    def time_scale(self) -> float:
        return self.scale

    def make_backend(self):
        return SimBackend(self.scale)
