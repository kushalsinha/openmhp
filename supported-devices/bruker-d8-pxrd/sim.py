"""Simulated twin of the DIFFRAC.SUITE route: a fake measurement centre that imports the job after a moment and,
once the scaled scan time has passed, writes a minimal .brml zip (Experiment0/RawData0.xml with Datum lines) and
an .xy text export of a powder pattern with a few peaks."""
from __future__ import annotations

import importlib.util
import math
import os
import pathlib
import random
import sys
import tempfile
import time
import zipfile

_spec = importlib.util.spec_from_file_location(__name__ + "_real", pathlib.Path(__file__).with_name("driver.py"))
real = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = real
_spec.loader.exec_module(real)

PEAKS = [(12.4, 900), (17.9, 1400), (21.3, 650), (25.6, 2600), (28.1, 480), (31.7, 1100), (38.2, 300), (44.6, 420)]


def pattern(two_theta: float) -> float:
    bg = 60 + 20 * math.exp(-two_theta / 15)
    s = sum(h * math.exp(-0.5 * ((two_theta - c) / 0.07) ** 2) for c, h in PEAKS)
    return max(0.0, random.gauss(bg + s, math.sqrt(bg + s)))


class SimBackend(real.DiffracBackend):
    def __init__(self, cfg, scale):
        super().__init__(cfg)
        self.scale = scale
        self.jobs: dict[str, dict] = {}

    def write_job(self, token, p, result_name):
        path = super().write_job(token, p, result_name)
        prog = p["program"]
        n = math.floor((prog["end_2theta"] - prog["start_2theta"]) / prog["step"]) + 1
        now = time.monotonic()
        self.jobs[token] = {"p": p, "n": n, "result_name": result_name, "path": path,
                            "read_at": now + 3 * self.scale, "done_at": now + (60 + n * prog["time_per_step_s"]) * self.scale}
        return path

    def _tick(self):
        now = time.monotonic()
        for token, j in list(self.jobs.items()):
            if now >= j["read_at"] and j["path"].exists():
                j["path"].unlink()
            if now >= j["done_at"]:
                self._write_result(j)
                self.jobs.pop(token)

    def picked_up(self, token):
        self._tick()
        return super().picked_up(token)

    def brml_path(self, result_name):
        self._tick()
        return super().brml_path(result_name)

    def _write_result(self, j):
        prog, n = j["p"]["program"], j["n"]
        pts = [(prog["start_2theta"] + i * prog["step"], pattern(prog["start_2theta"] + i * prog["step"])) for i in range(n)]
        tps = prog["time_per_step_s"]
        datum = "\n".join(f"<Datum>{tps:.3f},{i},{a:.4f},{a / 2:.4f},{int(c)}</Datum>" for i, (a, c) in enumerate(pts))
        xml = ('<?xml version="1.0" encoding="utf-8"?>\n<RawData>\n<Identifier><SampleId>%s</SampleId></Identifier>\n'
               '<DataRoutes><DataRoute>\n<ScanInformation>\n<MeasurementPoints>%d</MeasurementPoints>\n'
               '<TimePerStepEffective>%.3f</TimePerStepEffective>\n<ScaleAxes><ScaleAxisInfo AxisId="TwoTheta">'
               '<Start>%.4f</Start><Stop>%.4f</Stop><Increment>%.4f</Increment></ScaleAxisInfo></ScaleAxes>\n'
               '</ScanInformation>\n%s\n</DataRoute></DataRoutes>\n</RawData>\n'
               % (j["p"]["sample_id"], n, tps, prog["start_2theta"], prog["end_2theta"], prog["step"], datum))
        out = pathlib.Path(self.cfg["results_dir"])
        tmp = out / (j["result_name"] + ".brml.tmp")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("Experiment0/RawData0.xml", xml)
            z.writestr("Experiment0/MeasurementContainer.xml", "<MeasurementContainer/>")
        os.replace(tmp, out / (j["result_name"] + ".brml"))
        (pathlib.Path(self.cfg["xy_dir"]) / (j["result_name"] + ".xy")).write_text(
            "".join(f"{a:.4f} {c:.0f}\n" for a, c in pts), encoding="utf-8")
        self.log.append(f"result {j['result_name']}.brml and .xy written ({n} points)")


class SimBrukerD8(real.BrukerD8):
    def setup(self) -> None:
        super().setup()
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        base = os.environ.get("OPENMHP_HOME") or tempfile.gettempdir()
        pathlib.Path(base).mkdir(parents=True, exist_ok=True)
        root = pathlib.Path(tempfile.mkdtemp(prefix="bruker-d8-pxrd-", dir=base))
        for d in ("jobs", "results", "xy"):
            (root / d).mkdir()
        self.cfg = {"job_dir": str(root / "jobs"), "results_dir": str(root / "results"), "xy_dir": str(root / "xy"),
                    "methods_dir": "", "changer_positions": 9, "changer_s": 60, "max_points": 20000,
                    "max_scan_hours": 12, "poll_s": 10, "result_wait_s": 7200}

    def time_scale(self) -> float:
        return self.scale

    def make_backend(self):
        return SimBackend(self.cfg, self.scale)
