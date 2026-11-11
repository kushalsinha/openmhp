"""MHP driver for a Bruker D8 powder diffractometer under DIFFRAC.SUITE (file-based route, Windows PC).

The package writes one job file per scan into the folder the DIFFRAC.MEASUREMENT CENTER job
import reads, waits for the raw `.brml` result (and the `.xy` text export where DIFFRAC's
Result Manager / a post-processing script writes one) and parses the pattern. DIFFRAC.SUITE
moves the sample changer, opens the shutter and measures; the package touches no hardware.
Formats and what is unverified: references/diffrac_files.md.
"""
from __future__ import annotations

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
_NUM2 = re.compile(r"^\s*([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)[\s,;]+([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*$")


def load_config() -> dict:
    p = HERE / "config.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def parse_xy(text: str) -> list[tuple[float, float]]:
    """Two-column text (2theta, intensity), any whitespace/comma/semicolon separator; other lines are skipped."""
    out = []
    for line in text.splitlines():
        m = _NUM2.match(line)
        if m:
            out.append((float(m.group(1)), float(m.group(2))))
    return out


def parse_brml(data: bytes) -> list[tuple[float, float]]:
    """Read Experiment0/RawData0.xml (the first RawData*.xml) out of a .brml zip: one (2theta, counts) per Datum.

    Datum fields, comma-separated, as the GSAS-II importer reads them: index 0 time per step, index 2 the
    2theta angle, index 4 the counts (index 3 in some files). Fields beyond those are not interpreted.
    """
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = sorted(n for n in z.namelist() if "RawData" in n and n.endswith(".xml"))
        if not names:
            raise DeviceFault("the .brml holds no RawData*.xml", {"transient": False, "recovery": "operator"})
        root = ET.fromstring(z.read(names[0]))
    pts = []
    for datum in root.iter("Datum"):
        f = (datum.text or "").split(",")
        if len(f) < 4:
            continue
        try:
            two_theta = float(f[2])
            counts = float(f[4]) if len(f) > 4 else float(f[3])
        except ValueError:
            continue
        pts.append((two_theta, counts))
    return pts


class DiffracBackend:
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

    # ---- the job file (XML; shape chosen by this package, see references/diffrac_files.md) ---- #
    def write_job(self, token: str, p: dict, result_name: str) -> pathlib.Path:
        prog = p["program"]
        job = ET.Element("MeasurementJob", {"Id": token, "Source": "openmhp"})
        ET.SubElement(job, "SampleId").text = p["sample_id"]
        ET.SubElement(job, "Position").text = "" if p.get("position") is None else str(p["position"])
        ET.SubElement(job, "MethodFile").text = prog.get("method_file") or ""
        ET.SubElement(job, "ResultFile").text = result_name + ".brml"
        scan = ET.SubElement(job, "Scan", {"Axis": "TwoTheta", "Mode": "Coupled"})
        ET.SubElement(scan, "Start").text = f"{prog['start_2theta']:.4f}"
        ET.SubElement(scan, "Stop").text = f"{prog['end_2theta']:.4f}"
        ET.SubElement(scan, "Increment").text = f"{prog['step']:.4f}"
        ET.SubElement(scan, "TimePerStep").text = f"{prog['time_per_step_s']:.3f}"
        path = self._dir("job_dir") / f"{token}.xml"
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(b'<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(job, encoding="utf-8"))
        os.replace(tmp, path)
        self.pending[token] = path
        self.log.append(f"wrote job {path.name}: {p['sample_id']} pos {p.get('position')} "
                        f"{prog['start_2theta']}-{prog['end_2theta']} step {prog['step']}")
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
    def brml_path(self, result_name: str) -> pathlib.Path | None:
        p = self._dir("results_dir") / (result_name + ".brml")
        return p if p.is_file() else None

    def xy_path(self, result_name: str) -> pathlib.Path | None:
        d = self.cfg.get("xy_dir") or self.cfg.get("results_dir")
        for ext in (".xy", ".txt", ".xye"):
            p = pathlib.Path(d) / (result_name + ext)
            if p.is_file():
                return p
        return None

    def parse(self, result_name: str) -> dict:
        brml = self.brml_path(result_name)
        xy = self.xy_path(result_name)
        pts: list[tuple[float, float]] = []
        if brml is not None:
            try:
                pts = parse_brml(brml.read_bytes())
            except (zipfile.BadZipFile, ET.ParseError) as e:
                raise DeviceFault(f"{brml.name} is not a readable .brml: {e}",
                                  {"transient": True, "recovery": "retry_after"}) from None
        if not pts and xy is not None:
            pts = parse_xy(xy.read_text(encoding="utf-8", errors="replace"))
        if not pts:
            raise DeviceFault(f"no data points found for {result_name}", {"transient": False, "recovery": "operator"})
        angles = [a for a, _ in pts]
        return {"file": str(brml) if brml else str(xy), "xy_file": str(xy) if xy else None, "points": len(pts),
                "two_theta_range": [round(min(angles), 4), round(max(angles), 4)]}

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


class BrukerD8(Driver):
    def setup(self) -> None:
        self.cfg = load_config()
        self.hw = None
        self.last_result = None
        self.current_position: int | None = None
        self.stopped = False

    def make_backend(self):
        return DiffracBackend(self.cfg)

    def time_scale(self) -> float:
        return 1.0

    def _hw(self) -> DiffracBackend:
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

    def validate_params(self, action: str, params: dict) -> None:
        if action != "queue_scan":
            return
        if not _NAME.match(str(params.get("sample_id", ""))):
            raise InvalidValue("sample_id must be letters, digits, underscore, hyphen or dot (it names the result file)")
        prog = params["program"]
        if prog["end_2theta"] <= prog["start_2theta"]:
            raise InvalidValue("program.end_2theta must be above program.start_2theta")
        n = (prog["end_2theta"] - prog["start_2theta"]) / prog["step"]
        max_points = int(self.cfg.get("max_points", 20000))
        if n > max_points:
            raise LimitViolation(f"the scan would have {int(n)} points; max_points in config.json is {max_points}",
                                 {"max": max_points})
        max_h = float(self.cfg.get("max_scan_hours", 12))
        if n * prog["time_per_step_s"] > max_h * 3600:
            raise LimitViolation(f"the scan would take {n * prog['time_per_step_s'] / 3600:.1f} h; max_scan_hours is {max_h}",
                                 {"max": max_h})
        positions = int(self.cfg.get("changer_positions", 9))
        if params.get("position") is not None and not 1 <= int(params["position"]) <= positions:
            raise LimitViolation(f"position {params['position']} is outside 1..{positions} (changer_positions in config.json)",
                                 {"min": 1, "max": positions})
        mf = prog.get("method_file")
        if mf is not None and (not mf.lower().endswith(".bsml") or "/" in mf or "\\" in mf or ".." in mf):
            raise InvalidValue("program.method_file must be a bare .bsml file name in DIFFRAC's method folder")

    def on_invoke(self, job: Job):
        if job.action != "queue_scan":
            raise InvalidValue(f"unhandled action {job.action}")
        hw = self._hw()
        p = job.params
        prog = p["program"]
        self.stopped = False
        token = f"mhp_{time.strftime('%Y%m%d')}_{job.id.replace('job_', '')}"
        result_name = f"{p['sample_id']}_{token}"
        if hw.brml_path(result_name) is not None:
            raise InvalidValue(f"{result_name}.brml already exists in results_dir")
        started = time.time()
        hw.write_job(token, p, result_name)
        self.checkpoint(job, 0.05, phase="queued for DIFFRAC.MEASUREMENT CENTER")
        n = math.floor((prog["end_2theta"] - prog["start_2theta"]) / prog["step"]) + 1
        expected = (n * prog["time_per_step_s"] + float(self.cfg.get("changer_s", 60))) * self.time_scale()
        poll = float(self.cfg.get("poll_s", 10)) * self.time_scale()
        wait = float(self.cfg.get("result_wait_s", 2 * expected / self.time_scale() + 900)) * self.time_scale()
        t0 = time.monotonic()
        try:
            while hw.brml_path(result_name) is None:
                if self.stopped:
                    raise DeviceFault("stopped: the queued job file was removed; a scan already started must be "
                                      "stopped in DIFFRAC.MEASUREMENT CENTER", {"transient": False, "recovery": "operator"})
                elapsed = time.monotonic() - t0
                if hw.picked_up(token):
                    self.current_position = p.get("position")
                    self.checkpoint(job, min(0.95, 0.1 + 0.85 * elapsed / max(expected, 1e-6)), phase="measuring")
                else:
                    self.checkpoint(job, 0.05, phase="waiting for the job to be imported")
                if elapsed > wait:
                    raise DeviceFault(f"no {result_name}.brml after {wait / self.time_scale():.0f} s; the job file "
                                      f"{token}.xml is left in {self.cfg.get('job_dir')}",
                                      {"transient": True, "recovery": "retry_after"})
                time.sleep(poll)
            time.sleep(min(poll, 2.0 * self.time_scale()))          # let DIFFRAC finish writing the zip and the export
        finally:
            self.current_position = None
            hw.pending.pop(token, None)
        parsed = hw.parse(result_name)
        result = {"sample_id": p["sample_id"], **parsed,
                  "duration_s": round((time.time() - started) / self.time_scale(), 1)}
        self.last_result = result
        self.emit_signal("last_result", result)
        return result

    def on_estop(self) -> None:
        self.stopped = True
        if self.hw is not None:
            self.hw.abort()

    @classmethod
    def discover(cls, cfg: dict, what: str) -> list:
        if what == "method_files" and cfg.get("methods_dir") and pathlib.Path(cfg["methods_dir"]).is_dir():
            return sorted(f.name for f in pathlib.Path(cfg["methods_dir"]).glob("*.bsml"))
        return []

    @classmethod
    def probe(cls, cfg: dict) -> str:
        hw = DiffracBackend(cfg)
        hw.open()
        return f"jobs go to {cfg.get('job_dir')}, results are read from {cfg.get('results_dir')} ({hw.queue_depth()} job(s) waiting)"
