"""Simulated twin of the SP-300: plausible potential traces for a Cu2O/Cu cathode, no hardware.

Simulated time runs faster than the clock: OPENMHP_SIM_TIME_SCALE real seconds per simulated second
(default 0.01, so a 45 min electrolysis takes 27 s).
"""
from __future__ import annotations

import importlib.util
import math
import os
import pathlib
import random
import sys
import time

_spec = importlib.util.spec_from_file_location(__name__ + "_real", pathlib.Path(__file__).with_name("driver.py"))
real = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = real
_spec.loader.exec_module(real)


def _v_reduction(i_mA: float, t: float) -> float:
    # more negative with current; slow drift as the catalyst loses Cu+
    return -1.35 - 0.0042 * abs(i_mA) - 0.03 * (1 - math.exp(-t / 1500))


class SimRun:
    def __init__(self, kind: str, p: dict, scale: float):
        self.kind, self.p, self.scale = kind, p, scale
        self.t0, self.sent_t, self.stopped = time.monotonic(), 0.0, False
        if kind == "ocv":
            self.total, self.dt = p["duration_s"], p["record_dt_s"]
        elif kind == "cp":
            self.total, self.dt = sum(p["durations_s"]) * (p["n_cycles"] + 1), p["record_dt_s"]
        else:
            span = abs(p["e_vertex1_V"] - p["e_start_V"]) + abs(p["e_vertex2_V"] - p["e_vertex1_V"])
            self.rate = p["scan_rate_mV_s"] / 1000
            self.total, self.dt = p["cycles"] * span / self.rate, 0.001 / self.rate * 5
        self.error = None

    def _now(self) -> float:
        return min(self.total, (time.monotonic() - self.t0) / self.scale)

    def alive(self) -> bool:
        return not self.stopped and self._now() < self.total

    def _row(self, t: float):
        p = self.p
        if self.kind == "ocv":
            return (t, 0.12 + random.gauss(0, 0.001), 0.0, 0)
        if self.kind == "cp":
            period = sum(p["durations_s"])
            cyc, ph = int(t // period), t % period
            if len(p["currents_A"]) == 1:
                i = p["currents_A"][0]
                return (t, _v_reduction(i * 1000, t) + random.gauss(0, 0.004), i, 0)
            i_ox, i_red = p["currents_A"]
            t_ox = p["durations_s"][0]
            if ph < t_ox:                              # oxidation: fast jump, slow Cu -> Cu+ plateau, then steady
                v = 0.05 - 0.85 * math.exp(-ph / 0.25) + random.gauss(0, 0.004)
                return (t, v, i_ox, cyc)
            v = _v_reduction(i_red * 1000, t) + 0.6 * math.exp(-(ph - t_ox) / 0.05) + random.gauss(0, 0.004)
            return (t, v, i_red, cyc)
        e0, e1, e2 = p["e_start_V"], p["e_vertex1_V"], p["e_vertex2_V"]
        leg1, leg2 = abs(e1 - e0) / self.rate, abs(e2 - e1) / self.rate
        cyc, ph = int(t // (leg1 + leg2)), t % (leg1 + leg2)
        v = e0 + (e1 - e0) * ph / leg1 if ph < leg1 else e1 + (e2 - e1) * (ph - leg1) / leg2
        i = -0.15 * math.exp((-0.9 - v) / 0.25) + 0.012 * math.exp(-((v + 0.5) / 0.06) ** 2) * (1 if ph >= leg1 else -1)
        return (t, v, i + random.gauss(0, 2e-4), cyc)

    def poll(self):
        upto, rows = self._now(), []
        t = self.sent_t
        while t < upto and not self.stopped:
            rows.append(self._row(t))
            t += self.dt
        self.sent_t = t
        return rows

    def stop(self):
        self.stopped = True


class SimBackend:
    channel = 0
    def __init__(self): self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
    def open(self): pass
    def values(self): return (0.12 + random.gauss(0, 0.001), 0.0)
    def start(self, kind, p): return SimRun(kind, p, self.scale)
    def stop(self): pass


class SimSP300(real.SP300):
    def setup(self) -> None:
        super().setup()
        self.cfg = {"address": "SIM", "channel": 0, "ewe_abort_window_V": [-3.5, 1.5], "live_every_s": 2,
                    "data_dir": str(pathlib.Path.home() / ".openmhp" / "sim-data" / "biologic-sp300")}

    def make_backend(self):
        return SimBackend()
