"""Simulated twin of a Gamry potentiostat: no COM, a dummy cell (Rs 200 ohm in series with Rct 2 kohm parallel to
Cdl 20 uF, open-circuit 12 mV) answering OCP, chronoamperometry, cyclic voltammetry and impedance. Time runs at
OPENMHP_SIM_TIME_SCALE real seconds per simulated second (default 0.01); an EIS point takes three periods or 0.2 s.
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

RS, RCT, CDL, E_OC = 200.0, 2000.0, 20e-6, 0.012


class SimRun:
    def __init__(self, kind: str, p: dict, scale: float):
        self.kind, self.p, self.scale = kind, p, scale
        self.t0, self.sent, self.stopped, self.error = time.monotonic(), 0.0, False, None
        if kind in ("ocv", "chrono"):
            self.total, self.dt = p["duration_s"], p["sample_s"]
        else:
            self.rate = p["scan_rate_mV_s"] / 1000
            self.total, self.dt = p["expected_s"], p["step_V"] / self.rate
            e0, e1, e2, ef = p["e_init_V"], p["e_vertex1_V"], p["e_vertex2_V"], p["e_final_V"]
            legs = [(e0, e1), (e1, e2)] + [(e2, e1), (e1, e2)] * (p["cycles"] - 1) + [(e2, ef)]
            self.legs = [(a, b, abs(b - a) / self.rate) for a, b in legs]

    def _now(self) -> float:
        return min(self.total, (time.monotonic() - self.t0) / self.scale)

    def alive(self) -> bool:
        return not self.stopped and self._now() < self.total

    def _row(self, t: float):
        if self.kind == "ocv":
            return (t, E_OC + random.gauss(0, 2e-4), None)
        if self.kind == "chrono":
            e = self.p["e_V"] - E_OC
            tau = CDL * RS * RCT / (RS + RCT)
            i = e / (RS + RCT) + (e / RS - e / (RS + RCT)) * math.exp(-t / tau)
            return (t, self.p["e_V"], i + random.gauss(0, 1e-7))
        tt = t
        for a, b, dur in self.legs:
            if tt <= dur or (a, b, dur) is self.legs[-1]:
                frac = min(1.0, tt / dur) if dur else 1.0
                v = a + (b - a) * frac
                dvdt = (b - a) / dur if dur else 0.0
                i = (v - E_OC) / (RS + RCT) + CDL * dvdt
                return (t, v, i + random.gauss(0, 1e-7))
            tt -= dur
        return (t, self.legs[-1][1], 0.0)

    def poll(self):
        upto, rows, t = self._now(), [], self.sent
        while t < upto and not self.stopped:
            rows.append(self._row(t))
            t += self.dt
        self.sent = t
        return rows

    def stop(self):
        self.stopped = True


class SimBackend:
    def __init__(self, scale: float):
        self.scale, self.section, self.log = scale, "IFC1010-SIM01", []
        self.cell_is_on = False

    def open(self):
        self.log.append(f"open {self.section}")

    def close(self):
        self.log.append("close")

    def cell(self, on: bool):
        self.cell_is_on = on
        self.log.append("cell on" if on else "cell off")

    def start(self, kind, p):
        if kind != "ocv":
            self.cell(True)
        self.log.append(f"run {kind}")
        return SimRun(kind, p, self.scale)

    def measure_z(self, f_hz, e_dc_V, amplitude_V):
        if not self.cell_is_on:
            self.cell(True)
        time.sleep(max(0.2, 3.0 / f_hz) * self.scale)
        w = 2 * math.pi * f_hz
        z = RS + RCT / (1 + 1j * w * RCT * CDL)
        return z.real * (1 + random.gauss(0, 0.002)), z.imag * (1 + random.gauss(0, 0.002))

    def end_z(self):
        self.cell(False)


class Sim(real.Device):
    def setup(self) -> None:
        super().setup()
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        home = pathlib.Path(os.environ.get("OPENMHP_HOME", pathlib.Path.home() / ".openmhp"))
        self.cfg = {"device": "IFC1010-SIM01", "data_dir": str(home / "sim-data" / "gamry-potentiostat"),
                    "max_run_s": 3600, "max_eis_points": 100}

    def time_scale(self) -> float:
        return self.scale

    def make_backend(self):
        return SimBackend(self.scale)
