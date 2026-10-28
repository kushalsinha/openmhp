"""Simulated twin of an Empower-controlled HPLC: fake Web API with a run clock and an export file."""
from __future__ import annotations

import importlib.util
import os
import pathlib
import csv
import random
import sys
import time

_spec = importlib.util.spec_from_file_location(__name__ + "_real", pathlib.Path(__file__).with_name("driver.py"))
real = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = real
_spec.loader.exec_module(real)

RUN_MIN_PER_INJECTION = 12.0


class SimBackend:
    def __init__(self, scale, export_dir):
        self.scale, self.export_dir, self.until, self.pending = scale, export_dir, 0.0, None

    def open(self): pass

    def methods(self):
        return {"instrument_methods": ["Assay_C18_inst"], "method_sets": ["Assay_C18"],
                "sample_set_methods": [], "plate_types": ["ANSI-48Vial2mLHolder"]}

    def status(self):
        if time.monotonic() < self.until:
            return {"SystemState": "Acquiring", "CurrentSampleSet": self.pending["name"]}
        if self.pending:
            self._export()
        return {"SystemState": "Idle"}

    def create_and_run(self, ssm, lines, plates, run_mode, name, comment):
        n = len(lines)
        self.pending = {"name": name, "lines": lines, "mode": run_mode}
        self.until = time.monotonic() + n * RUN_MIN_PER_INJECTION * 60 * self.scale

    def _export(self):
        p, self.pending = self.pending, None
        if p["mode"] == "RunOnly":
            return
        path = pathlib.Path(self.export_dir)
        path.mkdir(parents=True, exist_ok=True)
        with (path / f"{p['name']}.csv").open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["SampleName", "Vial", "Injection", "Component", "RT_min", "Area", "Amount_mg_mL"])
            for l in p["lines"]:
                for k in range(1):
                    a = random.gauss(152000, 1500)
                    w.writerow([l["SampleName"], l["SamplePos"], k + 1, "Product", 4.21, round(a), round(a / 152000, 3)])
                    w.writerow([l["SampleName"], l["SamplePos"], k + 1, "Impurity_A", 3.05, round(a * 0.012), ""])


class SimEmpowerHPLC(real.EmpowerHPLC):
    def setup(self) -> None:
        super().setup()
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        export = str(pathlib.Path.home() / ".openmhp" / "sim-data" / "waters-empower-hplc")
        self.cfg = {"address": "SIM", "node": "SIM-NODE", "system": "SIM_HPLC", "plates": {"1": "ANSI-48Vial2mLHolder"},
                    "injection_volume_ul": [0.1, 50], "max_lines": 96,
                    "max_injections_per_sample": 10, "allowed_methods": [], "poll_s": 15, "max_run_hours": 24,
                    "export_dir": export}

    def time_scale(self) -> float:
        return self.scale

    def make_backend(self):
        return SimBackend(self.scale, self.cfg["export_dir"])
