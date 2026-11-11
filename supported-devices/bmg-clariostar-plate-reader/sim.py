"""Simulated twin of the plate reader: a fake backend with a tray, an incubator that ramps, a read clock per
protocol and a 96-well export file written when the read ends. Time scaled by OPENMHP_SIM_TIME_SCALE."""
from __future__ import annotations

import importlib.util
import os
import pathlib
import random
import sys
import time

_spec = importlib.util.spec_from_file_location(__name__ + "_real", pathlib.Path(__file__).with_name("driver.py"))
real = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = real
_spec.loader.exec_module(real)

PROTOCOLS = {"abs_600": {"duration": 90, "mean": 0.42, "sd": 0.05},
             "bca_562": {"duration": 120, "mean": 0.85, "sd": 0.12},
             "fluor_gfp_kinetic": {"duration": 600, "mean": 12000, "sd": 1500}}
DEFAULT = {"duration": 120, "mean": 1.0, "sd": 0.1}
ROWS, COLS = "ABCDEFGH", range(1, 13)


class SimBackend:
    def __init__(self, scale):
        self.scale, self.log = scale, []
        self.carrier_out, self.until, self.temp, self.sp = False, 0.0, 22.0, None
        self.pending, self.last = None, time.monotonic()

    def open(self):
        self.log.append("open")

    def _tick(self):
        now = time.monotonic()
        dt = (now - self.last) / self.scale
        self.last = now
        target = self.sp if self.sp is not None else 22.0
        step = 0.5 / 60 * dt
        self.temp = target if abs(target - self.temp) <= step else self.temp + step * (1 if target > self.temp else -1)
        if self.pending and now >= self.until:
            self._export()

    def status(self):
        self._tick()
        return "Busy" if self.pending else "Ready"

    def reading(self):
        return self.status() == "Busy"

    def plate_in(self):
        return not self.carrier_out

    def temperature(self):
        self._tick()
        return round(self.temp, 1)

    def set_temperature(self, c):
        self.log.append(("Temp", c)); self.sp = c

    def tray_in(self):
        self.log.append("PlateIn"); self.carrier_out = False

    def tray_out(self):
        self.log.append("PlateOut"); self.carrier_out = True

    def start_read(self, protocol, plate_id, export):
        if self.carrier_out:
            raise real.DeviceFault("Error: plate carrier is out")
        spec = PROTOCOLS.get(protocol, DEFAULT)
        self.log.append(("Run", protocol, plate_id, str(export)))
        self.pending = (spec, export)
        self.until = time.monotonic() + spec["duration"] * self.scale

    def _export(self):
        spec, export = self.pending
        self.pending = None
        lines = ["Well,Value"]
        for r in ROWS:
            for c in COLS:
                blank = 0.05 if c in (11, 12) else 0
                lines.append(f"{r}{c},{max(0.0, random.gauss(spec['mean'] if not blank else blank, spec['sd'])):.4f}")
        pathlib.Path(export).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(export).write_text("\n".join(lines) + "\n", encoding="utf-8")

    def abort(self):
        self.log.append("Terminate"); self.pending = None


class SimPlateReader(real.PlateReader):
    def setup(self) -> None:
        super().setup()
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        self.cfg = {"backend": "bmg", "control": "CLARIOstar", "allowed_protocols": [], "max_read_minutes": 240,
                    "export_dir": str(pathlib.Path.home() / ".openmhp" / "sim-data" / "bmg-clariostar-plate-reader")}

    def time_scale(self) -> float:
        return self.scale

    def make_backend(self):
        return SimBackend(self.scale)
