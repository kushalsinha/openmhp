"""Simulated twin of a Crystal16 under CrystalClear: real temporary folders stand in for the program and export
shares; a fake CrystalClear picks the program up, runs it with a solubility model per reactor and writes one
Version 1014 data report per block. Time is scaled by OPENMHP_SIM_TIME_SCALE (default 0.01)."""
from __future__ import annotations

import csv
import importlib.util
import math
import os
import pathlib
import random
import sys
import tempfile
import time

_spec = importlib.util.spec_from_file_location(__name__ + "_real", pathlib.Path(__file__).with_name("driver.py"))
real = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = real
_spec.loader.exec_module(real)

SAMPLE_S = 10.0                  # one data row every 10 s (the real export logs about every second)
# per reactor: concentration mg/mL; solubility curve c* = a * exp(b * T)
CONC = [5, 10, 20, 40, 8, 16, 32, 64, 6, 12, 24, 48, 7, 14, 28, 56]
A, B, HYST_K = 4.0, 0.045, 12.0


def clear_t(conc: float) -> float:
    return math.log(conc / A) / B


class SimFiles(real.CrystalClearFiles):
    def __init__(self, cfg: dict, scale: float):
        super().__init__(cfg)
        self.scale, self.online, self.log = scale, True, []
        self.pending: dict | None = None

    def open(self) -> None:
        if not self.online:
            raise real.DeviceFault("twin offline", {"transient": True})
        super().open()

    def write_program(self, name: str, program: dict, blocks: list[str]) -> str:
        path = super().write_program(name, program, blocks)
        self.log.append(("program", name, blocks))
        self.pending = {"name": name, "program": program, "blocks": blocks, "at": time.monotonic(),
                        "duration_s": real.program_duration_min(program) * 60}
        return path

    def _profile(self, program: dict):
        """(t_s, setpoint) breakpoints of the program from 20 degC."""
        pts, t, cur = [(0.0, 20.0)], 0.0, 20.0
        for _ in range(int(program["cycles"])):
            for s in program["steps"]:
                if s["action"] in ("heat", "cool"):
                    t += abs(s["temperature_c"] - cur) / max(s["rate_k_min"], 0.01) * 60
                    cur = s["temperature_c"]
                else:
                    t += s["hold_min"] * 60
                pts.append((t, cur))
        return pts

    def _crystalclear(self) -> None:
        p = self.pending
        if not p or (time.monotonic() - p["at"]) / self.scale < p["duration_s"] + 30:
            return
        self.pending = None
        pts = self._profile(p["program"])
        stamp = time.strftime("%m/%d/%y %H:%M")
        for block in p["blocks"]:
            bi = real.BLOCKS.index(block)
            out = pathlib.Path(self.cfg["export_dir"]) / f"{p['name']}_Block{block}.csv"
            with out.open("w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(["Crystal16 Data Report File", "Version: 1014"])
                w.writerow([]); w.writerow(["Experiment details"])
                w.writerow(["ExperimentNumber", "0"]); w.writerow(["Experimentor", "openmhp twin"]); w.writerow(["Project", "SIM"])
                for k in range(real.REACTORS_PER_BLOCK):
                    w.writerow([f"Reactor{k + 1}", f"{CONC[bi * 4 + k]} mg/mL compound in solvent"])
                w.writerow(["Labjournal"]); w.writerow(["Description"]); w.writerow(["Start of Experiment", stamp])
                w.writerow(["Temperature Program"])
                for line in real.program_lines(p["program"], block):
                    w.writerow(line.split(","))
                w.writerow(["Data Block"])
                w.writerow(["Date Time", "Decimal Time [mins]", "Temperature Setpoint [°C]", "Temperature Actual [°C]",
                            *[f"Reactor{k + 1} Transmission [%]" for k in range(real.REACTORS_PER_BLOCK)], "Stirring Rate [rpm]"])
                dissolved = [False] * real.REACTORS_PER_BLOCK
                t, actual = 0.0, 20.0
                while t <= pts[-1][0]:
                    sp = next((pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * (t - pts[i - 1][0]) / max(pts[i][0] - pts[i - 1][0], 1e-9)
                               for i in range(1, len(pts)) if t <= pts[i][0]), pts[-1][1])
                    actual += (sp - actual) * min(1.0, SAMPLE_S / 40)
                    row = [stamp, f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{int(t % 60):02d}", f"{sp:.1f}", f"{actual:.1f}"]
                    for k in range(real.REACTORS_PER_BLOCK):
                        tc = clear_t(CONC[bi * 4 + k])
                        if not dissolved[k] and actual >= tc:
                            dissolved[k] = True
                        elif dissolved[k] and actual <= tc - HYST_K:
                            dissolved[k] = False
                        row.append(str(int(100 if dissolved[k] else max(5, 40 + random.gauss(0, 2)))))
                    row.append(str(int(p["program"]["stirrer_rpm"])))
                    w.writerow(row)
                    t += SAMPLE_S
        self.log.append(("export", p["name"]))

    def exports(self, since: float):
        self._crystalclear()
        return super().exports(since)


class Sim(real.Device):
    def setup(self) -> None:
        super().setup()
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        root = pathlib.Path(tempfile.mkdtemp(prefix="crystal16-sim-"))
        (root / "programs").mkdir()
        (root / "exports").mkdir()
        self.cfg = {"program_dir": str(root / "programs"), "export_dir": str(root / "exports")}

    def time_scale(self) -> float:
        return self.scale

    def make_backend(self):
        return SimFiles(self.cfg, self.scale)
