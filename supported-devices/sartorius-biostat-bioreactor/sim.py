"""Simulated twin: a fake Biobrain OPC UA address space with a small bioreactor model.

Temperature, pH, DO, agitation and gas flow ramp toward their setpoints; a started recipe walks
through its phases over its duration; feeding raises the weight. Time is scaled by
OPENMHP_SIM_TIME_SCALE (default 0.01). No OPC UA library is needed.
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

N = real.DEFAULT_NODES
RECIPES = {"CHO_fedbatch_14d": {"duration": 14 * 86400, "phases": ["Inoculation", "Growth", "Production", "Harvest"]},
           "HEK_transient_5d": {"duration": 5 * 86400, "phases": ["Inoculation", "Growth", "Harvest"]}}
DEFAULT_RECIPE = {"duration": 4 * 3600, "phases": ["Inoculation", "Growth", "Harvest"]}


class _Node:
    def __init__(self, server, nid):
        self.server, self.nid = server, nid

    def get_value(self):
        return self.server.read(self.nid)

    def set_value(self, v):
        self.server.write(self.nid, v)

    def call_method(self, mid, *args):
        return self.server.call(self.nid, mid, *args)


class FakeServer:
    """Answers get_node() like asyncua's sync client; unknown ids answer BadNodeIdUnknown like a UA server."""

    def __init__(self, scale: float):
        self.scale = scale
        self.lock = threading.Lock()
        self.log: list = []
        self.values = {N["temperature"]: 22.0, N["temperature_setpoint"]: 37.0, N["temperature_mode"]: 0,
                       N["ph"]: 7.2, N["ph_setpoint"]: 7.0, N["ph_mode"]: 0,
                       N["do"]: 95.0, N["do_setpoint"]: 40.0, N["do_mode"]: 0,
                       N["agitation"]: 0.0, N["agitation_setpoint"]: 150.0, N["agitation_mode"]: 0,
                       N["gas_flow"]: 0.0, N["gas_flow_setpoint"]: 0.5, N["gas_flow_mode"]: 0,
                       N["weight"]: 1.850, N["foam_alarm"]: 0,
                       N["feed_rate_setpoint"]: 0.0, N["feed_mode"]: 0, N["acid_mode"]: 0, N["base_mode"]: 0,
                       N["phase"]: "", N["recipe_object"]: None}
        self.recipe = None
        self.last = time.monotonic()

    def is_open(self):
        return True

    def get_node(self, nid):
        return _Node(self, nid)

    # ---- the model ----------------------------------------------------------------------
    def _tick(self):
        now = time.monotonic()
        dt = (now - self.last) / self.scale                      # simulated seconds
        self.last = now
        v = self.values

        def ramp(pv, sp, rate):
            step = rate * dt
            return sp if abs(sp - pv) <= step else pv + step * (1 if sp > pv else -1)
        v[N["temperature"]] = ramp(v[N["temperature"]], v[N["temperature_setpoint"]] if v[N["temperature_mode"]] else 22.0, 0.5 / 60)
        v[N["ph"]] = ramp(v[N["ph"]], v[N["ph_setpoint"]] if v[N["ph_mode"]] else 7.2, 0.05 / 60)
        v[N["agitation"]] = ramp(v[N["agitation"]], v[N["agitation_setpoint"]] if v[N["agitation_mode"]] else 0.0, 50.0)
        v[N["gas_flow"]] = ramp(v[N["gas_flow"]], v[N["gas_flow_setpoint"]] if v[N["gas_flow_mode"]] else 0.0, 1.0)
        v[N["do"]] = ramp(v[N["do"]], v[N["do_setpoint"]] if v[N["do_mode"]] else 95.0, 2.0 / 60)
        if v[N["feed_mode"]] and v[N["feed_rate_setpoint"]] > 0:
            v[N["weight"]] += v[N["feed_rate_setpoint"]] / 1000 * dt / 3600       # mL/h -> kg
        r = self.recipe
        if r:
            r["t"] += dt
            frac = r["t"] / r["duration"]
            if frac >= 1.0:
                v[N["phase"]] = "Complete"
                self.recipe = None
            else:
                v[N["phase"]] = r["phases"][min(len(r["phases"]) - 1, int(frac * len(r["phases"])))]

    def read(self, nid):
        with self.lock:
            self._tick()
            if nid not in self.values:
                raise real.DeviceFault(f"BadNodeIdUnknown: {nid}")
            v = self.values[nid]
            return round(v, 3) if isinstance(v, float) else v

    def write(self, nid, value):
        with self.lock:
            self._tick()
            if nid not in self.values:
                raise real.DeviceFault(f"BadNodeIdUnknown: {nid}")
            self.log.append(("write", nid, value))
            self.values[nid] = value

    def call(self, obj, mid, *args):
        with self.lock:
            self._tick()
            self.log.append(("call", obj, mid, args))
            if mid == N["recipe_start"]:
                spec = RECIPES.get(str(args[0]) if args else "", DEFAULT_RECIPE)
                self.recipe = {"t": 0.0, **spec}
                self.values[N["phase"]] = spec["phases"][0]
                for key in ("temperature_mode", "ph_mode", "do_mode", "agitation_mode", "gas_flow_mode"):
                    self.values[N[key]] = 1
                return 0
            if mid == N["recipe_stop"]:
                self.recipe = None
                self.values[N["phase"]] = "Stopped"
                return 0
            raise real.DeviceFault(f"BadMethodInvalid: {mid}")


def Sim():
    scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
    server = FakeServer(scale)
    drv = real.build(server, {"url": "opc.tcp://sim:4840", "poll_s": 10}, scale=scale)
    drv.server = server                                          # the test asserts on its log
    return drv
