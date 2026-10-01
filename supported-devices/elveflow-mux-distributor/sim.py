"""Simulated twin of the MUX Distributor."""
from __future__ import annotations

import importlib.util
import pathlib
import sys

_spec = importlib.util.spec_from_file_location(__name__ + "_real", pathlib.Path(__file__).with_name("driver.py"))
real = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = real
_spec.loader.exec_module(real)


class SimBackend:
    pos = 1
    def open(self): pass
    def close(self): pass
    def set_valve(self, port, rotation): self.pos = port
    def get_valve(self): return self.pos
    def home(self): self.pos = 1


class SimMux(real.MuxDistributor):
    def setup(self) -> None:
        super().setup()
        self.cfg = {"visa_com": "SIM", "ports": 12,
                    "port_map": {"1": "CO2-saturated catholyte", "2": "DI water", "3": "air (drying)"}}

    def make_backend(self):
        return SimBackend()
