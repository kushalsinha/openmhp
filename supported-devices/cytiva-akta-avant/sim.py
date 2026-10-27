"""Simulated twin of the ÄKTA avant: a fake UNICORN OPC address space with two methods and a run clock.

A method run takes `duration` simulated seconds, scaled by OPENMHP_SIM_TIME_SCALE (default 0.01).
"""
from __future__ import annotations

import importlib.util
import math
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

ROOT = "\\Method\\DefaultHome"
METHODS = {
    "HisTrap_5ml_purification": {"duration": 3600, "variables": {
        "Flow rate": {"Unit": "mL/min", "Minimum value": 0.5, "Maximum value": 5.0, "Default value": 1.0},
        "Sample volume": {"Unit": "mL", "Minimum value": 1.0, "Maximum value": 50.0, "Default value": 10.0},
        "Elution gradient length": {"Unit": "CV", "Minimum value": 5.0, "Maximum value": 40.0, "Default value": 20.0}}},
    "Superdex200_SEC": {"duration": 5400, "variables": {
        "Flow rate": {"Unit": "mL/min", "Minimum value": 0.1, "Maximum value": 1.0, "Default value": 0.5}}},
}
BLOCKS = ["Equilibration", "Sample application", "Wash", "Elution", "Re-equilibration"]


class SimOPC:
    def __init__(self, scale: float):
        self.scale, self.items, self.run = scale, {"STATE\\AssignState": 0, "STATE\\RunState": 0,
                                                   "STATE\\UserInControl": ""}, None
        for m, spec in METHODS.items():
            base = f"{ROOT}\\Purification\\{m}"
            for v, props in spec["variables"].items():
                self.items[f"{base}\\Method Variable(s)\\{v}"] = props["Default value"]
        self.lock = threading.Lock()

    def open(self): pass

    def _tick(self):
        r = self.run
        if not r:
            return
        now = time.monotonic()
        if r["paused_at"] is None:
            r["t"] += (now - r["last"]) / self.scale
        r["last"] = now
        if r["t"] >= r["duration"] and self.items["STATE\\RunState"] in (1, 3):
            self.items["STATE\\RunState"] = 0
            self.run = None

    def read(self, item):
        with self.lock:
            self._tick()
            r = self.run
            frac = (r["t"] / r["duration"]) if r else 0.0
            block = BLOCKS[min(len(BLOCKS) - 1, int(frac * len(BLOCKS)))] if r else ""
            elution = math.exp(-((frac - 0.62) / 0.03) ** 2) if r else 0.0
            live = {"Event\\Analog Picture\\UV1": 5 + 1800 * elution + random.gauss(0, 1),
                    "Event\\Analog Picture\\Cond": (2 + 40 * max(0.0, min(1.0, (frac - 0.55) / 0.2))) if r else 2.0,
                    "Event\\Analog Picture\\System pressure": (0.32 if r else 0.0) + random.gauss(0, 0.005),
                    "Event\\Rundata\\System flow": r["flow"] if r and r["paused_at"] is None else 0.0,
                    "Event\\Curves\\CurrentMethod": r["method"] if r else "",
                    "Event\\Curves\\CurrentResult": r["result"] if r else "",
                    "Event\\Curves\\CurrentBlock": block}
            if item in live:
                return live[item]
            if item in self.items:
                return self.items[item]
            raise real.DeviceFault(f"no such OPC item {item!r}")

    def write(self, item, value):
        with self.lock:
            self._tick()
            if item == "STATE\\AssignState":
                self.items[item] = int(value)
                return
            if item.endswith("\\Run Method"):
                base = item.rsplit("\\", 1)[0]
                name = base.rsplit("\\", 1)[1]
                if not self.items.get(f"{base}\\Result Name"):
                    return                                   # UNICORN: no result name, no start
                spec = METHODS[name]
                flow = self.items.get(f"{base}\\Method Variable(s)\\Flow rate", 1.0)
                self.run = {"method": name, "result": self.items[f"{base}\\Result Name"], "t": 0.0,
                            "duration": spec["duration"], "last": time.monotonic(), "paused_at": None, "flow": flow}
                self.items["STATE\\RunState"] = 1
                return
            if item == "STATE\\Command" and self.run:
                if value == 0:
                    self.run["paused_at"] = self.run["t"]; self.items["STATE\\RunState"] = 2
                elif value == 1:
                    self.items["STATE\\RunState"] = 3
                elif value == 2:
                    self.run["paused_at"] = None; self.items["STATE\\RunState"] = 1
                elif value == 3:
                    self.run = None; self.items["STATE\\RunState"] = 0
                return
            if "\\Method Variable(s)\\" in item:
                base, var = item.split("\\Method Variable(s)\\")
                props = METHODS[base.rsplit("\\", 1)[1]]["variables"][var]
                if not props["Minimum value"] <= value <= props["Maximum value"]:
                    raise real.DeviceFault(f"OPC write {item!r} rejected: out of range")
            self.items[item] = value

    def browse(self, path):
        if path == ROOT:
            return ["Purification"]
        if path == f"{ROOT}\\Purification":
            return list(METHODS)
        if path.endswith("\\Method Variable(s)"):
            return list(METHODS[path.split("\\")[-2]]["variables"])
        if path.endswith("\\Question(s)"):
            return []
        raise real.DeviceFault(f"no branch {path!r}")

    def properties(self, item):
        base, var = item.split("\\Method Variable(s)\\")
        props = dict(METHODS[base.rsplit("\\", 1)[1]]["variables"][var])
        props["Current value"] = self.items.get(item)
        return props


class SimAktaAvant(real.AktaAvant):
    def setup(self) -> None:
        super().setup()
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        self.cfg = {"progid": "SIM", "method_root": ROOT, "allowed_methods": [], "live_every_s": 60,
                    "items": {"uv_mAU": "Event\\Analog Picture\\UV1", "conductivity_mS_cm": "Event\\Analog Picture\\Cond",
                              "pressure_MPa": "Event\\Analog Picture\\System pressure", "flow_ml_min": "Event\\Rundata\\System flow"}}

    def time_scale(self) -> float:
        return self.scale

    def make_backend(self):
        return SimOPC(self.scale)
