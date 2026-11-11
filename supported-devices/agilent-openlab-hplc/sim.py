"""Simulated twin of an OpenLab CDS HPLC behind Sample Scheduler: real temporary folders stand in for the command
and result shares, a fake scheduler picks commands up, runs each injection for RUN_MIN_PER_INJECTION simulated
minutes and copies a result CSV out. Time is scaled by OPENMHP_SIM_TIME_SCALE (default 0.01)."""
from __future__ import annotations

import csv
import importlib.util
import os
import pathlib
import random
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

_spec = importlib.util.spec_from_file_location(__name__ + "_real", pathlib.Path(__file__).with_name("driver.py"))
real = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = real
_spec.loader.exec_module(real)

RUN_MIN_PER_INJECTION = 12.0
PICKUP_S = 20.0
KNOWN_METHODS = {"Assay_C18", "Impurity_C18"}


class SimBackend(real.SchedulerFolderBackend):
    """The real folder backend over temp folders, plus the scheduler's side of the exchange."""

    def __init__(self, cfg: dict, scale: float):
        super().__init__(cfg)
        self.scale, self.online, self.log = scale, True, []
        self.pending: dict[str, dict] = {}

    def open(self) -> None:
        if not self.online:
            raise real.DeviceFault("twin offline", {"transient": True})
        super().open()

    def methods(self) -> dict:
        return {"acquisition_methods": sorted(KNOWN_METHODS), "processing_methods": ["Assay_C18_proc"]}

    def submit(self, name: str, lines: list[dict]) -> str:
        self.log.append(("submit", name, len(lines)))
        path = super().submit(name, lines)
        self.pending[name] = {"at": time.monotonic(), "lines": lines, "path": pathlib.Path(path)}
        return path

    def _scheduler(self) -> None:
        """What Sample Scheduler does: validate and move the command, run, then Review for LIMS copies the report."""
        now = time.monotonic()
        for name, p in list(self.pending.items()):
            elapsed = (now - p["at"]) / self.scale
            if p.get("state") is None and elapsed >= PICKUP_S:
                root = ET.fromstring(p["path"].read_bytes())
                bad = any(a.findtext("AcquisitionMethod") not in KNOWN_METHODS or not a.findtext("Vial") for a in root.iter("Analysis"))
                cmd = pathlib.Path(self.cfg["command_dir"])
                if bad:
                    (cmd / "trash").mkdir(exist_ok=True)
                    p["path"].replace(cmd / "trash" / p["path"].name)
                    p["state"] = "rejected"
                else:
                    (cmd / "processed").mkdir(exist_ok=True)
                    p["path"].replace(cmd / "processed" / p["path"].name)
                    p["state"] = "running"
                    p["run_s"] = sum(l["injections"] for l in p["lines"]) * RUN_MIN_PER_INJECTION * 60
            elif p.get("state") == "running" and elapsed >= PICKUP_S + p["run_s"]:
                out = pathlib.Path(self.cfg["result_dir"]) / f"{name}_Report.csv"
                with out.open("w", encoding="utf-8", newline="") as f:
                    w = csv.writer(f)
                    w.writerow(["Sample Name", "Vial", "Injection", "Compound", "RT [min]", "Area", "Amount [mg/mL]"])
                    for l in p["lines"]:
                        for k in range(l["injections"]):
                            a = random.gauss(152000, 1500)
                            w.writerow([l["name"], l["vial"], k + 1, "Product", 4.21, round(a), round(a / 152000, 3)])
                            w.writerow([l["name"], l["vial"], k + 1, "Impurity_A", 3.05, round(a * 0.012), ""])
                p["state"] = "done"
                del self.pending[name]

    def command_state(self, name: str) -> str:
        self._scheduler()
        return super().command_state(name)

    def result_files(self, result_name: str, since: float):
        self._scheduler()
        return super().result_files(result_name, since)


class Sim(real.Device):
    def setup(self) -> None:
        super().setup()
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        root = pathlib.Path(tempfile.mkdtemp(prefix="openlab-sim-"))
        (root / "LIMS_Commands").mkdir()
        (root / "LIMS_Results").mkdir()
        self.cfg = {"command_dir": str(root / "LIMS_Commands"), "result_dir": str(root / "LIMS_Results"), "project": "SIM_Project",
                    "instrument": "SIM_1290", "injection_source": "Sampler", "methods_dir": None, "processing_method": "Assay_C18_proc",
                    "injection_volume_ul": [0.1, 100], "max_lines": 96, "allowed_methods": [], "poll_s": 15, "max_run_hours": 24,
                    "accept_timeout_s": 300}

    def time_scale(self) -> float:
        return self.scale

    def make_backend(self):
        return SimBackend(self.cfg, self.scale)
