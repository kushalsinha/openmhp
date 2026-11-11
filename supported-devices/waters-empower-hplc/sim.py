"""Simulated twin of an Empower-controlled HPLC: a fake Empower with a run clock, playing either route.

OPENMHP_SIM_BACKEND=web_api (default) behaves like the Web API: no abort, results only through the export
file. OPENMHP_SIM_BACKEND=toolkit behaves like the Toolkit: abort works and results come back directly.
"""
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


class SimBackend(real.EmpowerBackend):
    def __init__(self, cfg, scale, export_dir, toolkit: bool):
        super().__init__(cfg)
        self.name = "toolkit" if toolkit else "web_api"
        self.can_abort = toolkit
        self.scale, self.export_dir, self.until, self.pending = scale, export_dir, 0.0, None
        self.finished: dict[str, list[dict]] = {}
        self.aborted: list[str] = []

    def open(self): pass

    def methods(self):
        return {"instrument_methods": ["Assay_C18_inst"], "method_sets": ["Assay_C18"],
                "sample_set_methods": [], "plate_types": ["ANSI-48Vial2mLHolder"]}

    def status(self):
        if time.monotonic() < self.until:
            return {"SystemState": "Acquiring", "CurrentSampleSet": self.pending["name"]}
        if self.pending:
            self._finish()
        return {"SystemState": "Idle"}

    def create_and_run(self, ssm, lines, plates, run_mode, name, comment):
        n = len(lines)
        self.pending = {"name": name, "lines": lines, "mode": run_mode}
        self.until = time.monotonic() + n * RUN_MIN_PER_INJECTION * 60 * self.scale

    def abort(self):
        if not self.can_abort:
            return super().abort()
        if self.pending:
            self.aborted.append(self.pending["name"])
        self.pending, self.until = None, 0.0

    def results(self, name):
        return list(self.finished.get(name, [])) if self.can_abort else None

    def _rows(self, p):
        rows = []
        for l in p["lines"]:
            a = random.gauss(152000, 1500)
            rows.append({"SampleName": l["SampleName"], "Vial": l["SamplePos"], "Injection": 1, "Name": "Product",
                         "RetentionTime": 4.21, "Area": round(a), "Amount": round(a / 152000, 3)})
            rows.append({"SampleName": l["SampleName"], "Vial": l["SamplePos"], "Injection": 1, "Name": "Impurity_A",
                         "RetentionTime": 3.05, "Area": round(a * 0.012), "Amount": None})
        return rows

    def _finish(self):
        p, self.pending = self.pending, None
        if p["mode"] == "RunOnly":
            return
        rows = self._rows(p)
        self.finished[p["name"]] = rows
        path = pathlib.Path(self.export_dir)                 # the export method writes its file either way
        path.mkdir(parents=True, exist_ok=True)
        with (path / f"{p['name']}.csv").open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["SampleName", "Vial", "Injection", "Component", "RT_min", "Area", "Amount_mg_mL"])
            for r in rows:
                w.writerow([r["SampleName"], r["Vial"], r["Injection"], r["Name"], r["RetentionTime"], r["Area"],
                            "" if r["Amount"] is None else r["Amount"]])


class SimEmpowerHPLC(real.EmpowerHPLC):
    def setup(self) -> None:
        super().setup()
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        self.sim_backend = os.environ.get("OPENMHP_SIM_BACKEND", "web_api")
        export = str(pathlib.Path.home() / ".openmhp" / "sim-data" / "waters-empower-hplc")
        self.cfg = {"backend": self.sim_backend, "address": "SIM", "database": "SIM", "project": "SIM",
                    "username": "sim", "node": "SIM-NODE", "system": "SIM_HPLC", "plates": {"1": "ANSI-48Vial2mLHolder"},
                    "injection_volume_ul": [0.1, 50], "max_lines": 96,
                    "max_injections_per_sample": 10, "allowed_methods": [], "poll_s": 15, "max_run_hours": 24,
                    "export_dir": export}

    def time_scale(self) -> float:
        return self.scale

    def make_backend(self):
        self.chosen = {"name": self.sim_backend, "reason": "simulated twin, OPENMHP_SIM_BACKEND"}
        return SimBackend(self.cfg, self.scale, self.cfg["export_dir"], toolkit=self.sim_backend == "toolkit")
