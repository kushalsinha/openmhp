"""Simulated twin of the Zetasizer: a fake SDK with a Peltier cell that ramps, an equilibration wait, a
measurement clock per SOP and plausible DLS (mAb, liposome) and zeta results. Time scaled by OPENMHP_SIM_TIME_SCALE."""
from __future__ import annotations

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

SOPS = {"mAb_size_25C.zsop": {"kind": "size", "duration": 120, "d": 10.4, "pdi": 0.06},
        "LNP_size_25C.zsop": {"kind": "size", "duration": 150, "d": 85.0, "pdi": 0.12},
        "mAb_zeta_pH6.zsop": {"kind": "zeta", "duration": 180, "zeta": -3.2, "cond": 1.1},
        "LNP_zeta_PBS.zsop": {"kind": "zeta", "duration": 180, "zeta": -14.5, "cond": 15.8}}
DEFAULT = {"size": {"kind": "size", "duration": 120, "d": 50.0, "pdi": 0.1}, "zeta": {"kind": "zeta", "duration": 180, "zeta": -10.0, "cond": 5.0}}


class FakeSdk:
    def __init__(self, scale):
        self.scale, self.log = scale, []
        self.temp, self.sp, self.equil, self.last = 24.0, 25.0, 120.0, time.monotonic()
        self.until, self.spec, self.res, self.aborted = 0.0, None, None, False

    def open(self):
        self.log.append("Connect")

    def _tick(self):
        now = time.monotonic()
        dt = (now - self.last) / self.scale
        self.last = now
        step = 1.0 / 60 * dt
        self.temp = self.sp if abs(self.sp - self.temp) <= step else self.temp + step * (1 if self.sp > self.temp else -1)

    def status(self):
        self._tick()
        return "Measuring" if self.running() else "Idle"

    def cell_temperature(self):
        self._tick()
        return round(self.temp + random.gauss(0, 0.01), 2)

    def set_temperature(self, c):
        self.log.append(("SetTemperature", c)); self.sp = float(c)

    def set_equilibration(self, s):
        self.log.append(("SetEquilibrationTime", s)); self.equil = float(s)

    def start(self, kind, sop, sample_name):
        self.log.append(("LoadSop", sop)); self.log.append(("StartMeasurement", sample_name))
        self.spec = SOPS.get(sop, DEFAULT[kind])
        self.aborted = False
        self.until = time.monotonic() + (self.spec["duration"] + self.equil) * self.scale

    def running(self):
        return time.monotonic() < self.until and not self.aborted

    def abort(self):
        self.log.append("AbortMeasurement"); self.aborted = True; self.until = 0.0

    def result(self, kind):
        if self.aborted or self.spec is None:
            raise real.DeviceFault("no completed measurement")
        s = self.spec
        if kind == "size":
            d = s["d"] * random.gauss(1, 0.02)
            peaks = [{"diameter_nm": round(d * 1.05, 2), "intensity_pct": round(97 + random.gauss(0, 1), 1), "width_nm": round(d * 0.3, 2)}]
            if random.random() < 0.5:
                peaks.append({"diameter_nm": round(d * 40, 1), "intensity_pct": round(100 - peaks[0]["intensity_pct"], 1), "width_nm": round(d * 12, 1)})
            return {"z_average_nm": round(d, 2), "pdi": round(max(0.01, s["pdi"] * random.gauss(1, 0.1)), 3), "peaks": peaks,
                    "temperature_c": round(self.temp, 2), "attenuator": random.choice([6, 7, 8])}
        z = s["zeta"] * random.gauss(1, 0.08)
        return {"zeta_mv": round(z, 2), "conductivity_ms_cm": round(s["cond"] * random.gauss(1, 0.02), 3),
                "mobility": round(z * 0.0786, 4), "quality": "Good" if abs(z) > 2 else "Poor: low zeta"}

    def export(self, path):
        self.log.append(("ExportResult", path))
        pathlib.Path(path).write_text("sim export\n", encoding="utf-8")


class SimZetasizer(real.Zetasizer):
    def setup(self) -> None:
        super().setup()
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        self.cfg = {"sop_dir": "C:\\ZSXplorer\\SOPs", "allowed_sops": [], "max_minutes": 60,
                    "export_dir": str(pathlib.Path.home() / ".openmhp" / "sim-data" / "malvern-zetasizer-dls")}

    def time_scale(self) -> float:
        return self.scale

    def make_backend(self):
        return FakeSdk(self.scale)
