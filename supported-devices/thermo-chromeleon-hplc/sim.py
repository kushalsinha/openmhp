"""Simulated twin of a Chromeleon-controlled HPLC: a fake SDK with a data vault, an instrument queue and peak results.

Each injection takes RUN_MIN_PER_INJECTION simulated minutes, scaled by OPENMHP_SIM_TIME_SCALE (default 0.01).
"""
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

RUN_MIN_PER_INJECTION = 12.0
INSTRUMENT_METHODS = {"Assay_C18_15min": 15.0, "Impurity_C18_40min": 40.0}
PROCESSING_METHODS = ["Assay_C18_proc", "Impurity_proc"]


class SimBackend:
    def __init__(self, scale: float):
        self.scale, self.online, self.log = scale, True, []
        self.sequences: dict[str, dict] = {}
        self.queue: list[str] = []
        self.ended: set[str] = set()
        self.started = None

    def open(self) -> None:
        if not self.online:
            raise real.DeviceFault("twin offline", {"transient": True})

    def methods(self) -> dict:
        return {"instrument_methods": sorted(INSTRUMENT_METHODS), "processing_methods": sorted(PROCESSING_METHODS)}

    def _tick(self) -> None:
        if self.started is None or not self.queue:
            return
        url = self.queue[0]
        seq = self.sequences[url]
        elapsed_min = (time.monotonic() - self.started) / self.scale / 60
        done = 0
        for i, l in enumerate(seq["lines"]):
            runtime = INSTRUMENT_METHODS.get(l["instrument_method"], RUN_MIN_PER_INJECTION)
            if elapsed_min >= sum(INSTRUMENT_METHODS.get(x["instrument_method"], RUN_MIN_PER_INJECTION) for x in seq["lines"][:i + 1]):
                self.ended.add(f"{url}/{i + 1}.smp")
                done += 1
        if done == len(seq["lines"]):
            self.queue.pop(0)
            self.started = time.monotonic() if self.queue else None
            self.ended = set() if self.queue else self.ended

    def status(self) -> dict:
        self._tick()
        return {"instrument": "SIM_HPLC", "state": "Running" if self.queue else "Idle", "injections_ended": len(self.ended)}

    def create_sequence(self, name: str, lines: list[dict]) -> str:
        for l in lines:
            if l["instrument_method"] not in INSTRUMENT_METHODS:
                raise real.DeviceFault(f"Chromeleon has no IInstrumentMethod at chrom://sim/vault/{l['instrument_method']}")
        url = f"chrom://sim/ChromeleonLocal/MHP/{name}.seq"
        self.sequences[url] = {"lines": lines}
        self.log.append(("create_sequence", name, len(lines)))
        return url

    def submit(self, seq_url: str) -> None:
        self.log.append(("submit", seq_url))
        self.queue.append(seq_url)
        self.ended = set()
        if self.started is None:
            self.started = time.monotonic()

    def sequence_done(self, seq_url: str, n: int) -> bool:
        self._tick()
        return seq_url not in self.queue

    def results(self, seq_url: str, channel: str) -> list[dict]:
        out = []
        for l in self.sequences[seq_url]["lines"]:
            a = random.gauss(152000, 1500)
            out.append({"injection": l["name"], "peaks": [
                {"name": "Impurity_A", "retention_min": round(3.05 + random.gauss(0, 0.01), 3), "area": round(a * 0.012, 1), "height": round(a * 0.0012, 1)},
                {"name": "Product", "retention_min": round(4.21 + random.gauss(0, 0.01), 3), "area": round(a, 1), "height": round(a * 0.09, 1)}]})
        return out


class Sim(real.Device):
    def setup(self) -> None:
        super().setup()
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        self.cfg = {"sdk_dir": "SIM", "data_vault": "chrom://sim/ChromeleonLocal/MHP", "instrument": "chrom://sim/Instruments/SIM_HPLC",
                    "username": None, "processing_method": "Assay_C18_proc", "injection_volume_ul": [0.1, 100], "max_lines": 96,
                    "allowed_methods": [], "poll_s": 10, "max_run_hours": 24}

    def time_scale(self) -> float:
        return self.scale

    def make_backend(self):
        return SimBackend(self.scale)
