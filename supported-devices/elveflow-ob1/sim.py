"""Simulated twin of the OB1: same descriptor and gates, a made-up fluidic resistance instead of hardware."""
from __future__ import annotations

import importlib.util
import pathlib
import random
import sys

_spec = importlib.util.spec_from_file_location(__name__ + "_real", pathlib.Path(__file__).with_name("driver.py"))
real = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = real
_spec.loader.exec_module(real)

UL_MIN_PER_MBAR = 2.0          # pretend tubing: 500 mbar -> 1000 uL/min


class SimBackend:
    def __init__(self):
        self.p = {ch: 0.0 for ch in real.CHANNELS}
        self.loops: dict[int, tuple[int, float]] = {}
        self.remote = False

    def open(self): pass
    def close(self): pass

    def set_pressure(self, ch, mbar): self.p[ch] = float(mbar)
    def pressure(self, ch): return self.p[ch] + random.gauss(0, 0.3)

    def flow(self, ch):
        for reg, (sens, target) in self.loops.items():
            if sens == ch:
                return target + random.gauss(0, max(0.5, target * 0.004))
        return self.p[ch] * UL_MIN_PER_MBAR + random.gauss(0, 0.5)

    def start_flow_control(self, ch, sensor_ch, target, p, i):
        self.remote = True
        self.loops[ch] = (sensor_ch, target)
        self.p[ch] = target / UL_MIN_PER_MBAR

    def stop_flow_control(self):
        self.remote = False
        self.loops.clear()


class SimOB1(real.OB1):
    def setup(self) -> None:
        super().setup()
        self.cfg = {"device_name": "SIM", "regulators": [2, 2, 0, 0], "sensors": {"1": {"type": 5}}}

    def make_backend(self):
        return SimBackend()
