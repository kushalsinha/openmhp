"""MHP driver for a Bruker Avance NMR under TopSpin with ICON-NMR automation (file-based route).

The package writes one job file per experiment into the folder ICON-NMR's automation import
reads, then waits for the dataset to appear under the TopSpin data directory
(<data_dir>/<dataset>/<expno>/pdata/1/1r with acqus beside it) and reads the acquisition
parameters back. ICON-NMR, not this package, moves the sample changer, locks, shims and acquires.
Formats and what is unverified: references/iconnmr_files.md.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import time

from openmhp.driver import DeviceFault, Driver, InvalidValue, Job, LimitViolation

HERE = pathlib.Path(__file__).parent
JOB_COLUMNS = ["USER", "NAME", "HOLDER", "EXPNO", "SOLVENT", "EXPERIMENT", "TITLE"]     # unverified header words
PARAM_COLUMNS = {"ns": "NS", "d1_s": "D1"}
ACQUS_KEYS = {"NS": int, "SW": float, "O1": float, "TD": int}
# rough per-scan time (s) and lock/shim overhead used only to size the result wait and the twin's clock
EXPERIMENT_TIME = {"PROTON": (4.0, 16), "C13CPD": (3.0, 1024), "HSQC": (1.2 * 256, 2), "COSY": (1.2 * 128, 2),
                   "HMBC": (1.3 * 256, 4), "DEPT135": (3.0, 256), "F19": (2.5, 32), "P31CPD": (3.0, 128)}
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_ACQUS = re.compile(r"^##\$(\w+)=\s*(.+?)\s*$")


def load_config() -> dict:
    p = HERE / "config.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def parse_acqus(text: str) -> dict:
    """The JCAMP-like `##$KEY= value` lines of a TopSpin acqus file, as {KEY: str}."""
    out = {}
    for line in text.splitlines():
        m = _ACQUS.match(line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


class IconNMRBackend:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.log: list[str] = []
        self.pending: dict[str, pathlib.Path] = {}       # token -> job file written by this package

    def _dir(self, key: str) -> pathlib.Path:
        d = self.cfg.get(key)
        if not d:
            raise DeviceFault(f"config.json is missing {key} (copy config.example.json and fill it in)",
                              {"transient": False, "recovery": "operator"})
        return pathlib.Path(d)

    def open(self) -> None:
        for key in ("import_dir", "data_dir"):
            d = self._dir(key)
            if not d.is_dir():
                raise DeviceFault(f"{key} {d} does not exist", {"transient": True, "recovery": "operator"})
        if not os.access(self._dir("import_dir"), os.W_OK):
            raise DeviceFault(f"import_dir {self._dir('import_dir')} is not writable",
                              {"transient": True, "recovery": "operator"})
        if not self.cfg.get("user"):
            raise DeviceFault("config.json is missing user (the ICON-NMR user the jobs run as)",
                              {"transient": False, "recovery": "operator"})

    # ---- the job file ------------------------------------------------------------------- #
    def write_job(self, token: str, dataset: str, expno: int, p: dict) -> pathlib.Path:
        cols = list(JOB_COLUMNS)
        row = [self.cfg["user"], dataset, str(p["holder"]), str(expno), p["solvent"], p["experiment"],
               p.get("title") or dataset]
        for key, col in PARAM_COLUMNS.items():
            if p.get(key) is not None:
                cols.append(col)
                row.append(f"{p[key]:g}" if isinstance(p[key], float) else str(p[key]))
        text = "\t".join(cols) + "\r\n" + "\t".join(row) + "\r\n"
        path = self._dir("import_dir") / f"{token}.txt"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
        self.pending[token] = path
        self.log.append(f"wrote job {path.name}: {dataset}/{expno} holder {p['holder']} {p['experiment']}")
        return path

    def queue_depth(self) -> int:
        try:
            return sum(1 for f in self._dir("import_dir").glob("*.txt") if f.is_file())
        except DeviceFault:
            return 0

    def picked_up(self, token: str) -> bool:
        """ICON-NMR removes (or renames) the job file once it has read it."""
        p = self.pending.get(token)
        return p is not None and not p.exists()

    # ---- the result --------------------------------------------------------------------- #
    def dataset_dir(self, dataset: str, expno: int) -> pathlib.Path:
        return self._dir("data_dir") / dataset / str(expno)

    def next_expno(self, dataset: str) -> int:
        d = self._dir("data_dir") / dataset
        used = [int(x.name) for x in d.iterdir() if x.is_dir() and x.name.isdigit()] if d.is_dir() else []
        return max(used, default=0) + 1

    def result_ready(self, dataset: str, expno: int) -> bool:
        d = self.dataset_dir(dataset, expno)
        return (d / "acqus").is_file() and (d / "pdata" / "1" / "1r").is_file()

    def parse(self, dataset: str, expno: int) -> dict:
        d = self.dataset_dir(dataset, expno)
        acqus = parse_acqus((d / "acqus").read_text(encoding="utf-8", errors="replace"))
        subset = {}
        for key, typ in ACQUS_KEYS.items():
            try:
                subset[key] = typ(float(acqus[key])) if typ is int else typ(acqus[key])
            except (KeyError, ValueError):
                raise DeviceFault(f"acqus of {dataset}/{expno} has no usable ##${key}=",
                                  {"transient": False, "recovery": "operator"}) from None
        files = sorted(str(f.relative_to(d.parent.parent)).replace(os.sep, "/")
                       for f in d.rglob("*") if f.is_file())
        return {"acqus": subset, "files": files}

    def abort(self) -> list[str]:
        """Remove job files of ours that ICON-NMR has not read yet; nothing else can be stopped from here."""
        removed = []
        for token, p in list(self.pending.items()):
            if p.exists():
                try:
                    p.unlink()
                    removed.append(p.name)
                except OSError:
                    pass
            self.pending.pop(token, None)
        self.log.append(f"estop: removed {len(removed)} queued job file(s): {removed}")
        return removed


class BrukerIconNMR(Driver):
    def setup(self) -> None:
        self.cfg = load_config()
        self.hw = None
        self.last_result = None
        self.current_holder: int | None = None
        self.stopped = False

    def make_backend(self):
        return IconNMRBackend(self.cfg)

    def time_scale(self) -> float:
        return 1.0

    def _hw(self) -> IconNMRBackend:
        if self.hw is None:
            hw = self.make_backend()
            hw.open()
            self.hw = hw
        return self.hw

    def on_read(self, name: str):
        if name == "connected":
            try:
                self._hw()
                return True
            except DeviceFault:
                return False
        if name == "queue_depth":
            return self._hw().queue_depth()
        if name == "sample_changer_position":
            return self.current_holder
        if name == "last_result":
            return self.last_result
        raise InvalidValue(f"unknown signal {name}")

    def validate_params(self, action: str, params: dict) -> None:
        if action != "queue_experiment":
            return
        exp = params.get("experiment")
        allowed = self.cfg.get("allowed_experiments") or []
        if not isinstance(exp, str) or not _NAME.match(exp):
            raise InvalidValue("experiment must be a TopSpin parameter set name (letters, digits, '_', '-', '.')")
        if allowed and exp not in allowed:
            raise InvalidValue(f"experiment {exp!r} is not in allowed_experiments {allowed}")
        max_holder = int(self.cfg.get("holders", 60))
        if not 1 <= int(params["holder"]) <= max_holder:
            raise LimitViolation(f"holder {params['holder']} is outside 1..{max_holder} (holders in config.json)",
                                 {"min": 1, "max": max_holder})
        ds = params.get("dataset")
        if ds is not None and not _NAME.match(ds):
            raise InvalidValue("dataset must be a TopSpin dataset name without spaces or special characters")
        title = params.get("title") or ""
        if "\t" in title or "\n" in title or "\r" in title:
            raise InvalidValue("title may not contain tabs or line breaks")

    def _expected_s(self, p: dict) -> float:
        per_scan, default_ns = EXPERIMENT_TIME.get(p["experiment"], (4.0, 16))
        ns = p.get("ns") or default_ns
        d1 = p.get("d1_s") if p.get("d1_s") is not None else 1.0
        return float(self.cfg.get("lock_shim_s", 180)) + ns * (per_scan + d1)

    def on_invoke(self, job: Job):
        if job.action != "queue_experiment":
            raise InvalidValue(f"unhandled action {job.action}")
        hw = self._hw()
        p = job.params
        self.stopped = False
        token = f"mhp_{time.strftime('%Y%m%d')}_{job.id.replace('job_', '')}"
        dataset = p.get("dataset") or token
        expno = int(p["expno"]) if p.get("expno") is not None else hw.next_expno(dataset)
        if hw.dataset_dir(dataset, expno).exists():
            raise InvalidValue(f"{dataset}/{expno} already exists; pick another expno or dataset")
        started = time.time()
        hw.write_job(token, dataset, expno, p)
        self.checkpoint(job, 0.05, phase="queued for ICON-NMR")
        poll = float(self.cfg.get("poll_s", 10)) * self.time_scale()
        wait = float(self.cfg.get("result_wait_s", 2 * self._expected_s(p) + 1800)) * self.time_scale()
        expected = self._expected_s(p) * self.time_scale()
        t0 = time.monotonic()
        try:
            while not hw.result_ready(dataset, expno):
                if self.stopped:
                    raise DeviceFault("stopped: the queued job file was removed; if ICON-NMR had already read it, "
                                      "stop the run in ICON-NMR", {"transient": False, "recovery": "operator"})
                elapsed = time.monotonic() - t0
                if hw.picked_up(token):
                    self.current_holder = int(p["holder"])
                    self.checkpoint(job, min(0.95, 0.1 + 0.85 * elapsed / max(expected, 1e-6)), phase="acquiring")
                else:
                    self.checkpoint(job, 0.05, phase="waiting for ICON-NMR to read the job")
                if elapsed > wait:
                    raise DeviceFault(f"no result for {dataset}/{expno} after {wait / self.time_scale():.0f} s; "
                                      f"the job file {token}.txt is left in {self.cfg.get('import_dir')}",
                                      {"transient": True, "recovery": "retry_after"})
                time.sleep(poll)
        finally:
            self.current_holder = None
            hw.pending.pop(token, None)
        parsed = hw.parse(dataset, expno)
        result = {"dataset": dataset, "expno": expno, "holder": int(p["holder"]), "files": parsed["files"],
                  "acqus": parsed["acqus"], "duration_s": round((time.time() - started) / self.time_scale(), 1)}
        self.last_result = result
        self.emit_signal("last_result", result)
        return result

    def on_estop(self) -> None:
        self.stopped = True
        if self.hw is not None:
            self.hw.abort()

    @classmethod
    def discover(cls, cfg: dict, what: str) -> list:
        if what == "experiments" and cfg.get("allowed_experiments"):
            return list(cfg["allowed_experiments"])
        return []

    @classmethod
    def probe(cls, cfg: dict) -> str:
        hw = IconNMRBackend(cfg)
        hw.open()
        return (f"job files go to {cfg.get('import_dir')}, datasets are read from {cfg.get('data_dir')} "
                f"as user {cfg.get('user')} ({hw.queue_depth()} job file(s) waiting)")
