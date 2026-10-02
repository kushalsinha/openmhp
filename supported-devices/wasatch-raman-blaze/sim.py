"""Simulated twin of the Raman probe: Cu2O bands on a sloping background, fading as if Cu+ were being reduced."""
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

BANDS = {149: 110.0, 219: 80.0, 419: 25.0, 630: 60.0}


class SimBackend:
    def __init__(self, scale):
        self.scale, self.s = scale, {"laser_enable": False, "integration_time_ms": 5000, "scans_to_average": 1}
        self.wavenumbers = [100 + 1.0 * k for k in range(1000)]
        self.t0 = time.monotonic()

    def open(self): pass
    def set(self, name, value): self.s[name] = value
    def detector_temperature(self): return -15.0 + random.gauss(0, 0.05)

    def spectrum(self, timeout_s):
        exposure = self.s["integration_time_ms"] / 1000 * self.s["scans_to_average"]
        time.sleep(exposure * self.scale)
        sim_t = (time.monotonic() - self.t0) / self.scale
        fade = 0.45 + 0.55 * math.exp(-sim_t / 600)          # Cu+ partly reduced over ~10 simulated minutes
        gain = (exposure / 5.0) * (1.0 if self.s["laser_enable"] else 0.0)
        out = []
        for x in self.wavenumbers:
            y = 400 + 0.05 * x + random.gauss(0, 3)
            y += gain * fade * sum(a * math.exp(-((x - c) / 6.0) ** 2) for c, a in BANDS.items())
            out.append(y)
        return out


class SimBlazeRaman(real.BlazeRaman):
    def setup(self) -> None:
        super().setup()
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        self.cfg = {"bands_cm1": [149, 219, 419, 630], "band_half_width_cm1": 12,
                    "data_dir": str(pathlib.Path.home() / ".openmhp" / "sim-data" / "wasatch-raman-blaze")}

    def time_scale(self) -> float:
        return self.scale

    def make_backend(self):
        return SimBackend(self.scale)
