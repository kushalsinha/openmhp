"""MHP driver for an Arbin LBT / BT-2000 cycler under MITS Pro: a file-based route (TEMPLATE).

Arbin's MITS Pro console and its SDK are under NDA, so nothing here talks to the cycler. The package
writes a request file (mhp_<job>.json: channel, test name carrying the job token, the schedule file
to run and the intended steps) into a watched folder; a person, or the lab's own helper, starts the
test in MITS Pro (Start Channel(s) dialog) with that schedule and test name; MITS Pro or its export
tool writes the results as CSV into the results folder, where the driver finds the file carrying the
token and parses the documented columns (Test_Time(s), Step_Index, Cycle_Index, Current(A),
Voltage(V), Charge_Capacity(Ah), Discharge_Capacity(Ah)). Every file format lives in ArbinBackend so
the twin can replace it. Members whose format is this package's own are marked `# template`.
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
CHANNEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-]{0,15}$")
SCHEDULE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.\-()]{0,79}\.sdu$", re.I)
MODES = ("cc_charge", "cc_discharge", "cv_charge", "rest")
COLUMNS = {"time": ("Test_Time(s)",), "step": ("Step_Index",), "cycle": ("Cycle_Index",),
           "current": ("Current(A)",), "voltage": ("Voltage(V)",),
           "qc": ("Charge_Capacity(Ah)",), "qd": ("Discharge_Capacity(Ah)",)}


def load_config() -> dict:
    p = HERE / "config.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def _num(v):
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def parse_results(text: str) -> dict:
    """Summary of a MITS Pro CSV export: the header is the first line holding 'Test_Time'; columns are
    matched by their documented names. Capacities are cumulative within a step, so the last discharge
    capacity is the largest Discharge_Capacity(Ah) seen in the last cycle's discharge rows."""
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if "Test_Time" in l), None)
    if start is None:
        raise DeviceFault("results export has no 'Test_Time(s)' column header", {"transient": False, "recovery": "operator"})
    body = lines[start:]
    dialect = "excel-tab" if body[0].count("\t") > body[0].count(",") else "excel"
    rows = list(csv.DictReader(body, dialect=dialect))
    if not rows:
        raise DeviceFault("results export has a header but no data rows", {"transient": True, "recovery": "retry_after"})
    cols = {c.strip(): c for c in rows[0].keys() if c}
    def col(key):
        for n in COLUMNS[key]:
            if n in cols:
                return cols[n]
        return None
    c = {k: col(k) for k in COLUMNS}
    missing = [k for k in ("time", "cycle", "voltage", "current") if c[k] is None]
    if missing:
        raise DeviceFault(f"results columns not recognised, missing {missing}: {sorted(cols)}", {"transient": False, "recovery": "operator"})
    last = rows[-1]
    cycles = max(int(_num(r.get(c["cycle"])) or 0) for r in rows)
    last_cycle_rows = [r for r in rows if int(_num(r.get(c["cycle"])) or 0) == cycles]
    qd = [(_num(r.get(c["qd"])) or 0.0) for r in last_cycle_rows if c["qd"]] if c["qd"] else []
    qc = [(_num(r.get(c["qc"])) or 0.0) for r in last_cycle_rows if c["qc"]] if c["qc"] else []
    last_q = max(qd) if qd and max(qd) > 0 else (max(qc) if qc else None)
    return {"points": len(rows), "cycles_completed": cycles, "last_capacity_ah": None if last_q is None else round(last_q, 6),
            "final_voltage_v": _num(last.get(c["voltage"])), "test_time_s": _num(last.get(c["time"])) or 0.0}


class ArbinBackend:
    """The only class that touches the MITS Pro folders."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.log: list[str] = []

    def _dir(self, key: str) -> pathlib.Path:
        d = self.cfg.get(key)
        if not d:
            raise DeviceFault(f"config.json has no {key} (copy config.example.json and fill it in)")
        return pathlib.Path(d)

    def open(self) -> None:
        for key in ("request_dir", "results_dir"):
            p = self._dir(key)
            if not p.is_dir():
                raise DeviceFault(f"{key} {p} is not a folder on this machine", {"transient": True, "recovery": "operator"})
            if not os.access(p, os.W_OK):
                raise DeviceFault(f"{key} {p} is not writable", {"transient": True, "recovery": "operator"})

    def pending(self) -> list[pathlib.Path]:
        return sorted(self._dir("request_dir").glob("mhp_*.json"))

    def queue_depth(self) -> int:
        return len(self.pending())

    def channel_state(self, channel: str) -> str:
        """What the folders say: queued while a request for this channel waits; the cycler's own state is not exported."""
        for p in self.pending():
            try:
                if json.loads(p.read_text(encoding="utf-8")).get("channel") == channel:
                    return "queued"
            except (OSError, ValueError):
                continue
        return "unknown"

    def write_request(self, token: str, params: dict) -> str:                       # template
        folder = self._dir("request_dir")
        req = {"token": token, "channel": params["channel"], "test_name": f"{params['barcode']}_{token}",
               "barcode": params["barcode"], "schedule": params["schedule"], "steps": params["steps"],
               "cycles": int(params["cycles"]), "export": f"{params['barcode']}_{token}.csv", "written": time.time()}
        tmp = folder / f"{token}.part"
        tmp.write_text(json.dumps(req, indent=1), encoding="utf-8")
        final = folder / f"{token}.json"
        tmp.replace(final)
        self.log.append(f"request {final.name}")
        return str(final)

    def find_result(self, token: str) -> pathlib.Path | None:
        hits = sorted(p for p in self._dir("results_dir").glob(f"*{token}*") if p.suffix.lower() in (".csv", ".txt"))
        return hits[0] if hits else None

    def read_result(self, path: pathlib.Path) -> dict:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            raise DeviceFault(f"cannot read {path.name}: {e}", {"transient": True, "recovery": "retry_after"}) from None
        return parse_results(text)

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
        self.channel = str(self.cfg.get("default_channel", "1"))
        self.last_result = None
        self.withdrawn: set[str] = set()

    def make_backend(self):
        return ArbinBackend(self.cfg)

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
                raise DeviceFault(f"cannot reach the MITS Pro folders: {type(e).__name__}: {e}") from None
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
        if name == "channel":
            return self.channel
        if name == "channel_state":
            return self._hw().channel_state(self.channel)
        if name == "last_result":
            return self.last_result
        raise InvalidValue(f"unknown signal {name}")

    def on_write(self, name: str, value):
        if name != "channel":
            raise InvalidValue(f"unknown setting {name}")
        if not CHANNEL_RE.match(str(value)):
            raise InvalidValue("channel must be the MITS Pro channel name: digits and dashes, e.g. '3' or '1-2-3'")
        self.channel = str(value)
        return None

    def validate_params(self, action: str, params: dict) -> None:
        if action != "start_protocol":
            return
        if not isinstance(params.get("channel"), str) or not CHANNEL_RE.match(params["channel"]):
            raise InvalidValue("start_protocol.channel must be the MITS Pro channel name: digits and dashes, e.g. '3'")
        if not isinstance(params.get("barcode"), str) or not NAME_RE.match(params["barcode"]):
            raise InvalidValue("start_protocol.barcode must be 1-64 characters: letters, digits, space, '_', '.', '-'")
        if not isinstance(params.get("schedule"), str) or not SCHEDULE_RE.match(params["schedule"]):
            raise InvalidValue("start_protocol.schedule must be a schedule file name in the MITS Pro library ending in .sdu")
        allowed = self.cfg.get("allowed_schedules") or []
        if allowed and params["schedule"] not in allowed:
            raise InvalidValue(f"schedule {params['schedule']!r} is not in allowed_schedules", {"allowed": allowed})
        steps = params.get("steps")
        if not isinstance(steps, list) or not steps:
            raise InvalidValue("start_protocol.steps must be a non-empty list (what the schedule is expected to do)")
        vmax, imax = float(self.cfg.get("voltage_max_v", 5.0)), float(self.cfg.get("current_max_a", 1.0))
        for i, s in enumerate(steps):
            mode, cur, volt, tl, cl = s.get("mode"), s.get("current_a"), s.get("voltage_v"), s.get("time_limit_s"), s.get("capacity_limit_ah")
            where = f"steps[{i}] ({mode})"
            if mode in ("cc_charge", "cc_discharge") and (cur is None or cur <= 0):
                raise InvalidValue(f"{where}: current_a must be a positive current (the sign comes from the mode)")
            if mode == "cv_charge" and (volt is None or cur is None):
                raise InvalidValue(f"{where}: cv_charge needs voltage_v (the hold) and current_a (the cut-off current)")
            if mode == "rest" and tl is None:
                raise InvalidValue(f"{where}: rest needs time_limit_s")
            if mode != "rest" and volt is None and tl is None and cl is None:
                raise InvalidValue(f"{where}: needs an end condition: voltage_v, time_limit_s or capacity_limit_ah")
            if volt is not None and volt > vmax:
                raise LimitViolation(f"{where}: voltage_v {volt} exceeds voltage_max_v {vmax} from config.json", {"max": vmax})
            if cur is not None and cur > imax:
                raise LimitViolation(f"{where}: current_a {cur} exceeds current_max_a {imax} from config.json", {"max": imax})

    def on_invoke(self, job: Job):
        if job.action != "start_protocol":
            raise InvalidValue(f"unhandled action {job.action}")
        hw = self._hw()
        p = job.params
        token = f"mhp_{job.id}"
        started = time.time()
        req = hw.write_request(token, p)
        self.emit_signal("queue_depth", hw.queue_depth())
        poll = float(self.cfg.get("poll_s", 60)) * self.time_scale()
        limit = float(self.cfg.get("result_wait_s", 1209600)) * self.time_scale()
        t0 = time.monotonic()
        try:
            while True:
                self.checkpoint(job, min(0.9, (time.monotonic() - t0) / limit), phase="waiting for the results export")
                hw.poll()
                path = hw.find_result(token)
                if path is not None:
                    break
                if token in self.withdrawn:
                    raise DeviceFault(f"request {token} was withdrawn by an emergency stop before anyone started it",
                                      {"transient": False, "recovery": "operator"})
                if time.monotonic() - t0 > limit:
                    raise DeviceFault(f"no results export named *{token}* appeared within {self.cfg.get('result_wait_s', 1209600)} s; "
                                      f"the request {pathlib.Path(req).name} is left in request_dir for a person to see",
                                      {"transient": True, "recovery": "retry_after", "request": req})
                time.sleep(poll)
        except JobCancelled:
            hw.withdraw(token)                            # not started: nothing runs; started: it finishes in MITS Pro
            raise
        time.sleep(min(poll, 1.0))
        summary = hw.read_result(path)
        result = {"channel": p["channel"], "barcode": p["barcode"], "schedule": p["schedule"], "file": str(path),
                  "points": summary["points"], "cycles_completed": summary["cycles_completed"],
                  "last_capacity_ah": summary["last_capacity_ah"], "final_voltage_v": summary["final_voltage_v"],
                  "test_time_s": round(summary["test_time_s"], 1), "duration_s": round((time.time() - started) / self.time_scale(), 1)}
        self.last_result = result
        self.emit_signal("last_result", result)
        return result

    def on_estop(self) -> None:
        """MITS Pro's own Stop (console) stops a channel; the package withdraws every queued request."""
        if self.hw is not None:
            self.withdrawn.update(pathlib.Path(n).stem for n in self.hw.withdraw())

    @classmethod
    def probe(cls, cfg: dict) -> str:
        hw = ArbinBackend(cfg)
        hw.open()
        return (f"request folder {cfg.get('request_dir')} and results folder {cfg.get('results_dir')} are writable; "
                f"{hw.queue_depth()} request(s) waiting")
