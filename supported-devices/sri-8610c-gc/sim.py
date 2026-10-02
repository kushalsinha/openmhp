"""Simulated twin of the SRI 8610C: a plausible CO2-reduction gas peak table, no PeakSimple."""
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

# component: (retention min, area per ppm, typical ppm in the outlet)
GASES = {"H2": (1.2, 0.9, 5200), "CO": (2.6, 2.1, 480), "CH4": (3.4, 6.5, 1500), "C2H4": (5.8, 11.0, 2100)}


class SimBackend:
    channel = 1
    def __init__(self, scale): self.scale, self.until = scale, 0.0
    def open(self): pass
    def start(self, control_path): self.until = time.monotonic() + 600 * self.scale
    def is_running(self): return time.monotonic() < self.until
    def stop(self): self.until = 0.0

    def collect(self, started, sample):
        rows = ["Component\tRetention\tArea\tExternal (ppm)"]
        for name, (rt, k, ppm) in GASES.items():
            c = ppm * random.gauss(1, 0.04)
            rows.append(f"{name}\t{rt + random.gauss(0, 0.01):.3f}\t{c * k:.1f}\t{c:.1f}")
        asc = ["<RATE>=5Hz", "<SIZE>=3000"]
        for k in range(3000):
            tmin = k / 5 / 60
            asc.append(f"{int(1000 * (2 + random.gauss(0, 0.02) + sum(ppm / 500 * math.exp(-((tmin - rt) / 0.05) ** 2) for rt, _, ppm in GASES.values())))},0")
        return [("sim://TCD01.ASC", "\n".join(asc)), ("sim://TCD01.res", "\n".join(rows))]


class SimSRI8610C(real.SRI8610C):
    def setup(self) -> None:
        super().setup()
        self.cfg = {"connector_dll": "SIM"}
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))

    def time_scale(self) -> float:
        return self.scale

    def make_backend(self):
        return SimBackend(self.scale)
