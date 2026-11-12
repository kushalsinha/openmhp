"""Simulated twin of the ICON-NMR route: a fake ICON-NMR that reads the job file after a moment, then writes
the dataset folder (acqus, pdata/1/title, a placeholder 1r) once the scaled acquisition time has passed."""
from __future__ import annotations

import importlib.util
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

SOLVENT_PPM = {"CDCl3": 7.26, "DMSO": 2.50, "D2O": 4.79, "MeOD": 3.31, "C6D6": 7.16, "Acetone": 2.05,
               "CD3CN": 1.94, "CD2Cl2": 5.32, "THF": 3.58, "Tol": 2.08, "Pyr": 8.74, "TFE": 3.88}


class SimBackend(real.IconNMRBackend):
    def __init__(self, cfg, scale):
        super().__init__(cfg)
        self.scale = scale
        self.jobs: dict[str, dict] = {}            # token -> {dataset, expno, params, read_at, done_at}

    def write_job(self, token, dataset, expno, p):
        path = super().write_job(token, dataset, expno, p)
        per_scan, default_ns = real.EXPERIMENT_TIME.get(p["experiment"], (4.0, 16))
        ns = p.get("ns") or default_ns
        d1 = p.get("d1_s") if p.get("d1_s") is not None else 1.0
        now = time.monotonic()
        self.jobs[token] = {"dataset": dataset, "expno": expno, "p": p, "ns": ns, "d1": d1, "path": path,
                            "read_at": now + 2 * self.scale,
                            "done_at": now + (float(self.cfg.get("lock_shim_s", 180)) + ns * (per_scan + d1)) * self.scale}
        return path

    def _tick(self):
        now = time.monotonic()
        for token, j in list(self.jobs.items()):
            if now >= j["read_at"] and j["path"].exists():
                j["path"].unlink()                                   # ICON-NMR has read the job
            if now >= j["done_at"]:
                self._write_dataset(j)
                self.jobs.pop(token)

    def picked_up(self, token):
        self._tick()
        return super().picked_up(token)

    def result_ready(self, dataset, expno):
        self._tick()
        return super().result_ready(dataset, expno)

    def _write_dataset(self, j):
        p, d = j["p"], self.dataset_dir(j["dataset"], j["expno"])
        (d / "pdata" / "1").mkdir(parents=True, exist_ok=True)
        td = 65536 if p["experiment"] in ("PROTON", "F19") else 32768
        sw, o1 = (20.0, 2470.0) if p["experiment"] in ("PROTON", "HSQC", "COSY", "HMBC") else (240.0, 15000.0)
        lines = ["##TITLE= Parameter file, TopSpin 4.1", "##JCAMPDX= 5.0", "##DATATYPE= Parameter Values",
                 "##ORIGIN= Bruker BioSpin GmbH", "##OWNER= " + self.cfg["user"],
                 f"##$NS= {j['ns']}", f"##$DS= 2", f"##$TD= {td}", f"##$SW= {sw:.4f}", f"##$O1= {o1:.2f}",
                 f"##$D= (0..63)", f"0 {j['d1']:g} 0.003 0 0", f"##$SOLVENT= <{p['solvent']}>",
                 f"##$PULPROG= <zg30>", f"##$EXP= <{p['experiment']}>", "##$SFO1= 400.1324710",
                 "##END="]
        (d / "acqus").write_text("\n".join(lines) + "\n", encoding="utf-8")
        (d / "pdata" / "1" / "title").write_text((p.get("title") or j["dataset"]) + "\n", encoding="utf-8")
        # a placeholder processed spectrum: 1r is binary int32 in TopSpin; the twin writes a short text note
        ppm = SOLVENT_PPM.get(p["solvent"], 0.0)
        (d / "pdata" / "1" / "1r").write_bytes(
            f"simulated 1r placeholder; residual solvent at {ppm} ppm; noise seed {random.randint(0, 9999)}\n".encode())
        (d / "pdata" / "1" / "procs").write_text("##$SI= 32768\n##$LB= 0.3\n##END=\n", encoding="utf-8")
        self.log.append(f"dataset {j['dataset']}/{j['expno']} written")


class SimBrukerIconNMR(real.BrukerIconNMR):
    def setup(self) -> None:
        super().setup()
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        base = os.environ.get("OPENMHP_HOME") or tempfile.gettempdir()
        pathlib.Path(base).mkdir(parents=True, exist_ok=True)
        root = pathlib.Path(tempfile.mkdtemp(prefix="bruker-nmr-iconnmr-", dir=base))
        (root / "import").mkdir()
        (root / "data").mkdir()
        self.cfg = {"import_dir": str(root / "import"), "data_dir": str(root / "data"), "user": "sim",
                    "holders": 60, "allowed_experiments": [], "lock_shim_s": 180, "poll_s": 10, "result_wait_s": 7200}

    def time_scale(self) -> float:
        return self.scale

    def make_backend(self):
        return SimBackend(self.cfg, self.scale)
