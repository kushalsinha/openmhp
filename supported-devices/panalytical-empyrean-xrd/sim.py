"""Simulated twin of the Data Collector route: a fake job import that takes the job after a moment and, once the
scaled scan time has passed, writes an XRDML 2.1 file (xrdMeasurements / xrdMeasurement / scan / dataPoints with
2Theta and Omega positions, commonCountingTime and counts) of a powder pattern."""
from __future__ import annotations

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

PEAKS = [(12.4, 900), (17.9, 1400), (21.3, 650), (25.6, 2600), (28.1, 480), (31.7, 1100), (38.2, 300), (44.6, 420), (56.1, 260)]
SCHEMA = "2.1"


def pattern(two_theta: float) -> float:
    bg = 60 + 20 * math.exp(-two_theta / 15)
    s = sum(h * math.exp(-0.5 * ((two_theta - c) / 0.07) ** 2) for c, h in PEAKS)
    return max(0.0, random.gauss(bg + s, math.sqrt(bg + s)))


def xrdml(sample_id: str, prog: dict, pts: list[tuple[float, float]], status: str = "Completed") -> str:
    ns = f"http://www.xrdml.com/XRDMeasurement/{SCHEMA}"
    t0 = time.strftime("%Y-%m-%dT%H:%M:%S")
    counts = " ".join(str(int(c)) for _, c in pts)
    intensity_tag = "counts" if SCHEMA.startswith("2") else "intensities"
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<xrdMeasurements xmlns="{ns}" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            f'xsi:schemaLocation="{ns} {ns}/XRDMeasurement.xsd" status="{status}">\n'
            f'<sample type="To be analyzed"><id>{sample_id}</id><name>{sample_id}</name></sample>\n'
            f'<xrdMeasurement measurementType="Scan" status="{status}" sampleMode="Reflection">\n'
            f'<usedWavelength intended="K-Alpha 1"><kAlpha1 unit="Angstrom">1.5405980</kAlpha1><kAlpha2 unit="Angstrom">1.5444260</kAlpha2>'
            f'<kBeta unit="Angstrom">1.3922500</kBeta><ratioKAlpha2KAlpha1>0.5000</ratioKAlpha2KAlpha1></usedWavelength>\n'
            f'<incidentBeamPath><xRayTube name="SIM Cu LFF"><tension unit="kV">40.0</tension><current unit="mA">15.0</current>'
            f'<anodeMaterial>Cu</anodeMaterial></xRayTube></incidentBeamPath>\n'
            f'<scan appendNumber="0" mode="{real.MODES[prog.get("mode", "continuous")]}" scanAxis="{prog.get("scan_axis", "Gonio")}" status="{status}">\n'
            f'<header><startTimeStamp>{t0}</startTimeStamp><endTimeStamp>{t0}</endTimeStamp><author><name>openmhp twin</name></author>'
            f'<source><applicationSoftware version="6.1">Data Collector</applicationSoftware>'
            f'<instrumentControlSoftware version="1.0">SIM</instrumentControlSoftware><instrumentID>SIM-0000</instrumentID></source></header>\n'
            f'<dataPoints>\n<positions axis="2Theta" unit="deg"><startPosition>{pts[0][0]:.4f}</startPosition><endPosition>{pts[-1][0]:.4f}</endPosition></positions>\n'
            f'<positions axis="Omega" unit="deg"><startPosition>{pts[0][0] / 2:.4f}</startPosition><endPosition>{pts[-1][0] / 2:.4f}</endPosition></positions>\n'
            f'<commonCountingTime unit="seconds">{prog["time_per_step_s"]:.2f}</commonCountingTime>\n'
            f'<{intensity_tag} unit="counts">{counts}</{intensity_tag}>\n</dataPoints>\n</scan>\n</xrdMeasurement>\n</xrdMeasurements>\n')


class SimBackend(real.DataCollectorBackend):
    def __init__(self, cfg, scale):
        super().__init__(cfg)
        self.scale = scale
        self.jobs: dict[str, dict] = {}

    def write_job(self, token, p, result_name):
        path = super().write_job(token, p, result_name)
        prog = p["program"]
        n = real.PanalyticalXrd._points(prog)
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

    def result_path(self, result_name):
        self._tick()
        return super().result_path(result_name)

    def _write_result(self, j):
        prog, n = j["p"]["program"], j["n"]
        pts = [(prog["start_2theta"] + i * prog["step"], pattern(prog["start_2theta"] + i * prog["step"])) for i in range(n)]
        out = pathlib.Path(self.cfg["results_dir"])
        tmp = out / (j["result_name"] + ".xrdml.tmp")
        tmp.write_text(xrdml(j["p"]["sample_id"], prog, pts), encoding="utf-8")
        os.replace(tmp, out / (j["result_name"] + ".xrdml"))
        self.log.append(f"result {j['result_name']}.xrdml written ({n} points)")


class SimPanalyticalXrd(real.PanalyticalXrd):
    def setup(self) -> None:
        super().setup()
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        base = os.environ.get("OPENMHP_HOME") or tempfile.gettempdir()
        pathlib.Path(base).mkdir(parents=True, exist_ok=True)
        root = pathlib.Path(tempfile.mkdtemp(prefix="panalytical-empyrean-xrd-", dir=base))
        for d in ("jobs", "results"):
            (root / d).mkdir()
        self.cfg = {"job_dir": str(root / "jobs"), "results_dir": str(root / "results"), "programs_dir": "", "changer_positions": 6,
                    "changer_s": 60, "max_points": 50000, "max_scan_hours": 12, "poll_s": 10, "result_wait_s": 7200}

    def time_scale(self) -> float:
        return self.scale

    def make_backend(self):
        return SimBackend(self.cfg, self.scale)
