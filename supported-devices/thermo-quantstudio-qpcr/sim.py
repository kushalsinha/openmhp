"""Simulated twin of the QuantStudio file route: a fake PC that starts the queued plate and exports a Results CSV."""
from __future__ import annotations

import csv
import importlib.util
import json
import os
import pathlib
import random
import sys
import time

_spec = importlib.util.spec_from_file_location(__name__ + "_real", pathlib.Path(__file__).with_name("driver.py"))
real = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = real
_spec.loader.exec_module(real)

DEFAULT_RUN_MIN = 65.0          # a 40-cycle fast TaqMan run with hold stages
RAMP_S_PER_STEP = 20.0          # block ramp plus settling, per step, when a program is given


def _minutes(program) -> float:
    if not program:
        return DEFAULT_RUN_MIN
    total = 0.0
    for st in program["stages"]:
        per_cycle = sum(float(s["hold_s"]) + RAMP_S_PER_STEP for s in st["steps"])
        total += per_cycle * int(st["cycles"])
    return 3.0 + total / 60.0


class SimBackend(real.QuantStudioBackend):
    def __init__(self, cfg: dict, scale: float):
        super().__init__(cfg)
        self.scale = scale
        self.folders_ok = True
        self.hold = False                                  # True: nobody at the PC picks requests up
        self.due: dict[str, float] = {}
        self.running: str | None = None

    def open(self) -> None:
        if not self.folders_ok:
            raise real.DeviceFault("simulated: the share with the Design & Analysis folders is unreachable",
                                   {"transient": True, "recovery": "retry_after"})
        for key in ("import_dir", "results_dir"):
            pathlib.Path(self.cfg[key]).mkdir(parents=True, exist_ok=True)
        super().open()

    def run_state(self) -> str:
        return "running" if self.running else super().run_state()

    def write_plate(self, token: str, params: dict) -> str:
        path = super().write_plate(token, params)
        self.due[token] = time.monotonic() + _minutes(params.get("program")) * 60 * self.scale
        self.running = token                                  # the person pressed Start right away
        return path

    def poll(self) -> None:
        if self.hold:
            return
        for token, when in list(self.due.items()):
            if time.monotonic() < when:
                continue
            req_path = pathlib.Path(self.cfg["import_dir"]) / f"{token}.json"
            try:
                req = json.loads(req_path.read_text(encoding="utf-8"))
                setup = pathlib.Path(self.cfg["import_dir"]) / req["plate_setup_file"]
                rows = list(csv.DictReader(setup.read_text(encoding="utf-8").splitlines(), dialect="excel-tab"))
                self._export(token, rows)
                setup.unlink(); req_path.unlink()
            except OSError:                               # withdrawn: the person never started it
                pass
            if self.running == token:
                self.running = None
            del self.due[token]

    def _export(self, token: str, rows: list[dict]) -> None:
        out = pathlib.Path(self.cfg["results_dir"]) / f"{token}_Results.csv"
        tmp = out.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["# Results export (simulated QuantStudio Design & Analysis)"])
            w.writerow(["Well", "Well Position", "Sample Name", "Target Name", "Task", "Reporter", "Quencher",
                        "CT", "Ct Mean", "Ct SD", "Quantity", "Amp Status"])
            for i, r in enumerate(rows):
                task = r["Task"]
                if task == "NTC":
                    ct, amp, q = "Undetermined", "No Amp", ""
                else:
                    base = 22.0 if task == "POSITIVE" else 26.5
                    ct, amp, q = f"{random.gauss(base, 0.25):.3f}", "Amp", f"{10 ** (random.gauss(4, 0.1)):.1f}"
                w.writerow([i + 1, r["Well"], r["Sample Name"], r["Target Name"], task, r["Reporter"], r["Quencher"],
                            ct, ct if ct != "Undetermined" else "", "0.12" if ct != "Undetermined" else "", q, amp])
        tmp.replace(out)
        self.log.append(f"export {out.name}")


class Sim(real.Device):
    def setup(self) -> None:
        super().setup()
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        home = pathlib.Path(os.environ.get("OPENMHP_HOME", pathlib.Path.home() / ".openmhp"))
        root = home / "sim-data" / "thermo-quantstudio-qpcr"
        self.cfg = {"import_dir": str(root / "plates"), "results_dir": str(root / "results"),
                    "software": "SIM QuantStudio Design & Analysis 2", "wells": 96, "reporter": "FAM",
                    "quencher": "NFQ-MGB", "allowed_templates": [], "result_wait_s": 14400, "poll_s": 30}

    def time_scale(self) -> float:
        return self.scale

    def make_backend(self):
        return SimBackend(self.cfg, self.scale)
