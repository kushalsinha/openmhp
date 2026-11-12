"""MHP driver for a Rigaku SmartLab / MiniFlex diffractometer under SmartLab Studio II (file-based route, Windows PC).

The package writes one job file per scan into the folder the lab's Studio II import flow (a flow
template, a Package Part run per changer position, or a Rigaku Automation Interface client) reads,
waits for the `.rasx` (zip) or `.ras` (text) result and parses the pattern and the header. Studio II
aligns, moves the changer, opens the shutter and measures; the package touches no hardware.
Formats and what is unverified: references/rigaku_files.md.
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
import xml.etree.ElementTree as ET
import zipfile

from openmhp.driver import DeviceFault, Driver, InvalidValue, Job, LimitViolation

HERE = pathlib.Path(__file__).parent
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_HDR = re.compile(r'^\*([A-Z0-9_]+(?:-\d+)?)\s+"?(.*?)"?\s*$')
_NUM = r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?"
_ROW = re.compile(rf"^\s*({_NUM})[\s,;]+({_NUM})(?:[\s,;]+({_NUM}))?\s*$")
JOB_COLUMNS = ["job_id", "sample_id", "position", "axis", "mode", "start", "stop", "step", "speed_deg_min", "result_file"]


def load_config() -> dict:
    p = HERE / "config.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def _decode(data: bytes) -> str:
    """Rigaku text: ASCII/CRLF in every public file; Japanese installations may write Shift-JIS names."""
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _header_summary(h: dict) -> dict:
    def num(key):
        try:
            return float(h[key])
        except (KeyError, ValueError, TypeError):
            return None
    return {"scan_speed_deg_min": num("*MEAS_SCAN_SPEED"), "target": h.get("*HW_XG_TARGET_NAME") or None,
            "voltage_kv": num("*MEAS_COND_XG_VOLTAGE"), "current_ma": num("*MEAS_COND_XG_CURRENT")}


def parse_ras(text: str) -> tuple[dict, list[tuple[float, float]]]:
    """A Studio II `.ras`: `*RAS_DATA_START`, then per scan a `*RAS_HEADER_START..END` block of `*KEY "value"`
    lines and a `*RAS_INT_START..END` block of `angle intensity attenuation` rows. First scan only."""
    header: dict[str, str] = {}
    pts: list[tuple[float, float]] = []
    where = None
    for line in text.splitlines():
        s = line.strip()
        if s == "*RAS_HEADER_START" and not header:
            where = "header"
        elif s == "*RAS_HEADER_END":
            where = None
        elif s == "*RAS_INT_START" and not pts:
            where = "data"
        elif s == "*RAS_INT_END":
            if pts:
                break
            where = None
        elif where == "header":
            m = _HDR.match(s)
            if m:
                header["*" + m.group(1)] = m.group(2)
        elif where == "data":
            m = _ROW.match(s)
            if m:
                pts.append((float(m.group(1)), float(m.group(2))))
    if not header and not pts:
        raise DeviceFault("not a .ras file: no *RAS_HEADER_START / *RAS_INT_START blocks", {"transient": False, "recovery": "operator"})
    return header, pts


def parse_rasx(data: bytes) -> tuple[dict, list[tuple[float, float]]]:
    """A Studio II `.rasx`: a zip with Data0/Profile0.txt (UTF-8 BOM, tab-separated angle, intensity, attenuation)
    and Data0/MesurementConditions0.xml (vendor spelling) whose RASHeader repeats the .ras keys."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        prof = next((n for n in sorted(names) if n.endswith("Profile0.txt")), None) or \
            next((n for n in sorted(names) if re.search(r"Profile\d+\.txt$", n)), None)
        cond = next((n for n in sorted(names) if re.search(r"Me[a]?surementConditions0\.xml$", n)), None)
        if prof is None:
            raise DeviceFault("the .rasx holds no DataN/ProfileN.txt", {"transient": False, "recovery": "operator"})
        rows = _decode(z.read(prof))
        header: dict[str, str] = {}
        if cond is not None:
            root = ET.fromstring(_decode(z.read(cond)).encode("utf-8"))
            for pair in root.iter("Pair"):
                strs = [e.text or "" for e in pair.findall("string")]
                if len(strs) == 2 and strs[0].startswith("*"):
                    header[strs[0]] = strs[1]
            scan = root.find(".//ScanInformation")
            xg = root.find(".//XrayGenerator")
            if scan is not None:
                for tag, key in (("Speed", "*MEAS_SCAN_SPEED"), ("Start", "*MEAS_SCAN_START"), ("Stop", "*MEAS_SCAN_STOP"),
                                 ("Step", "*MEAS_SCAN_STEP"), ("Mode", "*MEAS_SCAN_MODE"), ("AxisName", "*MEAS_SCAN_AXIS_X")):
                    e = scan.find(tag)
                    if e is not None and e.text:
                        header.setdefault(key, e.text)
            if xg is not None:
                for tag, key in (("TargetName", "*HW_XG_TARGET_NAME"), ("Voltage", "*MEAS_COND_XG_VOLTAGE"), ("Current", "*MEAS_COND_XG_CURRENT")):
                    e = xg.find(tag)
                    if e is not None and e.text:
                        header.setdefault(key, e.text)
    pts = []
    for line in rows.splitlines():
        m = _ROW.match(line)
        if m:
            pts.append((float(m.group(1)), float(m.group(2))))
    return header, pts


class StudioBackend:
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

    # ---- the job file (CSV; shape chosen by this package, see references/rigaku_files.md) ---- #
    def write_job(self, token: str, p: dict, result_name: str) -> pathlib.Path:
        prog = p["program"]
        path = self._dir("job_dir") / f"{token}.csv"
        tmp = path.with_suffix(".tmp")
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\r\n")
        w.writerow(JOB_COLUMNS)
        w.writerow([token, p["sample_id"], "" if p.get("position") is None else p["position"], prog.get("axis", "TwoThetaTheta"),
                    str(prog.get("mode", "continuous")).upper(), f"{prog['start_2theta']:.4f}", f"{prog['end_2theta']:.4f}",
                    f"{prog['step']:.4f}", f"{prog['speed_deg_min']:.4f}", result_name + ".rasx"])
        tmp.write_text(buf.getvalue(), encoding="utf-8")
        os.replace(tmp, path)
        self.pending[token] = path
        self.log.append(f"wrote job {path.name}: {p['sample_id']} pos {p.get('position')} "
                        f"{prog['start_2theta']}-{prog['end_2theta']} step {prog['step']} at {prog['speed_deg_min']} deg/min")
        return path

    def queue_depth(self) -> int:
        try:
            return sum(1 for f in self._dir("job_dir").glob("*.csv") if f.is_file())
        except DeviceFault:
            return 0

    def picked_up(self, token: str) -> bool:
        p = self.pending.get(token)
        return p is not None and not p.exists()

    # ---- results ------------------------------------------------------------------------- #
    def result_path(self, result_name: str) -> pathlib.Path | None:
        for ext in (".rasx", ".ras"):
            p = self._dir("results_dir") / (result_name + ext)
            if p.is_file():
                return p
        return None

    def parse(self, result_name: str) -> dict:
        path = self.result_path(result_name)
        if path is None:
            raise DeviceFault(f"no result file for {result_name}", {"transient": True, "recovery": "retry_after"})
        try:
            if path.suffix.lower() == ".rasx":
                header, pts = parse_rasx(path.read_bytes())
            else:
                header, pts = parse_ras(_decode(path.read_bytes()))
        except (zipfile.BadZipFile, ET.ParseError) as e:
            raise DeviceFault(f"{path.name} is not a readable {path.suffix}: {e}", {"transient": True, "recovery": "retry_after"}) from None
        if not pts:
            raise DeviceFault(f"no data rows found in {path.name}", {"transient": False, "recovery": "operator"})
        angles = [a for a, _ in pts]
        return {"file": str(path), "format": path.suffix.lower().lstrip("."), "points": len(pts),
                "two_theta_range": [round(min(angles), 4), round(max(angles), 4)], **_header_summary(header)}

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


class RigakuSmartLab(Driver):
    def setup(self) -> None:
        self.cfg = load_config()
        self.hw = None
        self.last_result = None
        self.current_position: int | None = None
        self.stopped = False

    def make_backend(self):
        return StudioBackend(self.cfg)

    def time_scale(self) -> float:
        return 1.0

    def _hw(self) -> StudioBackend:
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
            return self.current_position
        if name == "last_result":
            return self.last_result
        raise InvalidValue(f"unknown signal {name}")

    @staticmethod
    def _points(prog: dict) -> int:
        return math.floor((prog["end_2theta"] - prog["start_2theta"]) / prog["step"] + 1e-9) + 1

    def validate_params(self, action: str, params: dict) -> None:
        if action != "queue_scan":
            return
        if not _NAME.match(str(params.get("sample_id", ""))):
            raise InvalidValue("sample_id must be letters, digits, underscore, hyphen or dot (it names the result file)")
        prog = params["program"]
        if prog["end_2theta"] <= prog["start_2theta"]:
            raise InvalidValue("program.end_2theta must be above program.start_2theta")
        n = self._points(prog)
        max_points = int(self.cfg.get("max_points", 50000))
        if n > max_points:
            raise LimitViolation(f"the scan would have {n} points; max_points in config.json is {max_points}", {"max": max_points})
        max_h = float(self.cfg.get("max_scan_hours", 12))
        minutes = (prog["end_2theta"] - prog["start_2theta"]) / prog["speed_deg_min"]
        if minutes > max_h * 60:
            raise LimitViolation(f"the scan would take {minutes / 60:.1f} h; max_scan_hours is {max_h}", {"max": max_h})
        positions = int(self.cfg.get("changer_positions", 10))
        if params.get("position") is not None and not 1 <= int(params["position"]) <= positions:
            raise LimitViolation(f"position {params['position']} is outside 1..{positions} (changer_positions in config.json)",
                                 {"min": 1, "max": positions})

    def on_invoke(self, job: Job):
        if job.action != "queue_scan":
            raise InvalidValue(f"unhandled action {job.action}")
        hw = self._hw()
        p = job.params
        prog = p["program"]
        self.stopped = False
        token = f"mhp_{time.strftime('%Y%m%d')}_{job.id.replace('job_', '')}"
        result_name = f"{p['sample_id']}_{token}"
        if hw.result_path(result_name) is not None:
            raise InvalidValue(f"{result_name}.rasx/.ras already exists in results_dir")
        started = time.time()
        hw.write_job(token, p, result_name)
        self.checkpoint(job, 0.05, phase="queued for SmartLab Studio II")
        expected = ((prog["end_2theta"] - prog["start_2theta"]) / prog["speed_deg_min"] * 60
                    + float(self.cfg.get("changer_s", 90))) * self.time_scale()
        poll = float(self.cfg.get("poll_s", 10)) * self.time_scale()
        wait = float(self.cfg.get("result_wait_s", 2 * expected / self.time_scale() + 900)) * self.time_scale()
        t0 = time.monotonic()
        try:
            while hw.result_path(result_name) is None:
                if self.stopped:
                    raise DeviceFault("stopped: the queued job file was removed; a scan already started must be "
                                      "stopped in SmartLab Studio II", {"transient": False, "recovery": "operator"})
                elapsed = time.monotonic() - t0
                if hw.picked_up(token):
                    self.current_position = p.get("position")
                    self.checkpoint(job, min(0.95, 0.1 + 0.85 * elapsed / max(expected, 1e-6)), phase="measuring")
                else:
                    self.checkpoint(job, 0.05, phase="waiting for the job to be taken")
                if elapsed > wait:
                    raise DeviceFault(f"no {result_name}.rasx/.ras after {wait / self.time_scale():.0f} s; the job file "
                                      f"{token}.csv is left in {self.cfg.get('job_dir')}",
                                      {"transient": True, "recovery": "retry_after"})
                time.sleep(poll)
            time.sleep(min(poll, 2.0 * self.time_scale()))          # let Studio II finish writing the zip
        finally:
            self.current_position = None
            hw.pending.pop(token, None)
        parsed = hw.parse(result_name)
        result = {"sample_id": p["sample_id"], **parsed, "duration_s": round((time.time() - started) / self.time_scale(), 1)}
        self.last_result = result
        self.emit_signal("last_result", result)
        return result

    def on_estop(self) -> None:
        self.stopped = True
        if self.hw is not None:
            self.hw.abort()

    @classmethod
    def probe(cls, cfg: dict) -> str:
        hw = StudioBackend(cfg)
        hw.open()
        return f"jobs go to {cfg.get('job_dir')}, results are read from {cfg.get('results_dir')} ({hw.queue_depth()} job(s) waiting)"
