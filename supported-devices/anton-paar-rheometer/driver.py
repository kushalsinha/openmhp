"""MHP driver for an Anton Paar MCR rheometer under RheoCompass (file-based route, Windows PC).

RheoCompass keeps projects and test definitions in its SQL database and publishes no automation interface
(Anton Paar's LIMS route is the separate AP Connect server). The package writes one job file per test into
the folder the lab's RheoCompass workflow reads, waits for the ASCII export and parses it. RheoCompass drives
the head, the temperature device and the measurement; the package touches no hardware. Formats and what is
unverified: references/rheocompass_files.md.
"""
from __future__ import annotations

import csv
import io
import json
import math
import os
import pathlib
import re
import time

from openmhp.driver import DeviceFault, Driver, InvalidValue, Job, LimitViolation

HERE = pathlib.Path(__file__).parent
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_PLAIN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.\-/]{0,31}$")
JOB_COLUMNS = ["job_id", "sample_name", "test_type", "measuring_system", "temperature_c", "shear_rate_start", "shear_rate_end",
               "strain_pct", "frequency_start_hz", "frequency_end_hz", "points", "point_duration_s", "log", "result_file"]
SUMMARY = {"shear_rate": ("shear rate",), "shear_stress_pa": ("shear stress",), "viscosity_pa_s": ("viscosity",),
           "storage_modulus_pa": ("storage modulus",), "loss_modulus_pa": ("loss modulus",), "frequency_hz": ("frequency", "angular frequency")}


def load_config() -> dict:
    p = HERE / "config.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def decode_export(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _cell(s: str):
    s = s.strip()
    if not s or s.lower() in ("n.a.", "nan", "-"):
        return None
    if "," in s and "." not in s:
        s = s.replace(",", ".")
    elif "," in s and "." in s and s.rfind(",") > s.rfind("."):
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def parse_export(text: str) -> dict:
    """RheoCompass ASCII export: tab-separated; `key:<TAB>value` metadata lines; a block starts with
    `Interval and data points:<TAB>n<TAB>count`; the column header line starts with `Interval data:` and the
    column names follow, units either as `Name [unit]` or on the next line in brackets; then the rows.
    First interval only."""
    meta: dict[str, str] = {}
    columns: list[str] = []
    rows: list[list] = []
    in_block = False
    for raw in text.splitlines():
        line = raw.rstrip("\r\n")
        if not line.strip():
            if in_block and rows:
                break
            continue
        parts = line.split("\t")
        head = parts[0].strip()
        if head.lower().startswith("interval data:"):
            if columns:
                break
            columns = [re.sub(r"\s*\[.*?\]\s*$", "", c).strip() for c in parts[1:]]
            in_block = True
            continue
        if in_block:
            cells = parts[1:] if len(parts) > len(columns) else parts
            if all(c.strip() == "" or c.strip().startswith("[") for c in cells):
                continue                                          # the units line
            vals = [_cell(c) for c in cells[:len(columns)]]
            if any(v is not None for v in vals):
                rows.append(vals)
            continue
        if head.endswith(":") and len(parts) > 1:
            meta[head[:-1]] = parts[1].strip()
    if not columns or not rows:
        raise DeviceFault("export has no 'Interval data:' header with rows", {"transient": False, "recovery": "operator"})
    return {"meta": meta, "columns": columns, "rows": rows}


def _col(parsed: dict, *names: str) -> list:
    low = [c.lower() for c in parsed["columns"]]
    for n in names:
        if n in low:
            i = low.index(n)
            return [r[i] if i < len(r) else None for r in parsed["rows"]]
    return []


class RheoCompassBackend:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.log: list[str] = []
        self.pending: dict[str, pathlib.Path] = {}

    def _dir(self, key: str) -> pathlib.Path:
        d = self.cfg.get(key)
        if not d:
            raise DeviceFault(f"config.json is missing {key} (copy config.example.json and fill it in)",
                              {"transient": False, "recovery": "operator"})
        return pathlib.Path(d)

    def open(self) -> None:
        for key in ("job_dir", "results_dir"):
            d = self._dir(key)
            if not d.is_dir():
                raise DeviceFault(f"{key} {d} does not exist", {"transient": True, "recovery": "operator"})
        if not os.access(self._dir("job_dir"), os.W_OK):
            raise DeviceFault(f"job_dir {self._dir('job_dir')} is not writable", {"transient": True, "recovery": "operator"})

    def hood_closed(self) -> bool:
        f = self.cfg.get("hood_state_file")
        if not f:
            return False
        try:
            return pathlib.Path(f).read_text(encoding="utf-8", errors="replace").strip().lower() == "closed"
        except OSError:
            return False

    def live_temperature(self) -> float | None:
        f = self.cfg.get("live_export_file")
        if not f or not pathlib.Path(f).is_file():
            return None
        try:
            parsed = parse_export(decode_export(pathlib.Path(f).read_bytes()))
        except DeviceFault:
            return None
        t = [v for v in _col(parsed, "temperature") if v is not None]
        return round(t[-1], 2) if t else None

    # ---- the job file (CSV; shape chosen by this package, see references/rheocompass_files.md) ---- #
    def write_job(self, token: str, p: dict, result_name: str) -> pathlib.Path:
        fc, fs = p.get("flow_curve") or {}, p.get("frequency_sweep") or {}
        path = self._dir("job_dir") / f"{token}.csv"
        tmp = path.with_suffix(".tmp")
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\r\n")
        w.writerow(JOB_COLUMNS)
        w.writerow([token, p["sample_name"], p["test_type"], p["measuring_system"], f"{p['temperature_c']:.1f}",
                    fc.get("shear_rate_start", ""), fc.get("shear_rate_end", ""), fs.get("strain_pct", ""),
                    fs.get("frequency_start_hz", ""), fs.get("frequency_end_hz", ""), fc.get("points", fs.get("points", "")),
                    fc.get("point_duration_s", ""), str(fc.get("log", True)).lower() if fc else "", result_name + ".txt"])
        tmp.write_text(buf.getvalue(), encoding="utf-8")
        os.replace(tmp, path)
        self.pending[token] = path
        self.log.append(f"wrote job {path.name}: {p['sample_name']} {p['test_type']} {p['measuring_system']} at {p['temperature_c']} C")
        return path

    def queue_depth(self) -> int:
        try:
            return sum(1 for f in self._dir("job_dir").glob("*.csv") if f.is_file())
        except DeviceFault:
            return 0

    def picked_up(self, token: str) -> bool:
        p = self.pending.get(token)
        return p is not None and not p.exists()

    def result_path(self, result_name: str) -> pathlib.Path | None:
        for ext in (".txt", ".csv"):
            p = self._dir("results_dir") / (result_name + ext)
            if p.is_file():
                return p
        return None

    def parse(self, result_name: str, test_type: str) -> dict:
        path = self.result_path(result_name)
        if path is None:
            raise DeviceFault(f"no export for {result_name}", {"transient": True, "recovery": "retry_after"})
        parsed = parse_export(decode_export(path.read_bytes()))
        temps = [v for v in _col(parsed, "temperature") if v is not None]
        summary = {}
        for key, names in SUMMARY.items():
            col = [v for v in _col(parsed, *names) if v is not None]
            summary[key] = round(col[-1], 6) if col else None
        return {"file": str(path), "points": len(parsed["rows"]), "columns": parsed["columns"],
                "temperature_mean_c": round(sum(temps) / len(temps), 2) if temps else None, "summary": summary}

    def abort(self) -> list[str]:
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


class AntonPaarRheometer(Driver):
    def setup(self) -> None:
        self.cfg = load_config()
        self.hw = None
        self.last_result = None
        self.setpoint: float | None = None
        self.stopped = False

    def make_backend(self):
        return RheoCompassBackend(self.cfg)

    def time_scale(self) -> float:
        return 1.0

    def _hw(self) -> RheoCompassBackend:
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
        if name == "temperature":
            return self._hw().live_temperature()
        if name == "temperature_setpoint":
            return self.setpoint
        if name == "hood_closed":
            return self._hw().hood_closed()
        if name == "last_result":
            return self.last_result
        raise InvalidValue(f"unknown signal {name}")

    @staticmethod
    def _expected_s(p: dict) -> float:
        fc, fs = p.get("flow_curve") or {}, p.get("frequency_sweep") or {}
        if p["test_type"] == "flow_curve":
            return fc["points"] * fc["point_duration_s"]
        total = 0.0
        for i in range(fs["points"]):                              # one or more periods per point, at least 5 s
            f = fs["frequency_start_hz"] * (fs["frequency_end_hz"] / fs["frequency_start_hz"]) ** (i / max(fs["points"] - 1, 1))
            total += max(5.0, 2.0 / f)
        return total

    def validate_params(self, action: str, params: dict) -> None:
        if action != "queue_test":
            return
        if not _NAME.match(str(params.get("sample_name", ""))):
            raise InvalidValue("sample_name must be letters, digits, underscore, hyphen or dot (it names the export)")
        if not _PLAIN.match(str(params.get("measuring_system", ""))):
            raise InvalidValue("measuring_system must be a plain RheoCompass name such as CP50-1 or PP25")
        tt = params["test_type"]
        if tt == "flow_curve" and not params.get("flow_curve"):
            raise InvalidValue("test_type flow_curve needs the flow_curve object")
        if tt == "frequency_sweep" and not params.get("frequency_sweep"):
            raise InvalidValue("test_type frequency_sweep needs the frequency_sweep object")
        fc = params.get("flow_curve") or {}
        if fc and fc["shear_rate_end"] == fc["shear_rate_start"]:
            raise InvalidValue("flow_curve.shear_rate_end must differ from shear_rate_start")
        fs = params.get("frequency_sweep") or {}
        if fs and fs["frequency_end_hz"] == fs["frequency_start_hz"]:
            raise InvalidValue("frequency_sweep.frequency_end_hz must differ from frequency_start_hz")
        max_h = float(self.cfg.get("max_test_hours", 6))
        secs = self._expected_s(params)
        if secs > max_h * 3600:
            raise LimitViolation(f"the test would take {secs / 3600:.1f} h; max_test_hours is {max_h}", {"max": max_h})

    def on_invoke(self, job: Job):
        if job.action != "queue_test":
            raise InvalidValue(f"unhandled action {job.action}")
        hw = self._hw()
        p = job.params
        self.stopped = False
        token = f"mhp_{time.strftime('%Y%m%d')}_{job.id.replace('job_', '')}"
        result_name = f"{p['sample_name']}_{token}"
        if hw.result_path(result_name) is not None:
            raise InvalidValue(f"{result_name}.txt already exists in results_dir")
        started = time.time()
        hw.write_job(token, p, result_name)
        self.checkpoint(job, 0.05, phase="queued for RheoCompass")
        expected = (self._expected_s(p) + float(self.cfg.get("equilibration_s", 300))) * self.time_scale()
        poll = float(self.cfg.get("poll_s", 10)) * self.time_scale()
        wait = float(self.cfg.get("result_wait_s", 2 * expected / self.time_scale() + 900)) * self.time_scale()
        t0 = time.monotonic()
        try:
            while hw.result_path(result_name) is None:
                if self.stopped:
                    raise DeviceFault("stopped: the queued job file was removed; a test already started must be "
                                      "stopped in RheoCompass", {"transient": False, "recovery": "operator"})
                elapsed = time.monotonic() - t0
                if hw.picked_up(token):
                    self.setpoint = float(p["temperature_c"])
                    self.checkpoint(job, min(0.95, 0.1 + 0.85 * elapsed / max(expected, 1e-6)), phase="measuring")
                else:
                    self.checkpoint(job, 0.05, phase="waiting for the job to be taken")
                if elapsed > wait:
                    raise DeviceFault(f"no {result_name}.txt after {wait / self.time_scale():.0f} s; the job file "
                                      f"{token}.csv is left in {self.cfg.get('job_dir')}",
                                      {"transient": True, "recovery": "retry_after"})
                time.sleep(poll)
            time.sleep(min(poll, 2.0 * self.time_scale()))          # let RheoCompass finish writing the export
        finally:
            self.setpoint = None
            hw.pending.pop(token, None)
        parsed = hw.parse(result_name, p["test_type"])
        result = {"sample_name": p["sample_name"], "test_type": p["test_type"], **parsed,
                  "duration_s": round((time.time() - started) / self.time_scale(), 1)}
        self.last_result = result
        self.emit_signal("last_result", result)
        return result

    def on_estop(self) -> None:
        self.stopped = True
        if self.hw is not None:
            self.hw.abort()

    @classmethod
    def probe(cls, cfg: dict) -> str:
        hw = RheoCompassBackend(cfg)
        hw.open()
        return (f"jobs go to {cfg.get('job_dir')}, exports are read from {cfg.get('results_dir')} "
                f"({hw.queue_depth()} job(s) waiting, hood {'closed' if hw.hood_closed() else 'open or unknown'})")
