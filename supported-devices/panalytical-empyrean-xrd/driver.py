"""MHP driver for a Malvern Panalytical Empyrean / Aeris diffractometer under Data Collector (file-based route, Windows PC).

The package writes one job file per scan into the folder the lab's job import (Operator Interface job list,
a batch built by a script, or a Universal Automation Interface client) reads, waits for the `.xrdml` result
and parses the scan. Data Collector moves the changer, opens the shutter and measures; the package touches no
hardware. Formats and what is unverified: references/xrdml_files.md.
"""
from __future__ import annotations

import json
import math
import os
import pathlib
import re
import time
import xml.etree.ElementTree as ET

from openmhp.driver import DeviceFault, Driver, InvalidValue, Job, LimitViolation

HERE = pathlib.Path(__file__).parent
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_NS = re.compile(r"^\{(http://www\.xrdml\.com/XRDMeasurement/([\d.]+))\}")
MODES = {"continuous": "Continuous", "pre_set_time": "Pre-set time"}


def load_config() -> dict:
    p = HERE / "config.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def _floats(text: str | None) -> list[float]:
    return [float(x) for x in (text or "").split()]


def parse_xrdml(data: bytes) -> dict:
    """The first scan of the first xrdMeasurement: namespace taken from the root tag (schema 1.0 to 2.x),
    2Theta positions from startPosition/endPosition or listPositions, intensities (1.x) or counts (2.x)."""
    root = ET.fromstring(data)
    m = _NS.match(root.tag)
    if not m or not root.tag.endswith("xrdMeasurements"):
        raise DeviceFault("not an XRDML file: root is not xrdMeasurements in the xrdml.com namespace",
                          {"transient": False, "recovery": "operator"})
    ns, version = "{" + m.group(1) + "}", m.group(2)
    meas = root.find(ns + "xrdMeasurement")
    scan = meas.find(ns + "scan") if meas is not None else None
    if scan is None:
        raise DeviceFault("the XRDML holds no xrdMeasurement/scan", {"transient": False, "recovery": "operator"})
    dp = scan.find(ns + "dataPoints")
    if dp is None:
        raise DeviceFault("the scan holds no dataPoints", {"transient": False, "recovery": "operator"})
    inten = dp.find(ns + "intensities")
    if inten is None:
        inten = dp.find(ns + "counts")
    values = _floats(inten.text if inten is not None else None)
    start = end = None
    for pos in dp.findall(ns + "positions"):
        if pos.get("axis") != "2Theta":
            continue
        s, e, lst = pos.find(ns + "startPosition"), pos.find(ns + "endPosition"), pos.find(ns + "listPositions")
        if s is not None and e is not None:
            start, end = float(s.text), float(e.text)
        elif lst is not None:
            xs = _floats(lst.text)
            if xs:
                start, end = xs[0], xs[-1]
    ct = dp.find(ns + "commonCountingTime")
    sample = meas.find(ns + "sample")
    sid = sample.find(ns + "id") if sample is not None else None
    return {"schema_version": version, "measurement_type": meas.get("measurementType"), "status": scan.get("status") or "unknown",
            "scan_axis": scan.get("scanAxis"), "mode": scan.get("mode"), "points": len(values), "intensities": values,
            "two_theta_range": [start, end] if start is not None else None,
            "counting_time_s": float(ct.text) if ct is not None and ct.text else None,
            "sample_id": sid.text if sid is not None else None}


class DataCollectorBackend:
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

    # ---- the job file (XML; shape chosen by this package, see references/xrdml_files.md) ---- #
    def write_job(self, token: str, p: dict, result_name: str) -> pathlib.Path:
        prog = p["program"]
        job = ET.Element("MeasurementJob", {"Id": token, "Source": "openmhp"})
        ET.SubElement(job, "SampleId").text = p["sample_id"]
        ET.SubElement(job, "Position").text = "" if p.get("position") is None else str(p["position"])
        ET.SubElement(job, "ProgramFile").text = prog.get("program_file") or ""
        ET.SubElement(job, "ResultFile").text = result_name + ".xrdml"
        scan = ET.SubElement(job, "Scan", {"ScanAxis": prog.get("scan_axis", "Gonio"), "Mode": MODES[prog.get("mode", "continuous")]})
        ET.SubElement(scan, "StartPosition", {"axis": "2Theta", "unit": "deg"}).text = f"{prog['start_2theta']:.4f}"
        ET.SubElement(scan, "EndPosition", {"axis": "2Theta", "unit": "deg"}).text = f"{prog['end_2theta']:.4f}"
        ET.SubElement(scan, "StepSize", {"unit": "deg"}).text = f"{prog['step']:.4f}"
        ET.SubElement(scan, "CommonCountingTime", {"unit": "seconds"}).text = f"{prog['time_per_step_s']:.3f}"
        path = self._dir("job_dir") / f"{token}.xml"
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(b'<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(job, encoding="utf-8"))
        os.replace(tmp, path)
        self.pending[token] = path
        self.log.append(f"wrote job {path.name}: {p['sample_id']} pos {p.get('position')} "
                        f"{prog['start_2theta']}-{prog['end_2theta']} step {prog['step']} x {prog['time_per_step_s']} s")
        return path

    def queue_depth(self) -> int:
        try:
            return sum(1 for f in self._dir("job_dir").glob("*.xml") if f.is_file())
        except DeviceFault:
            return 0

    def picked_up(self, token: str) -> bool:
        p = self.pending.get(token)
        return p is not None and not p.exists()

    # ---- results ------------------------------------------------------------------------- #
    def result_path(self, result_name: str) -> pathlib.Path | None:
        p = self._dir("results_dir") / (result_name + ".xrdml")
        return p if p.is_file() else None

    def parse(self, result_name: str) -> dict:
        path = self.result_path(result_name)
        if path is None:
            raise DeviceFault(f"no {result_name}.xrdml", {"transient": True, "recovery": "retry_after"})
        try:
            r = parse_xrdml(path.read_bytes())
        except ET.ParseError as e:
            raise DeviceFault(f"{path.name} is not well-formed XML: {e}", {"transient": True, "recovery": "retry_after"}) from None
        if not r["points"]:
            raise DeviceFault(f"no intensities/counts found in {path.name}", {"transient": False, "recovery": "operator"})
        if r["two_theta_range"] is None:
            raise DeviceFault(f"no 2Theta positions found in {path.name}", {"transient": False, "recovery": "operator"})
        return {"file": str(path), "points": r["points"], "two_theta_range": [round(x, 4) for x in r["two_theta_range"]],
                "counting_time_s": r["counting_time_s"], "status": r["status"], "measurement_type": r["measurement_type"],
                "schema_version": r["schema_version"]}

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


class PanalyticalXrd(Driver):
    def setup(self) -> None:
        self.cfg = load_config()
        self.hw = None
        self.last_result = None
        self.current_position: int | None = None
        self.stopped = False

    def make_backend(self):
        return DataCollectorBackend(self.cfg)

    def time_scale(self) -> float:
        return 1.0

    def _hw(self) -> DataCollectorBackend:
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
        if n * prog["time_per_step_s"] > max_h * 3600:
            raise LimitViolation(f"the scan would take {n * prog['time_per_step_s'] / 3600:.1f} h; max_scan_hours is {max_h}", {"max": max_h})
        positions = int(self.cfg.get("changer_positions", 6))
        if params.get("position") is not None and not 1 <= int(params["position"]) <= positions:
            raise LimitViolation(f"position {params['position']} is outside 1..{positions} (changer_positions in config.json)",
                                 {"min": 1, "max": positions})
        pf = prog.get("program_file")
        if pf is not None and (not pf.lower().endswith(".xrdmp") or "/" in pf or "\\" in pf or ".." in pf):
            raise InvalidValue("program.program_file must be a bare .xrdmp file name in Data Collector's program folder")

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
            raise InvalidValue(f"{result_name}.xrdml already exists in results_dir")
        started = time.time()
        hw.write_job(token, p, result_name)
        self.checkpoint(job, 0.05, phase="queued for Data Collector")
        n = self._points(prog)
        expected = (n * prog["time_per_step_s"] + float(self.cfg.get("changer_s", 60))) * self.time_scale()
        poll = float(self.cfg.get("poll_s", 10)) * self.time_scale()
        wait = float(self.cfg.get("result_wait_s", 2 * expected / self.time_scale() + 900)) * self.time_scale()
        t0 = time.monotonic()
        try:
            while hw.result_path(result_name) is None:
                if self.stopped:
                    raise DeviceFault("stopped: the queued job file was removed; a scan already started must be "
                                      "stopped in Data Collector", {"transient": False, "recovery": "operator"})
                elapsed = time.monotonic() - t0
                if hw.picked_up(token):
                    self.current_position = p.get("position")
                    self.checkpoint(job, min(0.95, 0.1 + 0.85 * elapsed / max(expected, 1e-6)), phase="measuring")
                else:
                    self.checkpoint(job, 0.05, phase="waiting for the job to be taken")
                if elapsed > wait:
                    raise DeviceFault(f"no {result_name}.xrdml after {wait / self.time_scale():.0f} s; the job file "
                                      f"{token}.xml is left in {self.cfg.get('job_dir')}",
                                      {"transient": True, "recovery": "retry_after"})
                time.sleep(poll)
            time.sleep(min(poll, 2.0 * self.time_scale()))          # let Data Collector finish writing the file
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
    def discover(cls, cfg: dict, what: str) -> list:
        if what == "program_files" and cfg.get("programs_dir") and pathlib.Path(cfg["programs_dir"]).is_dir():
            return sorted(f.name for f in pathlib.Path(cfg["programs_dir"]).glob("*.xrdmp"))
        return []

    @classmethod
    def probe(cls, cfg: dict) -> str:
        hw = DataCollectorBackend(cfg)
        hw.open()
        return f"jobs go to {cfg.get('job_dir')}, results are read from {cfg.get('results_dir')} ({hw.queue_depth()} job(s) waiting)"
