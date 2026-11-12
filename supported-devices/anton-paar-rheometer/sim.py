"""Simulated twin of the RheoCompass route: a fake workflow that takes the job after a moment, keeps a live export
with the plate temperature settling toward the setpoint, and once the scaled test time has passed writes the
ASCII export (UTF-16 with BOM, tab-separated, `Interval data:` header, bracketed units line) of a shear-thinning
fluid (Carreau flow curve) or a gel (frequency sweep)."""
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

ETA0, ETA_INF, LAMBDA, N = 12.0, 0.05, 0.5, 0.4          # Carreau: a 12 Pa.s shear-thinning gel
G0 = 800.0                                                  # a weak gel: G' ~ G0 w^0.1, G'' ~ 0.25 G'


def fmt(x: float) -> str:
    return f"{x:.6g}".replace(".", ",")                     # the export's decimal comma (German locale)


class SimBackend(real.RheoCompassBackend):
    def __init__(self, cfg, scale):
        super().__init__(cfg)
        self.scale = scale
        self.jobs: dict[str, dict] = {}
        self.plate_c = 23.0

    def write_job(self, token, p, result_name):
        path = super().write_job(token, p, result_name)
        now = time.monotonic()
        self.jobs[token] = {"p": p, "result_name": result_name, "path": path, "read_at": now + 3 * self.scale,
                            "start": now + 3 * self.scale, "done_at": now + (3 + 60 + real.AntonPaarRheometer._expected_s(p)) * self.scale}
        return path

    def _tick(self):
        now = time.monotonic()
        for token, j in list(self.jobs.items()):
            if now >= j["read_at"] and j["path"].exists():
                j["path"].unlink()
            if now >= j["start"]:
                tau = 60 * self.scale
                self.plate_c += (j["p"]["temperature_c"] - self.plate_c) * (1 - math.exp(-(now - j["start"]) / tau))
                self._write_live(j)
            if now >= j["done_at"]:
                self._write_result(j)
                self.jobs.pop(token)

    def picked_up(self, token):
        self._tick()
        return super().picked_up(token)

    def result_path(self, result_name):
        self._tick()
        return super().result_path(result_name)

    def live_temperature(self):
        self._tick()
        return super().live_temperature()

    def _write_live(self, j):
        lines = ["Name:\tlive", "Interval and data points:\t1\t1", "Interval data:\tPoint No.\tTime\tTemperature",
                 "\t[]\t[s]\t[°C]", f"\t1\t{fmt(0.0)}\t{fmt(self.plate_c)}"]
        pathlib.Path(self.cfg["live_export_file"]).write_bytes(("\r\n".join(lines) + "\r\n").encode("utf-16"))

    def _write_result(self, j):
        p = j["p"]
        T = p["temperature_c"]
        rows = []
        if p["test_type"] == "flow_curve":
            fc = p["flow_curve"]
            cols = ["Point No.", "Time", "Shear Rate", "Shear Stress", "Viscosity", "Torque", "Temperature"]
            units = ["[]", "[s]", "[1/s]", "[Pa]", "[Pa·s]", "[mNm]", "[°C]"]
            for i in range(fc["points"]):
                f = i / max(fc["points"] - 1, 1)
                gd = (fc["shear_rate_start"] * (fc["shear_rate_end"] / fc["shear_rate_start"]) ** f if fc.get("log", True)
                      else fc["shear_rate_start"] + (fc["shear_rate_end"] - fc["shear_rate_start"]) * f)
                eta = ETA_INF + (ETA0 - ETA_INF) * (1 + (LAMBDA * gd) ** 2) ** ((N - 1) / 2)
                eta *= math.exp(-0.02 * (T - 25)) * (1 + random.gauss(0, 0.01))
                rows.append([i + 1, (i + 1) * fc["point_duration_s"], gd, eta * gd, eta, eta * gd * 0.0124, T + random.gauss(0, 0.02)])
        else:
            fs = p["frequency_sweep"]
            cols = ["Point No.", "Time", "Frequency", "Angular Frequency", "Strain", "Storage Modulus", "Loss Modulus", "Temperature"]
            units = ["[]", "[s]", "[Hz]", "[rad/s]", "[%]", "[Pa]", "[Pa]", "[°C]"]
            t = 0.0
            for i in range(fs["points"]):
                f = fs["frequency_start_hz"] * (fs["frequency_end_hz"] / fs["frequency_start_hz"]) ** (i / max(fs["points"] - 1, 1))
                w = 2 * math.pi * f
                g1 = G0 * w ** 0.1 * (1 + random.gauss(0, 0.01))
                t += max(5.0, 2.0 / f)
                rows.append([i + 1, t, f, w, fs["strain_pct"], g1, 0.25 * g1 * w ** 0.05, T + random.gauss(0, 0.02)])
        lines = [f"Name:\t{p['sample_name']}", f"Measuring System:\t{p['measuring_system']}", f"Test:\t{p['test_type']}",
                 "Measuring Date/Time:\t" + time.strftime("%d.%m.%Y %H:%M:%S"), f"Interval and data points:\t1\t{len(rows)}",
                 "Interval data:\t" + "\t".join(cols), "\t" + "\t".join(units)]
        lines += ["\t" + "\t".join(str(v) if isinstance(v, int) else fmt(v) for v in r) for r in rows]
        out = pathlib.Path(self.cfg["results_dir"])
        tmp = out / (j["result_name"] + ".txt.tmp")
        tmp.write_bytes(("\r\n".join(lines) + "\r\n").encode("utf-16"))
        os.replace(tmp, out / (j["result_name"] + ".txt"))
        self.log.append(f"export {j['result_name']}.txt written ({len(rows)} points)")


class SimAntonPaarRheometer(real.AntonPaarRheometer):
    def setup(self) -> None:
        super().setup()
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        base = os.environ.get("OPENMHP_HOME") or tempfile.gettempdir()
        pathlib.Path(base).mkdir(parents=True, exist_ok=True)
        root = pathlib.Path(tempfile.mkdtemp(prefix="anton-paar-rheometer-", dir=base))
        for d in ("jobs", "export"):
            (root / d).mkdir()
        (root / "hood.txt").write_text("closed\n", encoding="utf-8")
        self.cfg = {"job_dir": str(root / "jobs"), "results_dir": str(root / "export"), "live_export_file": str(root / "live.txt"),
                    "hood_state_file": str(root / "hood.txt"), "equilibration_s": 300, "max_test_hours": 6, "poll_s": 10,
                    "result_wait_s": 7200}

    def time_scale(self) -> float:
        return self.scale

    def make_backend(self):
        return SimBackend(self.cfg, self.scale)
