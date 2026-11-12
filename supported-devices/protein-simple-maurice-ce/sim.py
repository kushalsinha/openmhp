"""Simulated twin of the Maurice file route: a fake Compass PC that imports batch files and exports peak tables."""
from __future__ import annotations

import csv
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

CIEF_MIN_PER_INJECTION = 10.0        # focusing + imaging; CE-SDS separations run longer
CESDS_MIN_PER_INJECTION = 35.0
BATCH_OVERHEAD_MIN = 5.0


class SimBackend(real.CompassBackend):
    def __init__(self, cfg: dict, scale: float):
        super().__init__(cfg)
        self.scale = scale
        self.folders_ok = True
        self.hold = False                                  # True: nobody at the PC picks requests up
        self.cartridge = True
        self.due: dict[str, float] = {}

    def open(self) -> None:
        if not self.folders_ok:
            raise real.DeviceFault("simulated: the share with the Compass folders is unreachable",
                                   {"transient": True, "recovery": "retry_after"})
        for key in ("import_dir", "results_dir"):
            pathlib.Path(self.cfg[key]).mkdir(parents=True, exist_ok=True)
        super().open()

    def cartridge_present(self):
        return self.cartridge

    def write_batch(self, token: str, params: dict) -> str:
        path = super().write_batch(token, params)
        per = CESDS_MIN_PER_INJECTION if "sds" in params["method"].lower() else CIEF_MIN_PER_INJECTION
        minutes = BATCH_OVERHEAD_MIN + per * int(params["replicates"])
        self.due[token] = time.monotonic() + minutes * 60 * self.scale
        return path

    def poll(self) -> None:
        if self.hold:
            return
        for token, when in list(self.due.items()):
            if time.monotonic() < when:
                continue
            batch = pathlib.Path(self.cfg["import_dir"]) / f"{token}.csv"
            if not batch.is_file():
                del self.due[token]
                continue
            try:
                rows = list(csv.DictReader(batch.read_text(encoding="utf-8").splitlines()))
                self._export(token, rows)
                batch.unlink()
            except OSError:
                del self.due[token]
                continue
            del self.due[token]

    def _export(self, token: str, rows: list[dict]) -> None:
        sds = rows and "sds" in rows[0]["Method"].lower()
        pos_col = "Apparent MW (kDa)" if sds else "pI"
        out = pathlib.Path(self.cfg["results_dir"]) / f"{token}_peaks.csv"
        tmp = out.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Sample Name", "Injection", "Peak Name", pos_col, "Area", "% Area"])
            for r in rows:
                main = random.gauss(96.5 if sds else 62.0, 0.4)
                if sds:
                    peaks = [("LC", 24.9, 1.1), ("HC", 49.8, 1.0), ("Main", 148.2, main), ("HMW", 290.0, 100 - main - 2.1)]
                else:
                    peaks = [("Acidic 1", 8.42, (100 - main) * 0.35), ("Acidic 2", 8.58, (100 - main) * 0.25),
                             ("Main", 8.71, main), ("Basic 1", 8.86, (100 - main) * 0.40)]
                total = random.gauss(185000, 4000)
                for label, pos, pct in peaks:
                    w.writerow([r["Sample"], r["Injection"], label, f"{pos + random.gauss(0, 0.01):.2f}",
                                f"{total * pct / 100:.0f}", f"{pct:.2f}"])
        tmp.replace(out)
        self.log.append(f"export {out.name}")


class Sim(real.Device):
    def setup(self) -> None:
        super().setup()
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        home = pathlib.Path(os.environ.get("OPENMHP_HOME", pathlib.Path.home() / ".openmhp"))
        root = home / "sim-data" / "protein-simple-maurice-ce"
        self.cfg = {"import_dir": str(root / "batches"), "results_dir": str(root / "results"),
                    "software": "SIM Compass for iCE", "allowed_methods": [], "result_wait_s": 7200, "poll_s": 15}

    def time_scale(self) -> float:
        return self.scale

    def make_backend(self):
        return SimBackend(self.cfg, self.scale)
