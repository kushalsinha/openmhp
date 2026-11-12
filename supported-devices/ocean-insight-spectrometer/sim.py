"""Simulated twin of a cooled Ocean Insight spectrometer (QE Pro shape): a lamp spectrum with absorption bands,
dark counts, a TEC that settles toward its setpoint, and saturation above max_intensity. No seabreeze."""
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

PIXELS = 1044
MAX_INTENSITY = 200000.0
DARK_COUNTS = 1500.0
BANDS = {(430.0, 12.0, 0.55), (662.0, 9.0, 0.35)}         # chlorophyll-like absorptions: centre nm, width, depth


class SimBackend:
    def __init__(self, scale: float):
        self.scale = scale
        self.integration_us = 100000
        self.lamp_on = True                                     # a person blocks the light for a dark: the test flips this
        self.tec_on, self.tec_setpoint, self.temp, self.t_tec = False, None, 22.0, time.monotonic()
        self.log: list[str] = []
        self.wl = [350.0 + 800.0 * k / (PIXELS - 1) for k in range(PIXELS)]

    def open(self):
        self.log.append("open")

    def close(self):
        self.log.append("close")

    def identity(self):
        return {"serial_number": "QEP01234", "model": "QE-PRO", "pixels": PIXELS,
                "max_intensity": MAX_INTENSITY, "integration_limits_us": [8000, 1600000000]}

    def set_integration_time(self, micros):
        self.log.append(f"integration_time_micros {micros}")
        self.integration_us = int(micros)

    def wavelengths(self):
        return list(self.wl)

    def _temperature(self):
        target = self.tec_setpoint if self.tec_on and self.tec_setpoint is not None else 22.0
        dt = (time.monotonic() - self.t_tec) / self.scale
        self.temp = target + (self.temp - target) * math.exp(-dt / 60.0)
        self.t_tec = time.monotonic()
        return self.temp

    def intensities(self, correct_dark_counts, correct_nonlinearity):
        exposure = self.integration_us / 1e6
        time.sleep(exposure * self.scale)
        self.log.append(f"intensities dark={correct_dark_counts} nl={correct_nonlinearity}")
        temp = self._temperature()
        dark = DARK_COUNTS * (1 + 0.04 * (temp - 22.0)) * exposure / 0.1
        out = []
        for x in self.wl:
            lamp = (900000.0 if self.lamp_on else 0.0) * exposure * math.exp(-((x - 650.0) / 260.0) ** 2)
            for c, w, depth in BANDS:
                lamp *= 1 - depth * math.exp(-((x - c) / w) ** 2)
            y = lamp + (0.0 if correct_dark_counts else dark) + random.gauss(0, 25)
            out.append(min(MAX_INTENSITY, max(0.0, y)))
        return out

    def has_tec(self):
        return True

    def detector_temperature(self):
        return round(self._temperature() + random.gauss(0, 0.02), 3)

    def set_tec(self, setpoint_c):
        self._temperature()
        self.log.append(f"tec {'off' if setpoint_c is None else setpoint_c}")
        self.tec_on, self.tec_setpoint = setpoint_c is not None, setpoint_c


class SimOceanSpectrometer(real.OceanSpectrometer):
    def setup(self) -> None:
        super().setup()
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        home = pathlib.Path(os.environ.get("OPENMHP_HOME", pathlib.Path.home() / ".openmhp"))
        self.cfg = {"serial_number": None, "data_dir": str(home / "sim-data" / "ocean-insight-spectrometer")}

    def time_scale(self) -> float:
        return self.scale

    def make_backend(self):
        self.link = SimBackend(self.scale)
        return self.link
