"""MHP driver for a ProteinSimple Maurice (cIEF and CE-SDS) under Compass for iCE: a file-based route.

Compass for iCE has no public API. The package writes a sample-table CSV (the batch Compass imports) into a
watched folder, a helper or a person imports it and starts the run, Compass exports the peak table as CSV into a
results folder, and this driver waits for the export carrying the job's token and parses it. Every file format
lives in CompassBackend so the simulated twin can replace it.
"""
from __future__ import annotations

import csv
import json
import os
import pathlib
import re
import time

from openmhp.driver import DeviceFault, Driver, InvalidValue, Job, JobCancelled, LimitViolation

HERE = pathlib.Path(__file__).parent
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.\-]{0,63}$")
POSITION_RE = re.compile(r"^[A-H](?:[1-9]|1[0-2])$")                # 96-well plate, A1..H12
METHOD_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.\-]{0,63}$")
POSITION_COLUMNS = ("pI", "Apparent MW (kDa)", "Apparent MW", "MW (kDa)")   # which one appears depends on the method
MAIN_LABELS = ("main", "main peak", "monomer", "intact")


def load_config() -> dict:
    p = HERE / "config.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def _num(v):
    try:
        return float(str(v).strip().replace("%", ""))
    except (TypeError, ValueError):
        return None


def parse_peak_table(text: str, token: str) -> list[dict]:
    """Compass peak-table export (CSV): one row per peak with the sample name, a position column (pI for cIEF,
    apparent MW for CE-SDS), Area and % Area. Column names are matched loosely; see references/file_formats.md."""
    dialect = "excel-tab" if text.count("\t") > text.count(",") else "excel"
    rows = list(csv.DictReader(text.splitlines(), dialect=dialect))
    if not rows:
        raise DeviceFault("the exported peak table has no rows", {"transient": False, "recovery": "operator"})
    cols = {c.strip().lower(): c for c in rows[0].keys() if c}
    def col(*names):
        for n in names:
            if n.lower() in cols:
                return cols[n.lower()]
        return None
    c_sample = col("Sample Name", "Sample", "Name")
    c_pos = col(*POSITION_COLUMNS)
    c_area = col("Area", "Peak Area", "Corrected Area")
    c_pct = col("% Area", "%Area", "Area %", "Percent Area", "% Corrected Area")
    c_label = col("Peak Name", "Label", "Name", "Peak")
    if not (c_pos and c_area and c_pct):
        raise DeviceFault(f"peak table columns not recognised: {sorted(rows[0].keys())}",
                          {"transient": False, "recovery": "operator"})
    peaks = []
    for r in rows:
        if c_sample and token not in str(r.get(c_sample, "")):
            continue
        pos, area, pct = _num(r.get(c_pos)), _num(r.get(c_area)), _num(r.get(c_pct))
        if pos is None or area is None or pct is None:
            continue
        label = (r.get(c_label) or "").strip() if c_label and c_label != c_sample else ""
        peaks.append({"label": label or None, "position": round(pos, 3), "area": round(area, 1), "area_pct": round(pct, 2)})
    return peaks


def main_peak_pct(peaks: list[dict]):
    labelled = [p for p in peaks if p["label"] and p["label"].strip().lower() in MAIN_LABELS]
    if labelled:
        return labelled[0]["area_pct"]
    return max((p["area_pct"] for p in peaks), default=None)


class CompassBackend:
    """The only class that touches Compass for iCE's folders."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.log: list[str] = []

    def _dir(self, key: str) -> pathlib.Path:
        d = self.cfg.get(key)
        if not d:
            raise DeviceFault(f"config.json has no {key} (copy config.example.json and fill it in)")
        return pathlib.Path(d)

    def open(self) -> None:
        for key in ("import_dir", "results_dir"):
            p = self._dir(key)
            if not p.is_dir():
                raise DeviceFault(f"{key} {p} is not a folder on this machine", {"transient": True, "recovery": "operator"})
            if not os.access(p, os.W_OK):
                raise DeviceFault(f"{key} {p} is not writable", {"transient": True, "recovery": "operator"})

    def pending(self) -> list[pathlib.Path]:
        return sorted(self._dir("import_dir").glob("mhp_*.csv"))

    def queue_depth(self) -> int:
        return len(self.pending())

    def cartridge_present(self):
        """Compass exports no instrument status. A lab that writes one (status.json with {"cartridge": true})
        beside the results gets it reported; otherwise null."""
        p = self._dir("results_dir") / "status.json"
        if not p.is_file():
            return None
        try:
            v = json.loads(p.read_text(encoding="utf-8")).get("cartridge")
        except (OSError, ValueError):
            return None
        return bool(v) if v is not None else None

    def write_batch(self, token: str, params: dict) -> str:
        """The sample table Compass imports: Sample, Position, Method, Injection (one row per replicate)."""
        folder = self._dir("import_dir")
        tmp = folder / f"{token}.part"
        with tmp.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Sample", "Position", "Method", "Injection"])
            for i in range(int(params["replicates"])):
                w.writerow([f"{params['sample_name']} {token}", params["position"], params["method"], i + 1])
        final = folder / f"{token}.csv"
        tmp.replace(final)
        self.log.append(f"batch {final.name}")
        return str(final)

    def find_result(self, token: str) -> pathlib.Path | None:
        hits = sorted(self._dir("results_dir").glob(f"*{token}*.csv"))
        return hits[0] if hits else None

    def read_result(self, path: pathlib.Path, token: str) -> list[dict]:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            raise DeviceFault(f"cannot read {path.name}: {e}", {"transient": True, "recovery": "retry_after"}) from None
        return parse_peak_table(text, token)

    def withdraw(self, token: str | None = None) -> list[str]:
        gone = []
        for p in self.pending():
            if token is None or p.stem == token:
                try:
                    p.unlink(); gone.append(p.name)
                except OSError:
                    pass
        self.log.append(f"withdraw {gone}")
        return gone

    def poll(self) -> None:
        """Once per wait cycle; nothing to do on the real folders (the twin writes results here)."""


class Device(Driver):
    def setup(self) -> None:
        self.cfg = load_config()
        self.hw = None
        self.last_result = None
        self.withdrawn: set[str] = set()              # request tokens an e-stop took back

    def make_backend(self):
        return CompassBackend(self.cfg)

    def time_scale(self) -> float:
        return 1.0

    def _hw(self):
        if self.hw is None:
            hw = self.make_backend()
            try:
                hw.open()
            except DeviceFault:
                raise
            except Exception as e:                           # noqa: BLE001
                raise DeviceFault(f"cannot reach the watched folders: {type(e).__name__}: {e}") from None
            self.hw = hw
        return self.hw

    def on_read(self, name: str):
        if name == "connected":
            try:
                self._hw().open()
                return True
            except DeviceFault:
                return False
        if name == "queue_depth":
            return self._hw().queue_depth()
        if name == "cartridge_present":
            return self._hw().cartridge_present()
        if name == "last_result":
            return self.last_result
        raise InvalidValue(f"unknown signal {name}")

    def validate_params(self, action: str, params: dict) -> None:
        if action != "queue_run":
            return
        if not isinstance(params.get("sample_name"), str) or not NAME_RE.match(params["sample_name"]):
            raise InvalidValue("queue_run.sample_name must be 1-64 characters: letters, digits, space, '_', '.', '-'")
        if not isinstance(params.get("position"), str) or not POSITION_RE.match(params["position"]):
            raise InvalidValue("queue_run.position must be a 96-well position A1..H12 (no leading zero)")
        if not isinstance(params.get("method"), str) or not METHOD_RE.match(params["method"]):
            raise InvalidValue("queue_run.method must be the Compass method name (letters, digits, space, '_', '.', '-')")
        allowed = self.cfg.get("allowed_methods") or []
        if allowed and params["method"] not in allowed:
            raise InvalidValue(f"queue_run.method {params['method']!r} is not in allowed_methods", {"allowed": allowed})
        n = params.get("replicates")
        if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= 3:
            raise LimitViolation(f"queue_run.replicates={n!r} outside 1..3", {"min": 1, "max": 3})

    def on_invoke(self, job: Job):
        if job.action != "queue_run":
            raise InvalidValue(f"unhandled action {job.action}")
        hw = self._hw()
        p = job.params
        token = f"mhp_{job.id}"
        started = time.time()
        req = hw.write_batch(token, p)
        self.emit_signal("queue_depth", hw.queue_depth())
        poll = float(self.cfg.get("poll_s", 15)) * self.time_scale()
        limit = float(self.cfg.get("result_wait_s", 7200)) * self.time_scale()
        t0 = time.monotonic()
        try:
            while True:
                self.checkpoint(job, min(0.9, (time.monotonic() - t0) / limit), phase="waiting for Compass export")
                hw.poll()
                path = hw.find_result(token)
                if path is not None:
                    break
                if token in self.withdrawn:
                    raise DeviceFault(f"request {token} was withdrawn by an emergency stop before anyone acted on it",
                                      {"transient": False, "recovery": "operator"})
                if time.monotonic() - t0 > limit:
                    raise DeviceFault(f"no peak-table export named *{token}*.csv appeared within "
                                      f"{self.cfg.get('result_wait_s', 7200)} s; the batch file {pathlib.Path(req).name} "
                                      f"is left in import_dir for a person to see",
                                      {"transient": True, "recovery": "retry_after", "request": req})
                time.sleep(poll)
        except JobCancelled:
            hw.withdraw(token)                            # not yet taken: nothing runs; taken: it finishes in the vendor software
            raise
        time.sleep(min(poll, 1.0))
        peaks = hw.read_result(path, token)
        result = {"sample_name": p["sample_name"], "method": p["method"], "file": str(path), "peaks": peaks,
                  "main_peak_pct": main_peak_pct(peaks),
                  "duration_s": round((time.time() - started) / self.time_scale(), 1)}
        self.last_result = result
        self.emit_signal("last_result", result)
        self.emit_signal("queue_depth", hw.queue_depth())
        return result

    def on_estop(self) -> None:
        """Compass stops the instrument; the package can only withdraw batches not yet imported."""
        if self.hw is not None:
            self.withdrawn.update(pathlib.Path(n).stem for n in self.hw.withdraw())

    @classmethod
    def probe(cls, cfg: dict) -> str:
        hw = CompassBackend(cfg)
        hw.open()
        return (f"batch folder {cfg.get('import_dir')} and results folder {cfg.get('results_dir')} are writable; "
                f"{hw.queue_depth()} batch file(s) waiting")
