"""MHP driver for a Waters HPLC/UPLC under Empower 3, through the Empower Web API (opti-hplc-handler).

The vendor client sits behind EmpowerBackend so the simulated twin can replace it.
"""
from __future__ import annotations

import csv
import json
import pathlib
import re
import time

from openmhp.driver import DeviceFault, Driver, InvalidValue, Job, LimitViolation

HERE = pathlib.Path(__file__).parent
IDLE_WORDS = ("idle", "ready", "stopped", "not running")


def load_config() -> dict:
    p = HERE / "config.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


class EmpowerBackend:
    def __init__(self, cfg: dict):
        self.cfg = cfg

    def open(self) -> None:
        if not self.cfg.get("address"):
            raise DeviceFault("config.json is missing (copy config.example.json and fill it in)")
        from OptiHPLCHandler import EmpowerHandler
        self.h = EmpowerHandler(address=self.cfg["address"], project=self.cfg.get("project"),
                                service=self.cfg.get("service"), username=self.cfg.get("username"),
                                allow_login_without_context_manager=True, auto_login=False)
        if self.cfg.get("verify_tls") is False:
            self.h.connection.verify = False
        self.h.login()                                     # password from keyring ("Empower", username)

    def methods(self) -> dict:
        h = self.h
        return {"instrument_methods": h.GetMethodList(method_type="Instrument"),
                "method_sets": h.GetMethodList(method_type="MethodSetMethod"),
                "sample_set_methods": h.GetMethodList(method_type="SampleSet"),
                "plate_types": h.GetPlateTypeNames()}

    def status(self) -> dict:
        return self.h.GetStatus(node=self.cfg["node"], system=self.cfg["system"])

    def create_and_run(self, ssm_name: str, sample_list: list[dict], plates: dict, run_mode: str,
                       sample_set_name: str, comment: str | None) -> None:
        self.h.PostExperiment(sample_set_method_name=ssm_name, sample_list=sample_list, plates=plates,
                              audit_trail_message=comment)
        self.h.RunExperiment(sample_set_method=ssm_name, sample_set_name=sample_set_name, node=self.cfg["node"],
                             system=self.cfg["system"], run_mode=run_mode)


def is_idle(status: dict) -> bool:
    text = " ".join(f"{k}={v}" for k, v in (status or {}).items()).lower()
    if re.search(r"(acquir|running|inject|equilibrat|run in progress)", text):
        return False
    return any(w in text for w in IDLE_WORDS)


class EmpowerHPLC(Driver):
    def setup(self) -> None:
        self.cfg = load_config()
        self.hw = None
        self.is_busy = False
        self.last_result = None

    def make_backend(self):
        return EmpowerBackend(self.cfg)

    def time_scale(self) -> float:
        return 1.0

    def _hw(self):
        if self.hw is None:
            hw = self.make_backend()
            try:
                hw.open()
            except Exception as e:                         # noqa: BLE001
                raise DeviceFault(f"cannot log into the Empower Web API: {type(e).__name__}: {e}") from None
            self.hw = hw
        return self.hw

    def on_read(self, name: str):
        if name == "connected":
            try:
                self._hw()
                return True
            except DeviceFault:
                return False
        if name == "system_status":
            return self._hw().status()
        if name == "busy":
            return self.is_busy
        if name == "last_result":
            return self.last_result
        raise InvalidValue(f"unknown signal {name}")

    def validate_params(self, action: str, params: dict) -> None:
        if action != "run_samples":
            return
        samples = params.get("samples")
        cfg = self.cfg
        if not isinstance(samples, list) or not samples:
            raise InvalidValue("run_samples.samples must be a non-empty list")
        max_lines = int(cfg.get("max_lines", 96))
        if len(samples) > max_lines:
            raise LimitViolation(f"run_samples has {len(samples)} samples; the maximum is {max_lines}")
        lo, hi = cfg.get("injection_volume_ul", [0.1, 50])
        max_inj = int(cfg.get("max_injections_per_sample", 6))
        allowed = cfg.get("allowed_methods") or []
        for i, s in enumerate(samples):
            if not isinstance(s, dict):
                raise InvalidValue(f"samples[{i}] must be an object")
            unknown = set(s) - {"name", "vial", "injection_volume_ul", "method", "injections"}
            if unknown:
                raise InvalidValue(f"samples[{i}]: unknown keys {sorted(unknown)}")
            for k in ("name", "vial", "method"):
                if not isinstance(s.get(k), str) or not s[k].strip():
                    raise InvalidValue(f"samples[{i}].{k} must be a non-empty string")
            v = s.get("injection_volume_ul")
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not lo <= v <= hi:
                raise LimitViolation(f"samples[{i}].injection_volume_ul={v!r} outside {lo}..{hi}", {"min": lo, "max": hi})
            n = s.get("injections", 1)
            if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= max_inj:
                raise LimitViolation(f"samples[{i}].injections={n!r} outside 1..{max_inj}", {"min": 1, "max": max_inj})
            if allowed and s["method"] not in allowed:
                raise InvalidValue(f"samples[{i}].method {s['method']!r} is not in allowed_methods")
        if params.get("plates") is not None and not isinstance(params["plates"], dict):
            raise InvalidValue("run_samples.plates must be an object {position: plate type}")

    def _exported(self, since: float) -> list[dict]:
        folder = self.cfg.get("export_dir")
        if not folder or not pathlib.Path(folder).is_dir():
            return []
        rows = []
        for f in sorted(pathlib.Path(folder).glob("*")):
            if f.is_file() and f.stat().st_mtime >= since and f.suffix.lower() in (".csv", ".txt", ".tsv"):
                text = f.read_text(encoding="utf-8", errors="replace")
                dialect = "excel-tab" if text.count("\t") > text.count(",") else "excel"
                for r in csv.DictReader(text.splitlines(), dialect=dialect, restkey="_extra"):
                    rows.append({"file": f.name, **{str(k): v for k, v in r.items()}})
        return rows[:2000]

    def on_invoke(self, job: Job):
        hw = self._hw()
        if job.action == "list_methods":
            return hw.methods()
        if job.action != "run_samples":
            raise InvalidValue(f"unhandled action {job.action}")
        p = job.params
        status = hw.status()
        if not is_idle(status):
            raise DeviceFault(f"{self.cfg.get('system')} is not idle: {status}")
        ssm = f"mhp_{time.strftime('%Y%m%d_%H%M%S')}_{job.id}"
        name = p.get("sample_set_name") or ssm
        # one line per injection: repeat injections become repeated lines, so no Empower field name is assumed
        lines = [{"SampleName": s["name"], "SamplePos": s["vial"], "InjectionVolume": float(s["injection_volume_ul"]),
                  "Method": s["method"]} for s in p["samples"] for _ in range(int(s.get("injections", 1)))]
        started = time.time()
        plates = p.get("plates") or self.cfg.get("plates") or {}
        hw.create_and_run(ssm, lines, plates, p["run_mode"], name, p.get("audit_comment") or f"OpenMHP job {job.id}")
        self.is_busy = True
        poll = float(self.cfg.get("poll_s", 15)) * self.time_scale()
        limit = float(self.cfg.get("max_run_hours", 24)) * 3600 * self.time_scale()
        t0, seen_running, status = time.monotonic(), False, {}
        try:
            while True:
                self.checkpoint(job, phase="acquiring")
                status = hw.status()
                idle = is_idle(status)
                seen_running = seen_running or not idle
                if seen_running and idle:
                    break
                elapsed = time.monotonic() - t0
                if not seen_running and elapsed > 10 * poll + 30 * self.time_scale():
                    raise DeviceFault(f"sample set {name} did not start; Empower status: {status}")
                if elapsed > limit:
                    raise DeviceFault(f"sample set {name} still running after {self.cfg.get('max_run_hours', 24)} h")
                self.emit_signal("system_status", status)
                time.sleep(poll)
        finally:
            self.is_busy = False
        result = {"sample_set_method": ssm, "sample_set_name": name, "run_mode": p["run_mode"], "plates": plates,
                  "injections": len(lines), "samples": len(p["samples"]), "final_status": status,
                  "elapsed_s": round((time.time() - started) / self.time_scale(), 1),
                  "exported_rows": self._exported(started)}
        self.last_result = result
        self.emit_signal("last_result", result)
        return result
