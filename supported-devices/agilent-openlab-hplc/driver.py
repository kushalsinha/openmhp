"""MHP driver for an Agilent 1260/1290 Infinity II under OpenLab CDS 2.x, through Sample Scheduler for OpenLab.

Route: Sample Scheduler's LIMS integration, which is file based. A command file dropped in the watched command
folder (default C:\\LIMS_Commands) creates an analysis; Sample Scheduler moves it to a processed folder when
accepted or to `trash` when invalid; "Review for LIMS" copies the result reports (csv, txt, ...) to a result
folder. No REST API for OpenLab CDS is publicly documented, so none is used; see references/sample_scheduler.md.
The folder I/O sits behind SchedulerFolderBackend so the simulated twin can replace it.
"""
from __future__ import annotations

import csv
import json
import os
import pathlib
import re
import time
import xml.etree.ElementTree as ET

from openmhp.driver import DeviceFault, Driver, InvalidValue, Job, LimitViolation

HERE = pathlib.Path(__file__).parent
RESULT_SUFFIXES = (".csv", ".txt", ".tsv")
MAX_ROWS = 2000


def load_config() -> dict:
    p = HERE / "config.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def command_xml(lines: list[dict], cfg: dict) -> bytes:
    """One Sample Scheduler command file. The parameter names are the documented mandatory XML parameters
    (SampleName, Project, Instrument, InjectionSource, AcquisitionMethod, ResultName, Vial, InjectionVolume) plus
    the documented optional ones; the root and grouping element names are unverified (see the reference)."""
    root = ET.Element("Command")                                   # unverified
    analyses = ET.SubElement(root, "Analyses")                     # unverified
    for l in lines:
        a = ET.SubElement(analyses, "Analysis")                    # unverified
        fields = {"SampleName": l["name"], "Project": cfg["project"], "Instrument": cfg["instrument"],
                  "InjectionSource": cfg.get("injection_source", "Sampler"), "AcquisitionMethod": l["method"],
                  "ProcessingMethod": l.get("processing_method") or "", "ResultName": l["result_name"],
                  "Vial": l["vial"], "InjectionVolume": f"{float(l['injection_volume_ul']):g}", "InjectionVolumeUnit": "uL",
                  "InjectionsPerSample": str(int(l.get("injections", 1))), "SampleType": l.get("sample_type", "Sample"),
                  "LIMSID1": l.get("lims_id") or ""}
        for k, v in fields.items():
            ET.SubElement(a, k).text = str(v)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def read_rows(path: pathlib.Path) -> list[dict]:
    text = path.read_text(encoding="utf-8", errors="replace")
    dialect = "excel-tab" if text.count("\t") > text.count(",") else "excel"
    rows = []
    for r in csv.DictReader(text.splitlines(), dialect=dialect, restkey="_extra"):
        rows.append({"file": path.name, **{str(k): v for k, v in r.items()}})
    return rows


class SchedulerFolderBackend:
    def __init__(self, cfg: dict):
        self.cfg = cfg

    def open(self) -> None:
        if not self.cfg.get("command_dir"):
            raise DeviceFault("config.json is missing (copy config.example.json and fill it in)")
        cmd, res = pathlib.Path(self.cfg["command_dir"]), pathlib.Path(self.cfg.get("result_dir") or "")
        if not cmd.is_dir():
            raise DeviceFault(f"command folder {cmd} is not reachable (a share to the Sample Scheduler PC must be mounted)", {"transient": True})
        if not os.access(cmd, os.W_OK):
            raise DeviceFault(f"command folder {cmd} is not writable by this user")
        if self.cfg.get("result_dir") and not res.is_dir():
            raise DeviceFault(f"result folder {res} is not reachable", {"transient": True})

    def methods(self) -> dict:
        folder = self.cfg.get("methods_dir")
        if not folder or not pathlib.Path(folder).is_dir():
            return {"acquisition_methods": [], "processing_methods": [], "note": "methods_dir is not configured; names come from the OpenLab project"}
        p = pathlib.Path(folder)
        return {"acquisition_methods": sorted(f.stem for f in p.rglob("*.amx")),       # unverified: file extensions
                "processing_methods": sorted(f.stem for f in p.rglob("*.pmx"))}

    def submit(self, name: str, lines: list[dict]) -> str:
        path = pathlib.Path(self.cfg["command_dir"]) / f"{name}.xml"
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(command_xml(lines, self.cfg))
        tmp.replace(path)                              # appear atomically; the scheduler polls the folder
        return str(path)

    def command_state(self, name: str) -> str:
        cmd = pathlib.Path(self.cfg["command_dir"])
        if (cmd / f"{name}.xml").exists():
            return "waiting"
        if (cmd / "trash" / f"{name}.xml").exists():
            return "rejected"
        return "accepted"

    def result_files(self, result_name: str, since: float) -> list[pathlib.Path]:
        folder = self.cfg.get("result_dir")
        if not folder or not pathlib.Path(folder).is_dir():
            return []
        out = []
        for f in sorted(pathlib.Path(folder).rglob("*")):
            if f.is_file() and f.suffix.lower() in RESULT_SUFFIXES and result_name.lower() in f.name.lower() and f.stat().st_mtime >= since:
                out.append(f)
        return out


class Device(Driver):
    def setup(self) -> None:
        self.cfg = load_config()
        self.hw = None
        self.is_busy = False
        self.last_result = None
        self.current = None

    def make_backend(self):
        return SchedulerFolderBackend(self.cfg)

    def time_scale(self) -> float:
        return 1.0

    def _hw(self):
        if self.hw is None:
            hw = self.make_backend()
            try:
                hw.open()
            except DeviceFault:
                raise
            except Exception as e:                            # noqa: BLE001
                raise DeviceFault(f"cannot reach the Sample Scheduler folders: {type(e).__name__}: {e}") from None
            self.hw = hw
        return self.hw

    def _status(self) -> dict:
        hw = self._hw()
        cur = self.current
        if not cur:
            return {"command": "none", "sequence_name": None, "result_files": []}
        return {"command": hw.command_state(cur["name"]), "sequence_name": cur["name"],
                "result_files": [f.name for f in hw.result_files(cur["name"], cur["since"])]}

    def on_read(self, name: str):
        if name == "connected":
            try:
                self._hw()
                return True
            except DeviceFault:
                return False
        if name == "instrument_status":
            return self._status()
        if name == "busy":
            return self.is_busy
        if name == "robot_access_ready":
            return not self.is_busy
        if name == "last_result":
            return self.last_result
        raise InvalidValue(f"unknown signal {name}")

    def validate_params(self, action: str, params: dict) -> None:
        if action != "run_samples":
            return
        samples = params["samples"]
        if not samples:
            raise InvalidValue("run_samples.samples must hold at least one sample")
        max_lines = int(self.cfg.get("max_lines", 96))
        total = sum(int(s.get("injections", 1)) for s in samples)
        if total > max_lines:
            raise LimitViolation(f"run_samples has {total} injections; the maximum is {max_lines}", {"max": max_lines})
        lo, hi = self.cfg.get("injection_volume_ul", [0.1, 100])
        allowed = self.cfg.get("allowed_methods") or []
        for i, s in enumerate(samples):
            if not lo <= s["injection_volume_ul"] <= hi:
                raise LimitViolation(f"samples[{i}].injection_volume_ul={s['injection_volume_ul']} outside this sampler's {lo}..{hi}", {"min": lo, "max": hi})
            if allowed and s["method"] not in allowed:
                raise InvalidValue(f"samples[{i}].method {s['method']!r} is not in allowed_methods")
            for key in ("name", "vial", "method"):
                if not re.fullmatch(r"[^<>&/\\]+", s[key]):
                    raise InvalidValue(f"samples[{i}].{key} may not contain <, >, & or a path separator")
        sn = params.get("sequence_name")
        if sn is not None and not re.fullmatch(r"[A-Za-z0-9 _.\-]+", sn):
            raise InvalidValue("run_samples.sequence_name must be a plain file name (letters, digits, space, _ . -)")

    def on_invoke(self, job: Job):
        hw = self._hw()
        if job.action == "list_methods":
            return hw.methods()
        if job.action != "run_samples":
            raise InvalidValue(f"unhandled action {job.action}")
        p = job.params
        if self.current and hw.command_state(self.current["name"]) == "waiting":
            raise DeviceFault(f"the previous command {self.current['name']} is still waiting in the command folder; is Sample Scheduler running?")
        name = p.get("sequence_name") or f"mhp_{time.strftime('%Y%m%d_%H%M%S')}_{job.id}"
        lines = [{"name": s["name"], "vial": s["vial"], "injection_volume_ul": float(s["injection_volume_ul"]), "method": s["method"],
                  "processing_method": s.get("processing_method") or p.get("processing_method") or self.cfg.get("processing_method"),
                  "injections": int(s.get("injections", 1)), "result_name": name, "lims_id": job.id, "sample_type": s.get("sample_type", "Sample")}
                 for s in p["samples"]]
        n_inj = sum(l["injections"] for l in lines)
        started = time.time()
        scale = self.time_scale()
        self.current = {"name": name, "since": started - 1}
        path = hw.submit(name, lines)
        self.is_busy = True
        poll = float(self.cfg.get("poll_s", 15)) * scale
        limit = float(self.cfg.get("max_run_hours", 24)) * 3600 * scale
        accept_limit = float(self.cfg.get("accept_timeout_s", 300)) * scale
        expected = p.get("expected_run_min")
        t0, accepted_at, state, files = time.monotonic(), None, "waiting", []
        try:
            while True:
                self.checkpoint(job, 0.05 if accepted_at is None else min(0.95, 0.05 + 0.9 * (time.monotonic() - accepted_at) / max(1e-9, (expected or 20) * 60 * n_inj * scale)),
                                phase=state)
                state = hw.command_state(name)
                if state == "rejected":
                    raise DeviceFault(f"Sample Scheduler rejected {path} (moved to trash): a parameter is invalid for project "
                                      f"{self.cfg.get('project')} or instrument {self.cfg.get('instrument')}; check the method and vial names")
                if state == "accepted" and accepted_at is None:
                    accepted_at = time.monotonic()
                if state == "waiting" and time.monotonic() - t0 > accept_limit:
                    raise DeviceFault(f"{path} was not picked up within {accept_limit / scale:.0f} s; is Sample Scheduler running and watching this folder?",
                                      {"transient": True})
                files = hw.result_files(name, started - 1)
                if files:
                    time.sleep(min(2.0, 2 * scale) if scale < 1 else 2.0)   # let the copy finish
                    files = hw.result_files(name, started - 1)
                    break
                if accepted_at is not None and expected is not None and time.monotonic() - accepted_at > expected * 60 * n_inj * scale:
                    break
                if time.monotonic() - t0 > limit:
                    raise DeviceFault(f"no result for {name} after {self.cfg.get('max_run_hours', 24)} h")
                self.emit_signal("instrument_status", {"command": state, "sequence_name": name, "result_files": []})
                time.sleep(poll)
        finally:
            self.is_busy = False
        rows = []
        for f in files:
            try:
                rows += read_rows(f)
            except (OSError, csv.Error) as e:
                rows.append({"file": f.name, "error": f"{type(e).__name__}: {e}"})
        final = {"command": state, "sequence_name": name, "result_files": [f.name for f in files]}
        result = {"sequence_name": name, "command_file": path, "injections": n_inj, "samples": len(p["samples"]),
                  "final_status": final, "elapsed_s": round((time.time() - started) / scale, 1), "results": rows[:MAX_ROWS]}
        if not files:
            result["warning"] = ("no result file appeared in result_dir; the job ended on expected_run_min. Give the project a "
                                 "'Review for LIMS' report copy to the result folder for results to be returned")
        self.last_result = result
        self.emit_signal("last_result", result)
        return result

    # ---- setup-time check (`mhp node setup`) ---------------------------------------------- #
    @classmethod
    def probe(cls, cfg: dict) -> str:
        hw = SchedulerFolderBackend(cfg)
        hw.open()
        trash = pathlib.Path(cfg["command_dir"]) / "trash"
        return (f"command folder {cfg['command_dir']} is writable"
                + ("; its trash subfolder exists, so Sample Scheduler has used it" if trash.is_dir() else
                   "; no trash subfolder yet (Sample Scheduler creates it on the first invalid command)"))
