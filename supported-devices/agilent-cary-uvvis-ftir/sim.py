"""Simulated twin of the Cary file route: a fake instrument PC that picks up request files and exports CSV spectra."""
from __future__ import annotations

import importlib.util
import json
import math
import os
import pathlib
import random
import sys
import time

_spec = importlib.util.spec_from_file_location(__name__ + "_real", pathlib.Path(__file__).with_name("driver.py"))
real = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = real
_spec.loader.exec_module(real)

SCAN_NM_PER_S = 10.0           # Cary 60 medium scan rate, roughly; plus overheads below
UVVIS_OVERHEAD_S = 20.0
FTIR_S = 45.0                  # 16 co-added scans at 4 /cm with MicroLab's background


def _uvvis(x: float) -> float:
    return 0.8 * math.exp(-((x - 280.0) / 12.0) ** 2) + 1.4 * math.exp(-((x - 225.0) / 10.0) ** 2) + 0.003


def _ftir(x: float) -> float:
    peaks = ((1650.0, 25.0, 0.6), (1540.0, 20.0, 0.4), (3300.0, 120.0, 0.35), (2930.0, 30.0, 0.12))
    return sum(a * math.exp(-((x - c) / w) ** 2) for c, w, a in peaks) + 0.002


class SimBackend(real.CaryBackend):
    """Same folders, same files; the 'helper' is this class: a request becomes an export after a scaled scan time."""

    def __init__(self, cfg: dict, scale: float):
        super().__init__(cfg)
        self.scale = scale
        self.folders_ok = True
        self.hold = False                                  # True: nobody at the PC picks requests up
        self.due: dict[str, float] = {}

    def open(self) -> None:
        if not self.folders_ok:
            raise real.DeviceFault("simulated: the share with the request folders is unreachable",
                                   {"transient": True, "recovery": "retry_after"})
        for key in ("import_dir", "results_dir"):
            pathlib.Path(self.cfg[key]).mkdir(parents=True, exist_ok=True)
        super().open()

    def write_request(self, token: str, params: dict) -> str:
        path = super().write_request(token, params)
        if params["mode"] == "uvvis":
            t = UVVIS_OVERHEAD_S + abs(params["stop"] - params["start"]) / SCAN_NM_PER_S * (2 if params["baseline"] else 1)
        else:
            t = FTIR_S * (2 if params["baseline"] else 1)
        self.due[token] = time.monotonic() + t * self.scale
        return path

    def poll(self) -> None:
        if self.hold:
            return
        for token, when in list(self.due.items()):
            if time.monotonic() < when:
                continue
            req_path = pathlib.Path(self.cfg["import_dir"]) / f"{token}{self.REQUEST_EXT}"
            if not req_path.is_file():                        # withdrawn by estop: the helper never saw it
                del self.due[token]
                continue
            try:
                req = json.loads(req_path.read_text(encoding="utf-8"))
                self._export(token, req)
                req_path.unlink()
            except OSError:                               # withdrawn while being read
                del self.due[token]
                continue
            adl = req_path.with_suffix(".adl")
            if adl.is_file():
                adl.unlink()
            del self.due[token]

    def _export(self, token: str, req: dict) -> None:
        mode, start, stop, step = req["mode"], float(req["start"]), float(req["stop"]), float(req["step"])
        lo, hi = sorted((start, stop))
        n = int(round((hi - lo) / step)) + 1
        xs = [hi - i * step for i in range(n)] if mode == "ftir" else [lo + i * step for i in range(n)]
        f = _uvvis if mode == "uvvis" else _ftir
        lines = [f"{req['sample_name']} ({token})", f"{real.X_LABEL[mode]},Abs"]
        lines += [f"{x:.2f},{f(x) + random.gauss(0, 0.0008):.5f}" for x in xs]
        out = pathlib.Path(self.cfg["results_dir"]) / f"{token}.csv"
        tmp = out.with_suffix(".tmp")
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        tmp.replace(out)
        self.log.append(f"export {out.name} ({n} points)")


class Sim(real.Device):
    def setup(self) -> None:
        super().setup()
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        home = pathlib.Path(os.environ.get("OPENMHP_HOME", pathlib.Path.home() / ".openmhp"))
        root = home / "sim-data" / "agilent-cary-uvvis-ftir"
        self.cfg = {"import_dir": str(root / "requests"), "results_dir": str(root / "results"),
                    "software": "SIM Cary WinUV / MicroLab", "write_adl": True, "result_wait_s": 900, "poll_s": 5}

    def time_scale(self) -> float:
        return self.scale

    def make_backend(self):
        return SimBackend(self.cfg, self.scale)
