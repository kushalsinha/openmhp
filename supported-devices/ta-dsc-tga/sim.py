"""Simulated twin of the TRIOS route: a fake TRIOS that reads the run list after a moment, keeps a live export
with the current sample temperature while the program runs, and writes the TRIOS-style text export (header
lines, [step], columns, units, tab-separated rows) once the scaled program time has passed. The DSC curve has
one melting endotherm; the TGA curve one decomposition step."""
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

MELT_C, MELT_WIDTH, DECOMP_C = 168.0, 4.0, 310.0


def temperature_at(segments, t_s, start_c=25.0):
    temp, t = start_c, 0.0
    for s in segments:
        if s["type"] == "ramp":
            d = abs(s["to_c"] - temp) / s["rate_k_min"] * 60
            if t_s < t + d:
                return temp + (s["to_c"] - temp) * (t_s - t) / d
            t, temp = t + d, s["to_c"]
        hold = (s.get("hold_min") or 0) * 60
        if t_s < t + hold:
            return temp
        t += hold
    return temp


def curve(instrument, segments, mass_mg):
    total = real.program_duration_s(segments)
    n = max(50, min(3000, int(total / 2)))
    rows = []
    for i in range(n):
        t = total * i / (n - 1)
        T = temperature_at(segments, t)
        if instrument == "dsc":
            hf = -0.02 - 0.0004 * (T - 25) - 2.5 * math.exp(-0.5 * ((T - MELT_C) / MELT_WIDTH) ** 2) * (1 if i else 0)
            rows.append((t / 60, T, hf + random.gauss(0, 0.003)))
        else:
            frac = 1 / (1 + math.exp(-(T - DECOMP_C) / 8))
            w = mass_mg * (1 - 0.42 * frac)
            rows.append((t / 60, T, w + random.gauss(0, 0.002), 100 * w / mass_mg))
    return rows


class SimBackend(real.TriosBackend):
    def __init__(self, cfg, scale):
        super().__init__(cfg)
        self.scale = scale
        self.jobs: dict[str, dict] = {}

    def write_run(self, token, p, export_name):
        path = super().write_run(token, p, export_name)
        segs = p["program"]["segments"]
        now = time.monotonic()
        self.jobs[token] = {"p": p, "export": export_name, "path": path, "start": now + 300 * self.scale,
                            "read_at": now + 2 * self.scale, "done_at": now + (300 + real.program_duration_s(segs)) * self.scale}
        return path

    def _tick(self):
        now = time.monotonic()
        for token, j in list(self.jobs.items()):
            if now >= j["read_at"] and j["path"].exists():
                j["path"].unlink()
            if now >= j["start"] and now < j["done_at"]:
                T = temperature_at(j["p"]["program"]["segments"], (now - j["start"]) / self.scale)
                live = pathlib.Path(self.cfg["live_export_file"])
                live.write_text("Sample name\t%s\n\n[step]\nTime\tTemperature\nmin\t°C\n%.3f\t%.2f\n"
                                % (j["p"]["sample_name"], (now - j["start"]) / self.scale / 60, T), encoding="utf-8")
            if now >= j["done_at"]:
                self._write_export(j)
                self.jobs.pop(token)

    def picked_up(self, token):
        self._tick()
        return super().picked_up(token)

    def export_path(self, export_name):
        self._tick()
        return super().export_path(export_name)

    def live_temperature(self):
        self._tick()
        return super().live_temperature()

    def _write_export(self, j):
        p = j["p"]
        inst, segs = p["instrument"], p["program"]["segments"]
        rows = curve(inst, segs, p["mass_mg"])
        if inst == "dsc":
            cols, units = ["Time", "Temperature", "Heat Flow (Normalized)"], ["min", "°C", "W/g"]
        else:
            cols, units = ["Time", "Temperature", "Weight", "Weight (%)"], ["min", "°C", "mg", "%"]
        lines = [f"Filename\t{j['export'][:-4]}.tri", f"Instrument name\tDiscovery {inst.upper()} (simulated)",
                 "operator\tsim", f"rundate\t{time.strftime('%m/%d/%Y')}", f"Sample name\t{p['sample_name']}",
                 f"Sample mass\t{p['mass_mg']:.3f} mg", f"Procedure name\t{real.procedure_text(segs)}", "", "[step]",
                 f"Step name\t{real.procedure_text(segs)}", "\t".join(cols), "\t".join(units)]
        lines += ["\t".join(f"{v:.4f}" for v in r) for r in rows]
        out = pathlib.Path(self.cfg["export_dir"]) / j["export"]
        tmp = out.with_suffix(".tmp")
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(tmp, out)
        self.log.append(f"export {j['export']} written ({len(rows)} rows)")


class SimTADscTga(real.TADscTga):
    def setup(self) -> None:
        super().setup()
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        base = os.environ.get("OPENMHP_HOME") or tempfile.gettempdir()
        pathlib.Path(base).mkdir(parents=True, exist_ok=True)
        root = pathlib.Path(tempfile.mkdtemp(prefix="ta-dsc-tga-", dir=base))
        for d in ("runs", "export"):
            (root / d).mkdir()
        self.cfg = {"run_dir": str(root / "runs"), "export_dir": str(root / "export"),
                    "live_export_file": str(root / "export" / "live.txt"), "pan_positions": 50,
                    "max_temperature_c": {"dsc": 600, "tga": 1000}, "max_run_hours": 12, "load_equilibrate_s": 300,
                    "poll_s": 10, "result_wait_s": 14400}

    def time_scale(self) -> float:
        return self.scale

    def make_backend(self):
        return SimBackend(self.cfg, self.scale)
