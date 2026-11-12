"""MHP driver (template) for an Instron 3400/5900/6800 under Bluehill Universal through the Bluehill Universal API.

Instron documents the API only by name and mechanism (included with the standard licence; a Windows Communication
Foundation service reachable from .NET, C#, VB "or any language that connects to WCF"; documented uses: import
specimen inputs, open a method and start a test, export results). No member name is public, so InstronBackend
is written against the shape such an API must have; every member is read from config.json `api` and marked
`# unverified`. Results come from the results-table CSV export Bluehill writes at the end of a test (layout
from Bluehill 3-era exports: parameter rows, a blank row, a names row, a units row, one row per specimen).
The twin runs the same driver against a fake frame. See references/bluehill_api.md.
"""
from __future__ import annotations

import csv
import io
import json
import pathlib
import re
import time

from openmhp.driver import DeviceFault, Driver, InvalidValue, Job, JobCancelled, LimitViolation

HERE = pathlib.Path(__file__).parent
_PLAIN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.\-]{0,63}$")
API_DEFAULTS = {"assembly": "BluehillWCF", "client": "Instron.Bluehill.Api.BluehillApiClient", "connect": "Connect",
                "heartbeat": "APIHeartbeat", "open_method": "OpenMethod", "set_input": "SetSpecimenInput",
                "set_rate": "SetTestRate", "set_limit": "SetTestLimit", "start": "StartTest", "stop": "StopTest",
                "disable_frame": "DisableFrame", "frame_mode": "FrameMode", "crosshead": "CrossheadStatus",
                "load": "Load", "extension": "Extension", "test_running": "IsTestRunning", "end_reason": "TestEndReason"}
COLUMN_DEFAULTS = {"peak_load": "Maximum Force", "modulus": "Modulus (Automatic Young's)",
                   "stress_at_peak": "Tensile stress at Maximum Force", "strain_at_break": "Tensile strain at Break",
                   "extension_at_break": "Extension at Break"}
CROSSHEAD_STATES = {"disabled": "disabled", "setup": "ready", "caution": "ready", "testing": "testing", "moving": "moving",
                    "stopped": "stopped", "limit": "at_limit"}


def load_config() -> dict:
    p = HERE / "config.json"
    return json.loads(p.read_text(encoding="utf-8") or "{}") if p.is_file() else {}


def _num(s: str):
    s = (s or "").strip().replace(",", ".") if (s or "").count(",") == 1 and "." not in (s or "") else (s or "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def parse_results_csv(text: str, columns: dict, label: str | None = None) -> dict:
    """Bluehill results-table export: optional `parameter,value,unit` rows, a blank row, a names row, a units row,
    one row per specimen. Returns the named columns of the specimen row with `label` (else the last row)."""
    rows = list(csv.reader(io.StringIO(text)))
    names_i = next((i for i, r in enumerate(rows) if columns["peak_load"] in [c.strip() for c in r]), None)
    if names_i is None:
        raise DeviceFault(f"results export has no column {columns['peak_load']!r} (columns in config.json)",
                          {"transient": False, "recovery": "operator"})
    names = [c.strip() for c in rows[names_i]]
    units_i = names_i + 1 if names_i + 1 < len(rows) and all(_num(c) is None for c in rows[names_i + 1] if c.strip()) else None
    data = [r for r in rows[(units_i if units_i is not None else names_i) + 1:] if any(c.strip() for c in r)]
    if not data:
        raise DeviceFault("results export holds no specimen row", {"transient": True, "recovery": "retry_after"})
    row = data[-1]
    if label:
        row = next((r for r in data if r and r[0].strip() == label), row)
    rec = dict(zip(names, row))
    out = {}
    for key, col in columns.items():
        out[key] = _num(rec.get(col, "")) if col in rec else None
    return out


class InstronBackend:
    """Every Bluehill API call. The assembly, client class and member names are configuration because none could
    be verified against a public reference."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.api = {**API_DEFAULTS, **(cfg.get("api") or {})}
        self.client = None
        self.log: list[str] = []

    def _m(self, key: str):
        return getattr(self.client, self.api[key])

    def open(self) -> None:
        if not self.cfg.get("endpoint") or not self.cfg.get("outputs_dir"):
            raise DeviceFault("config.json is missing endpoint/outputs_dir (copy config.example.json and fill it in)",
                              {"transient": False, "recovery": "operator"})
        import clr                                               # pythonnet, Windows
        clr.AddReference(self.api["assembly"])                   # unverified assembly name
        import importlib
        mod, _, cls = self.api["client"].rpartition(".")
        self.client = getattr(importlib.import_module(mod), cls)(self.cfg["endpoint"])   # unverified class
        self._m("connect")()                                     # unverified
        if not bool(self._m("heartbeat")()):                     # APIHeartbeat: seen for the Bluehill 3 WCF API, unverified for Universal
            raise DeviceFault("Bluehill's API heartbeat answered false (is Bluehill Universal running with the API enabled?)",
                              {"transient": True, "recovery": "retry_after"})

    def frame_mode(self) -> str:
        return str(self._m("frame_mode")).lower()               # unverified property: DISABLED / SETUP / CAUTION / TESTING

    def crosshead(self) -> str:
        return str(self._m("crosshead")).lower()                 # unverified property

    def load(self) -> float:
        return float(self._m("load"))                            # unverified property (N)

    def extension(self) -> float:
        return float(self._m("extension"))                       # unverified property (mm)

    def test_running(self) -> bool:
        return bool(self._m("test_running"))                     # unverified property

    def end_reason(self) -> str:
        return str(self._m("end_reason") or "finished").lower()  # unverified property

    def start_test(self, method: str, sample_name: str, specimen: dict, rate: float, limits: dict) -> None:
        self._m("open_method")(str(pathlib.PureWindowsPath(self.cfg.get("methods_dir") or "") / method))   # unverified
        self._m("set_input")("Sample name", sample_name)         # unverified: input naming
        self._m("set_input")("Specimen label", specimen["label"])
        for key, inp in (("width_mm", "Width"), ("thickness_mm", "Thickness"), ("gauge_length_mm", "Gauge length")):
            if specimen.get(key) is not None:
                self._m("set_input")(inp, float(specimen[key]))  # unverified input names
        self._m("set_rate")(float(rate))                         # unverified (mm/min)
        self._m("set_limit")("Force", float(limits["max_load_N"]))            # unverified
        self._m("set_limit")("Displacement", float(limits["max_extension_mm"]))
        self._m("start")()                                       # unverified; on a 3400/6800 the frame's Start key may still be required

    def stop(self) -> None:
        self._m("stop")()                                        # unverified

    def disable_frame(self) -> None:
        self._m("disable_frame")()                               # unverified

    def export_paths(self, sample_name: str) -> tuple[pathlib.Path | None, pathlib.Path | None]:
        out = pathlib.Path(self.cfg["outputs_dir"])
        res = out / (sample_name + self.cfg.get("results_suffix", "_Results.csv"))
        raw_suffix = self.cfg.get("raw_suffix")
        raw = out / (sample_name + raw_suffix) if raw_suffix else None
        return (res if res.is_file() else None), (raw if raw and raw.is_file() else None)


class InstronBluehill(Driver):
    def setup(self) -> None:
        self.cfg = load_config()
        self.hw = None
        self.testing = False
        self.last_result = None

    def make_backend(self):
        return InstronBackend(self.cfg)

    def time_scale(self) -> float:
        return 1.0

    def _hw(self) -> InstronBackend:
        if self.hw is None:
            hw = self.make_backend()
            try:
                hw.open()
            except DeviceFault:
                raise
            except ImportError:
                raise DeviceFault("pythonnet (clr) is not installed or the Bluehill API assembly was not found",
                                  {"transient": False, "recovery": "operator"}) from None
            except Exception as e:                               # noqa: BLE001  vendor boundary
                raise DeviceFault(f"cannot open the Bluehill API: {type(e).__name__}: {e}", {"transient": True, "recovery": "retry_after"}) from None
            self.hw = hw
        return self.hw

    def _vendor(self, what: str, fn):
        try:
            return fn()
        except (DeviceFault, InvalidValue, JobCancelled):
            raise
        except Exception as e:                                   # noqa: BLE001  vendor boundary
            raise DeviceFault(f"Bluehill {what} failed: {type(e).__name__}: {e}", {"transient": True, "recovery": "retry_after"}) from None

    def _crosshead_state(self) -> str:
        hw = self._hw()
        mode = self._vendor("frame_mode", hw.frame_mode)
        if mode == "disabled":
            return "disabled"
        if self._vendor("test_running", hw.test_running):
            return "testing"
        ch = self._vendor("crosshead", hw.crosshead)
        if "limit" in ch:
            return "at_limit"
        if "moving" in ch:
            return "moving"
        return "ready" if mode in ("setup", "set up", "caution") else CROSSHEAD_STATES.get(ch, "stopped")

    def on_read(self, name: str):
        if name == "connected":
            try:
                self._hw()
                return True
            except DeviceFault:
                return False
        if name == "load":
            return round(self._vendor("load", self._hw().load), 3)
        if name == "extension":
            return round(self._vendor("extension", self._hw().extension), 4)
        if name == "crosshead_state":
            return self._crosshead_state()
        if name == "frame_ready":
            return self._crosshead_state() == "ready"
        if name == "last_result":
            return self.last_result
        raise InvalidValue(f"unknown signal {name}")

    def validate_params(self, action: str, params: dict) -> None:
        if action != "run_test":
            return
        m = str(params.get("bluehill_method", ""))
        if "/" in m or "\\" in m or ".." in m or not m.strip():
            raise InvalidValue("bluehill_method must be a bare file name in methods_dir")
        allowed = self.cfg.get("allowed_methods") or []
        if allowed and m not in allowed:
            raise InvalidValue(f"bluehill_method {m!r} is not in allowed_methods")
        if not _PLAIN.match(str(params["specimen"].get("label", ""))):
            raise InvalidValue("specimen.label must be letters, digits, spaces, underscore, hyphen or dot (it names the export)")
        lim = params["limits"]
        cell = self.cfg.get("load_cell_N")
        if cell and lim["max_load_N"] > float(cell):
            raise LimitViolation(f"limits.max_load_N {lim['max_load_N']} exceeds the fitted load cell ({cell} N, config.json load_cell_N)",
                                 {"max": float(cell)})

    def on_invoke(self, job: Job):
        hw = self._hw()
        if job.action == "stop_crosshead":
            self._vendor("stop", hw.stop)
            hw.log.append("stop_crosshead")
            return {"stopped": True}
        if job.action != "run_test":
            raise InvalidValue(f"unhandled action {job.action}")
        p = job.params
        if self._crosshead_state() != "ready":
            raise DeviceFault(f"the frame is {self._crosshead_state()}, not ready: enable it at the panel or wait for the running test",
                              {"transient": True, "recovery": "operator"})
        token = f"mhp_{time.strftime('%Y%m%d')}_{job.id.replace('job_', '')}"
        sample_name = f"{p['specimen']['label']}_{token}"
        started = time.time()
        self._vendor("start_test", lambda: hw.start_test(p["bluehill_method"], sample_name, p["specimen"], p["rate_mm_min"], p["limits"]))
        hw.log.append(f"start {p['bluehill_method']} {sample_name} rate {p['rate_mm_min']} limits {p['limits']}")
        self.testing = True
        scale = self.time_scale()
        poll = float(self.cfg.get("poll_s", 1)) * scale
        limit = float(self.cfg.get("max_test_minutes", 60)) * 60 * scale
        est = (p["limits"]["max_extension_mm"] / p["rate_mm_min"] * 60) * scale
        t0 = time.monotonic()
        try:
            time.sleep(min(0.5, 2 * scale))
            while self._vendor("test_running", hw.test_running):
                try:
                    self.checkpoint(job, min(0.95, (time.monotonic() - t0) / max(est, 1e-6)), phase="testing",
                                    load_N=round(self._vendor("load", hw.load), 2), extension_mm=round(self._vendor("extension", hw.extension), 3))
                except JobCancelled:
                    self._vendor("stop", hw.stop)
                    hw.log.append("cancel: stop")
                    raise
                if time.monotonic() - t0 > limit:
                    self._vendor("stop", hw.stop)
                    raise DeviceFault(f"test still running after {limit / scale / 60:.0f} min (max_test_minutes); crosshead stopped",
                                      {"transient": False, "recovery": "operator"})
                time.sleep(poll)
            reason = self._vendor("end_reason", hw.end_reason)
        finally:
            self.testing = False
        deadline = time.monotonic() + 30 * scale
        res_path = raw_path = None
        while res_path is None and time.monotonic() < deadline:          # Bluehill writes the export at finish
            res_path, raw_path = hw.export_paths(sample_name)
            if res_path is None:
                time.sleep(min(poll, 0.5 * scale))
        if res_path is None:
            raise DeviceFault(f"no {sample_name}{self.cfg.get('results_suffix', '_Results.csv')} in {self.cfg.get('outputs_dir')}: "
                              "is the method's export enabled (results table, CSV, at finish, named by sample)?",
                              {"transient": True, "recovery": "retry_after"})
        cols = {**COLUMN_DEFAULTS, **(self.cfg.get("columns") or {})}
        vals = parse_results_csv(res_path.read_text(encoding="utf-8-sig", errors="replace"), cols, p["specimen"]["label"])
        if vals.get("peak_load") is None:
            raise DeviceFault(f"{res_path.name} has no numeric {cols['peak_load']!r} for this specimen", {"transient": False, "recovery": "operator"})
        result = {"specimen_id": p["specimen"]["label"], "file": str(res_path), "raw_file": str(raw_path) if raw_path else None,
                  "peak_load_N": vals["peak_load"], "modulus_MPa": vals.get("modulus"), "stress_at_peak_MPa": vals.get("stress_at_peak"),
                  "strain_at_break": vals.get("strain_at_break"), "extension_at_break_mm": vals.get("extension_at_break"),
                  "end_reason": reason, "duration_s": round((time.time() - started) / scale, 1)}
        self.last_result = result
        self.emit_signal("last_result", result)
        return result

    def on_estop(self) -> None:
        try:
            if self.hw is not None:
                self.hw.stop()
                self.hw.disable_frame()
                self.hw.log.append("estop: stop crosshead, disable frame")
        except Exception:                                        # noqa: BLE001  must not raise
            pass
        self.testing = False

    @classmethod
    def discover(cls, cfg: dict, what: str) -> list:
        if what == "methods" and cfg.get("methods_dir") and pathlib.Path(cfg["methods_dir"]).is_dir():
            return sorted(f.name for f in pathlib.Path(cfg["methods_dir"]).glob("*.im_*"))
        return []

    @classmethod
    def probe(cls, cfg: dict) -> str:
        import sys
        if sys.platform != "win32":
            raise DeviceFault("the Bluehill Universal API is a WCF service on the Bluehill PC; this is not Windows")
        hw = InstronBackend(cfg)
        hw.open()
        return f"Bluehill API answers; frame mode {hw.frame_mode()}"
