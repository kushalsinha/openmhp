"""Simulated twin of an Orbitrap Tribrid under the IAPI: the instrument is On and scanning once a second
(scaled), every custom scan request is answered by the next scan with the requested m/z window, and the
spectrum holds a few peptide-like ions on a noise floor. No pythonnet, no Thermo assemblies."""
from __future__ import annotations

import importlib.util
import math
import os
import pathlib
import random
import sys
import threading
import time

_spec = importlib.util.spec_from_file_location(__name__ + "_real", pathlib.Path(__file__).with_name("driver.py"))
real = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = real
_spec.loader.exec_module(real)

IONS = [(445.1200, 8.0e6), (524.2650, 2.5e7), (785.8420, 1.2e7), (1046.5420, 4.0e6), (1570.6770, 9.0e5)]
SCAN_PERIOD_S = 1.0


class SimBackend(real.IapiBackend):
    def __init__(self, cfg, scale):
        super().__init__(cfg)
        self.scale = scale
        self.log: list[str] = []
        self.requests: list[tuple[dict, int]] = []
        self.state = "On"
        self.scan_number = 1200
        self._stop = threading.Event()
        self._thread = None

    def open(self) -> None:
        self.log.append("StartOnlineAccess")
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()

    def _spectrum(self, lo: float, hi: float, resolution: int) -> list[tuple[float, float]]:
        peaks = []
        for mz, h in IONS:
            if lo <= mz <= hi:
                for iso in range(3):                      # an isotope cluster, singly charged spacing
                    m = mz + iso * 1.00335
                    if lo <= m <= hi:
                        peaks.append((round(m + random.gauss(0, m / resolution / 4), 5),
                                      round(h * (0.6 ** iso) * random.gauss(1, 0.05), 1)))
        n_noise = int((hi - lo) / 10)
        peaks += [(round(random.uniform(lo, hi), 5), round(random.expovariate(1 / 3e3), 1)) for _ in range(n_noise)]
        return sorted(peaks)

    def _loop(self) -> None:
        while not self._stop.is_set():
            time.sleep(max(0.01, SCAN_PERIOD_S * self.scale))
            lo, hi, res, access = 150.0, 2000.0, 120000, None
            if self.requests:
                values, rn = self.requests.pop(0)
                lo, hi, res, access = float(values["FirstMass"]), float(values["LastMass"]), int(values["OrbitrapResolution"]), str(rn)
                self.log.append(f"custom scan {rn} delivered")
            self.scan_number += 1
            peaks = self._spectrum(lo, hi, res)
            summary = {"scan_number": self.scan_number, "tic": round(sum(i for _, i in peaks), 1),
                       "header": {"Scan": str(self.scan_number), "ScanMode": "Full"}, "peaks": peaks, "access_id": access}
            with self.lock:
                self.scans_seen += 1
                self.last = summary
                if access is not None:
                    self.pending[access] = summary

    def instrument_name(self):
        return "Orbitrap Fusion Lumos (simulated)"

    def connected(self):
        return True

    def system_state(self):
        return self.state

    def system_mode(self):
        return "Running" if self.requests else "Standby"

    def request_custom_scan(self, values, running_number):
        self.log.append(f"SetCustomScan {running_number} " + " ".join(f"{k}={v}" for k, v in values.items()))
        self.requests.append((values, running_number))

    def cancel_custom_scan(self):
        self.log.append("CancelCustomScan")
        self.requests.clear()


class SimOrbitrapIAPI(real.OrbitrapIAPI):
    def setup(self) -> None:
        super().setup()
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        home = pathlib.Path(os.environ.get("OPENMHP_HOME", pathlib.Path.home() / ".openmhp"))
        self.cfg = {"assembly_dir": "SIM", "instrument_index": 1, "scan_timeout_s": 30,
                    "data_dir": str(home / "sim-data" / "thermo-orbitrap-iapi")}

    def time_scale(self) -> float:
        return self.scale

    def make_backend(self):
        self.link = SimBackend(self.cfg, self.scale)
        return self.link
