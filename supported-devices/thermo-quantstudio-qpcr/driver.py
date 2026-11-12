"""MHP driver for an Applied Biosystems QuantStudio 5/7 under QuantStudio Design & Analysis: a file-based route.

The software imports a plate setup file (TXT/CSV: Well, Sample Name, Target Name, Task, Reporter, Quencher) into
a run template (.edt) and exports results per plate (Results table with Cq/CT, Quantity, Amp Status). This package
writes the plate setup file and a request naming the template into a watched folder, a person (or the lab's helper)
starts the run, and the driver waits for the results export carrying the job's token. Every file format lives in
QuantStudioBackend so the simulated twin can replace it.
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
WELL_RE = re.compile(r"^[A-H](?:[1-9]|1[0-2])$")
TASKS = ("UNKNOWN", "STANDARD", "NTC", "POSITIVE")
AMP_STATUS = ("Amp", "No Amp", "Inconclusive", "N/A")
SETUP_COLUMNS = ("Well", "Sample Name", "Target Name", "Task", "Reporter", "Quencher")
CT_COLUMNS = ("CT", "Cq", "Ct")


def load_config() -> dict:
    p = HERE / "config.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def _num(v):
    s = str(v if v is not None else "").strip()
    if s.lower() in ("", "undetermined", "n/a", "nan"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_results(text: str, token: str) -> list[dict]:
    """The Results table of a QuantStudio export (CSV or tab): one row per well and target. Section headers and
    metadata lines before the column header are skipped; the header is the first line that has 'Well'."""
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if re.match(r'^"?Well', l)), None)
    if start is None:
        raise DeviceFault("results export has no 'Well' column header", {"transient": False, "recovery": "operator"})
    body = "\n".join(lines[start:])
    dialect = "excel-tab" if body.count("\t") > body.count(",") else "excel"
    rows = list(csv.DictReader(body.splitlines(), dialect=dialect))
    cols = {c.strip().lower(): c for c in rows[0].keys() if c} if rows else {}
    def col(*names):
        for n in names:
            if n.lower() in cols:
                return cols[n.lower()]
        return None
    c_well, c_sample, c_target = col("Well Position", "Well"), col("Sample Name", "Sample"), col("Target Name", "Target")
    c_ct, c_q, c_amp = col(*CT_COLUMNS), col("Quantity"), col("Amp Status", "Amplification Status")
    if not (c_well and c_sample and c_target and c_ct):
        raise DeviceFault(f"results columns not recognised: {sorted(cols.values())}", {"transient": False, "recovery": "operator"})
    out = []
    for r in rows:
        sample = (r.get(c_sample) or "").strip()
        if not sample or token not in sample:
            continue
        amp = (r.get(c_amp) or "N/A").strip() if c_amp else "N/A"
        out.append({"well": (r.get(c_well) or "").strip(), "sample": sample.replace(f" {token}", ""),
                    "target": (r.get(c_target) or "").strip(), "ct": _num(r.get(c_ct)),
                    "quantity": _num(r.get(c_q)) if c_q else None, "amp_status": amp if amp in AMP_STATUS else amp})
    return out


class QuantStudioBackend:
    """The only class that touches the Design & Analysis folders."""

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
        return sorted(self._dir("import_dir").glob("mhp_*.json"))

    def queue_depth(self) -> int:
        return len(self.pending())

    def run_state(self) -> str:
        """What the folders say: 'queued' while a request waits, else 'idle'. The instrument's own run state
        (and its block temperature) is not exported by Design & Analysis."""
        return "queued" if self.pending() else "idle"

    def write_plate(self, token: str, params: dict) -> str:
        """The plate setup file (tab-separated TXT) plus a JSON request naming the template and the program."""
        folder = self._dir("import_dir")
        setup = folder / f"{token}_plate_setup.txt"
        with setup.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, dialect="excel-tab")
            w.writerow(SETUP_COLUMNS)
            for s in params["plate_setup"]:
                w.writerow([s["well"], f"{s['sample']} {token}", s["target"], s["task"],
                            self.cfg.get("reporter", "FAM"), self.cfg.get("quencher", "NFQ-MGB")])
        req = {"token": token, "plate_id": params["plate_id"], "template": params["template"],
               "plate_setup_file": setup.name, "program": params.get("program"),
               "export": f"{token}_Results.csv", "written": time.time()}
        tmp = folder / f"{token}.part"
        tmp.write_text(json.dumps(req, indent=1), encoding="utf-8")
        final = folder / f"{token}.json"
        tmp.replace(final)
        self.log.append(f"plate {setup.name} + {final.name}")
        return str(final)

    def find_result(self, token: str) -> pathlib.Path | None:
        hits = sorted(p for p in self._dir("results_dir").glob(f"*{token}*") if p.suffix.lower() in (".csv", ".txt"))
        return hits[0] if hits else None

    def read_result(self, path: pathlib.Path, token: str) -> list[dict]:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            raise DeviceFault(f"cannot read {path.name}: {e}", {"transient": True, "recovery": "retry_after"}) from None
        return parse_results(text, token)

    def withdraw(self, token: str | None = None) -> list[str]:
        gone = []
        for p in self.pending():
            if token is None or p.stem == token:
                try:
                    p.unlink(); gone.append(p.name)
                    setup = p.with_name(f"{p.stem}_plate_setup.txt")
                    if setup.is_file():
                        setup.unlink()
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
        return QuantStudioBackend(self.cfg)

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
        if name == "run_state":
            return self._hw().run_state()
        if name == "block_temperature":
            return None                                      # not exported by Design & Analysis
        if name == "last_result":
            return self.last_result
        raise InvalidValue(f"unknown signal {name}")

    def validate_params(self, action: str, params: dict) -> None:
        if action != "queue_run":
            return
        if not isinstance(params.get("plate_id"), str) or not NAME_RE.match(params["plate_id"]):
            raise InvalidValue("queue_run.plate_id must be 1-64 characters: letters, digits, space, '_', '.', '-'")
        if not isinstance(params.get("template"), str) or not re.match(r"^[A-Za-z0-9][A-Za-z0-9 _.\-]{0,63}\.edt$", params["template"]):
            raise InvalidValue("queue_run.template must be the template file name in the software's library, ending in .edt")
        allowed = self.cfg.get("allowed_templates") or []
        if allowed and params["template"] not in allowed:
            raise InvalidValue(f"queue_run.template {params['template']!r} is not in allowed_templates", {"allowed": allowed})
        setup = params.get("plate_setup")
        if not isinstance(setup, list) or not setup:
            raise InvalidValue("queue_run.plate_setup must be a non-empty list of wells")
        max_wells = int(self.cfg.get("wells", 96))
        if len(setup) > max_wells:
            raise LimitViolation(f"plate_setup names {len(setup)} wells; this block has {max_wells}", {"max": max_wells})
        seen = set()
        for i, s in enumerate(setup):
            if not isinstance(s.get("well"), str) or not WELL_RE.match(s["well"]):
                raise InvalidValue(f"plate_setup[{i}].well must be A1..H12 (no leading zero)")
            if s["well"] in seen:
                raise InvalidValue(f"plate_setup[{i}].well {s['well']} is listed twice; one sample per well")
            seen.add(s["well"])
            for k in ("sample", "target"):
                if not isinstance(s.get(k), str) or not NAME_RE.match(s[k]):
                    raise InvalidValue(f"plate_setup[{i}].{k} must be 1-64 characters: letters, digits, space, '_', '.', '-'")
        prog = params.get("program")
        if prog is not None:
            total = sum(int(st["cycles"]) * len(st["steps"]) for st in prog["stages"])
            if total > 600:
                raise LimitViolation(f"program has {total} step executions; keep it under 600", {"max": 600})

    def on_invoke(self, job: Job):
        if job.action != "queue_run":
            raise InvalidValue(f"unhandled action {job.action}")
        hw = self._hw()
        p = job.params
        token = f"mhp_{job.id}"
        started = time.time()
        req = hw.write_plate(token, p)
        self.emit_signal("queue_depth", hw.queue_depth())
        self.emit_signal("run_state", hw.run_state())
        poll = float(self.cfg.get("poll_s", 30)) * self.time_scale()
        limit = float(self.cfg.get("result_wait_s", 14400)) * self.time_scale()
        t0 = time.monotonic()
        try:
            while True:
                self.checkpoint(job, min(0.9, (time.monotonic() - t0) / limit), phase="waiting for results export")
                hw.poll()
                path = hw.find_result(token)
                if path is not None:
                    break
                if token in self.withdrawn:
                    raise DeviceFault(f"request {token} was withdrawn by an emergency stop before anyone acted on it",
                                      {"transient": False, "recovery": "operator"})
                if time.monotonic() - t0 > limit:
                    raise DeviceFault(f"no results export named *{token}* appeared within "
                                      f"{self.cfg.get('result_wait_s', 14400)} s; the request {pathlib.Path(req).name} and "
                                      f"its plate setup file are left in import_dir for a person to see",
                                      {"transient": True, "recovery": "retry_after", "request": req})
                time.sleep(poll)
        except JobCancelled:
            hw.withdraw(token)                            # not yet taken: nothing runs; taken: it finishes in the vendor software
            raise
        time.sleep(min(poll, 1.0))
        rows = hw.read_result(path, token)
        result = {"plate_id": p["plate_id"], "file": str(path), "wells": len({r["well"] for r in rows}),
                  "results": rows, "duration_s": round((time.time() - started) / self.time_scale(), 1)}
        self.last_result = result
        self.emit_signal("last_result", result)
        self.emit_signal("run_state", hw.run_state())
        return result

    def on_estop(self) -> None:
        """The instrument's own Stop (touchscreen or software) stops a run; the package withdraws queued plates."""
        if self.hw is not None:
            self.withdrawn.update(pathlib.Path(n).stem for n in self.hw.withdraw())

    @classmethod
    def probe(cls, cfg: dict) -> str:
        hw = QuantStudioBackend(cfg)
        hw.open()
        return (f"plate folder {cfg.get('import_dir')} and results folder {cfg.get('results_dir')} are writable; "
                f"{hw.queue_depth()} plate request(s) waiting")
