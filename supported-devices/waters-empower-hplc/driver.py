"""MHP driver for a Waters HPLC/UPLC under Empower 3.

Two ways into Empower sit behind the same EmpowerBackend interface. "backend" in config.json picks one, or
"auto" (the default) takes the Toolkit when this PC has it and falls back to the Web API address otherwise:

- "web_api":  the Empower Web API over HTTPS, through opti-hplc-handler. Runs anywhere that reaches the
              API server. No abort, and results come only from an export method writing to export_dir.
- "toolkit":  the Empower Toolkit, Waters' licensed COM SDK installed with an Empower client. Runs on
              that client PC under 32-bit Python with pywin32. Can abort a sample set and fetch results.

The simulated twin replaces the backend, so everything above the interface is exercised without Empower.
"""
from __future__ import annotations

import concurrent.futures
import csv
import json
import pathlib
import queue
import re
import sys
import threading
import time

from openmhp.driver import DeviceFault, Driver, InvalidValue, Job, JobCancelled, LimitViolation

HERE = pathlib.Path(__file__).parent
IDLE_WORDS = ("idle", "ready", "stopped", "not running")
KEYRING_SERVICE = "Empower"                            # python -m keyring set Empower <username>


def load_config() -> dict:
    p = HERE / "config.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


class EmpowerBackend:
    """What the driver needs from Empower. Each sample set line is a dict with the keys SampleName,
    SamplePos, InjectionVolume and Method; the backend maps them onto its own field names."""

    name = "empower"
    can_abort = False                                  # True when abort() really stops the run in Empower

    def __init__(self, cfg: dict):
        self.cfg = cfg

    def open(self) -> None: ...
    def close(self) -> None: ...
    def methods(self) -> dict: ...
    def status(self) -> dict: ...

    def create_and_run(self, ssm_name: str, sample_list: list[dict], plates: dict, run_mode: str,
                       sample_set_name: str, comment: str | None) -> None: ...

    def abort(self) -> None:
        raise DeviceFault(f"the {self.name} backend cannot stop a running sample set; "
                          "a person stops it in Empower Run Samples")

    def results(self, sample_set_name: str) -> list[dict] | None:
        """Result rows for a finished sample set, or None when this route cannot read them."""
        return None


class WebApiBackend(EmpowerBackend):
    """Empower Web API through opti-hplc-handler (see references/web_api.md)."""

    name = "web_api"

    def open(self) -> None:
        if not self.cfg.get("address"):
            raise DeviceFault("config.json is missing or has no address (copy config.example.json and fill it in)")
        from OptiHPLCHandler import EmpowerHandler
        self.h = EmpowerHandler(address=self.cfg["address"], project=self.cfg.get("project"),
                                service=self.cfg.get("service"), username=self.cfg.get("username"),
                                allow_login_without_context_manager=True, auto_login=False)
        if self.cfg.get("verify_tls") is False:
            self.h.connection.verify = False
        self.h.login()                                     # password from keyring ("Empower", username)

    def close(self) -> None:
        try:
            self.h.logout()
        except Exception:                                  # noqa: BLE001
            pass

    def methods(self) -> dict:
        h = self.h
        return {"instrument_methods": h.GetMethodList(method_type="Instrument"),
                "method_sets": h.GetMethodList(method_type="MethodSetMethod"),
                "sample_set_methods": h.GetMethodList(method_type="SampleSet"),
                "plate_types": h.GetPlateTypeNames()}

    def status(self) -> dict:
        return self.h.GetStatus(node=self.cfg["node"], system=self.cfg["system"])

    def create_and_run(self, ssm_name, sample_list, plates, run_mode, sample_set_name, comment) -> None:
        self.h.PostExperiment(sample_set_method_name=ssm_name, sample_list=sample_list, plates=plates,
                              audit_trail_message=comment)
        self.h.RunExperiment(sample_set_method=ssm_name, sample_set_name=sample_set_name, node=self.cfg["node"],
                             system=self.cfg["system"], run_mode=run_mode)


class _ComThread:
    """Runs every Toolkit call on one thread that owns the COM apartment.

    pywin32 Dispatch objects belong to the thread that created them; the driver is called from the
    server's request threads and from job threads, so all Toolkit work is funnelled through here."""

    def __init__(self, name: str):
        self.q: queue.Queue = queue.Queue()
        self.t = threading.Thread(target=self._run, name=name, daemon=True)
        self.t.start()

    def _run(self) -> None:
        import pythoncom
        pythoncom.CoInitialize()
        try:
            while True:
                fn, fut = self.q.get()
                if fn is None:
                    return
                try:
                    fut.set_result(fn())
                except BaseException as e:                 # noqa: BLE001
                    fut.set_exception(e)
        finally:
            pythoncom.CoUninitialize()

    def call(self, fn, timeout: float = 120.0):
        fut: concurrent.futures.Future = concurrent.futures.Future()
        self.q.put((fn, fut))
        return fut.result(timeout=timeout)

    def stop(self) -> None:
        self.q.put((None, None))


# Toolkit run modes are an enumeration; the Web API takes the names. Both backends accept the names.
TOOLKIT_RUN_MODES = {"RunOnly": 0, "RunAndProcess": 1, "RunAndReport": 2}
TOOLKIT_LINE_FIELDS = {"SampleName": "SampleName", "SamplePos": "Vial", "InjectionVolume": "InjVol",
                       "Method": "MethodSetOrReportMethod"}
DEFAULT_RESULT_FIELDS = ["SampleName", "Vial", "Injection", "Name", "RetentionTime", "Area", "Height", "Amount"]


class ToolkitBackend(EmpowerBackend):
    """Empower Toolkit (COM) on an Empower client PC. See references/toolkit.md.

    Every Toolkit object and member this backend touches is named in the small methods below and
    nowhere else, so a release whose Programmer's Reference spells one differently is a one-line fix."""

    name = "toolkit"
    can_abort = True

    def open(self) -> None:
        cfg = self.cfg
        missing = [k for k in ("database", "project", "username", "node", "system") if not cfg.get(k)]
        if missing:
            raise DeviceFault(f"config.json is missing {', '.join(missing)} (needed by the toolkit backend)")
        try:
            import win32com.client  # noqa: F401
        except ImportError:
            raise DeviceFault("the toolkit backend needs pywin32 under 32-bit Python on an Empower client PC "
                              "(pip install pywin32)") from None
        import keyring
        password = keyring.get_password(KEYRING_SERVICE, cfg["username"])
        if not password:
            raise DeviceFault(f"no password in the keyring for {cfg['username']}: "
                              f"python -m keyring set {KEYRING_SERVICE} {cfg['username']}")
        self.prefix = cfg.get("toolkit_progid", "MillenniumToolkit")
        self.com = _ComThread("empower-toolkit")
        self.com.call(lambda: self._login(password))

    def close(self) -> None:
        try:
            self.com.call(self._logout, timeout=30)
        except Exception:                                  # noqa: BLE001
            pass
        self.com.stop()

    # ---- the Toolkit objects, one member per line ---------------------------------------------
    def _dispatch(self, obj: str):
        import win32com.client
        return win32com.client.Dispatch(f"{self.prefix}.{obj}")

    def _login(self, password: str) -> None:
        cfg = self.cfg
        self.login = self._dispatch("Login")
        self.login.Login(cfg["username"], password, cfg["database"])        # Login.Login(user, password, database)
        self.project = self._dispatch("Project")
        self.project.Login = self.login
        self.project.Open(cfg["project"])                                    # Project.Open(name)
        self.instrument = self._dispatch("Instrument")
        self.instrument.Login = self.login
        self.instrument.Connect(cfg["node"], cfg["system"])                  # Instrument.Connect(node, system)

    def _logout(self) -> None:
        try:
            self.instrument.Disconnect()
        finally:
            self.login.Logout()

    def _method_names(self, kind: str) -> list[str]:
        return [str(n) for n in self.project.GetMethodList(kind)]            # Project.GetMethodList(type)

    def _plate_types(self) -> list[str]:
        return [str(n) for n in self.project.GetPlateTypeList()]            # Project.GetPlateTypeList()

    def _status(self) -> dict:
        s = self.instrument.Status                                            # Instrument.Status -> string
        return {"SystemState": str(s), "CurrentSampleSet": str(getattr(self.instrument, "SampleSetName", "") or "")}

    def _create_ssm(self, ssm_name: str, lines: list[dict], plates: dict, comment: str | None) -> None:
        ssm = self._dispatch("SampleSetMethod")
        ssm.Project = self.project
        ssm.New()                                                             # SampleSetMethod.New()
        for pos, kind in (plates or {}).items():
            ssm.SetPlateType(str(pos), kind)                                  # SampleSetMethod.SetPlateType(pos, type)
        for row, line in enumerate(lines):
            ssm.AddRow("Inject Samples")                                      # SampleSetMethod.AddRow(function)
            for ours, theirs in TOOLKIT_LINE_FIELDS.items():
                ssm.SetField(row, theirs, line[ours])                         # SampleSetMethod.SetField(row, field, value)
        ssm.Save(ssm_name, comment or "")                                     # SampleSetMethod.Save(name, auditComment)

    def _run(self, ssm_name: str, sample_set_name: str, run_mode: str) -> None:
        mode = TOOLKIT_RUN_MODES.get(run_mode)
        if mode is None:
            raise InvalidValue(f"run_mode {run_mode!r} is not one of {sorted(TOOLKIT_RUN_MODES)}")
        self.instrument.RunSampleSet(ssm_name, sample_set_name, mode)        # Instrument.RunSampleSet(ssm, name, mode)

    def _abort(self) -> None:
        self.instrument.Abort()                                               # Instrument.Abort()

    def _fetch(self, sample_set_name: str, fields: list[str]) -> list[dict]:
        df = self._dispatch("DataFetch")
        df.Project = self.project
        df.Fields = ", ".join(fields)                                         # DataFetch.Fields
        df.Criteria = f"SampleSetName = '{sample_set_name}'"                  # DataFetch.Criteria
        df.Fetch()                                                            # DataFetch.Fetch()
        rows = []
        for r in range(int(df.RowCount)):                                     # DataFetch.RowCount / GetValue(row, field)
            rows.append({f: _plain(df.GetValue(r, f)) for f in fields})
        return rows

    # ---- the EmpowerBackend interface, all through the COM thread -------------------------------
    def methods(self) -> dict:
        return self.com.call(lambda: {"instrument_methods": self._method_names("Instrument"),
                                      "method_sets": self._method_names("MethodSet"),
                                      "sample_set_methods": self._method_names("SampleSet"),
                                      "plate_types": self._plate_types()})

    def status(self) -> dict:
        return self.com.call(self._status, timeout=30)

    def create_and_run(self, ssm_name, sample_list, plates, run_mode, sample_set_name, comment) -> None:
        self.com.call(lambda: self._create_ssm(ssm_name, sample_list, plates, comment))
        self.com.call(lambda: self._run(ssm_name, sample_set_name, run_mode))

    def abort(self) -> None:
        self.com.call(self._abort, timeout=30)

    def results(self, sample_set_name: str) -> list[dict] | None:
        fields = list(self.cfg.get("result_fields") or DEFAULT_RESULT_FIELDS)
        return self.com.call(lambda: self._fetch(sample_set_name, fields))[:2000]


BACKENDS = {"web_api": WebApiBackend, "toolkit": ToolkitBackend}


def toolkit_installed(prefix: str = "MillenniumToolkit") -> bool:
    """True on a Windows PC where the Toolkit's COM classes are registered (an Empower client with the option)."""
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, f"{prefix}.Login"):
            return True
    except OSError:
        return False


def choose_backend(cfg: dict) -> tuple[str, str]:
    """Which route to Empower, and why. backend: "web_api" | "toolkit" chooses; "auto" (or nothing) picks the
    Toolkit when this PC has it and config names the database, else the Web API when it has an address."""
    kind = str(cfg.get("backend") or "auto")
    if kind != "auto":
        if kind not in BACKENDS:
            raise DeviceFault(f"config.json backend={kind!r}; choose auto or one of {sorted(BACKENDS)}")
        return kind, "set in config.json"
    installed = toolkit_installed(cfg.get("toolkit_progid", "MillenniumToolkit"))
    if installed and cfg.get("database"):
        return "toolkit", "the Empower Toolkit is installed on this PC"
    if cfg.get("address"):
        why = "no Toolkit on this PC" if not installed else "the Toolkit is installed but config.json has no database"
        return "web_api", f"{why}; config.json has a Web API address"
    if installed:
        raise DeviceFault("the Empower Toolkit is installed here but config.json has no database; set database "
                          "(the Empower database name) to use it, or address to use the Web API")
    raise DeviceFault("no route to Empower: this PC has no Empower Toolkit and config.json has no Web API address "
                      "(copy config.example.json and fill in address, or run this on an Empower client PC with the Toolkit)")


def _plain(v):
    """COM values as JSON-friendly Python."""
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return str(v)


def is_idle(status: dict) -> bool:
    text = " ".join(f"{k}={v}" for k, v in (status or {}).items()).lower()
    if re.search(r"(acquir|running|inject|equilibrat|run in progress)", text):
        return False
    return any(w in text for w in IDLE_WORDS)


class EmpowerHPLC(Driver):
    def setup(self) -> None:
        self.cfg = load_config()
        self.hw = None
        self.chosen = {"name": None, "reason": "not connected yet"}
        self.is_busy = False
        self.last_result = None

    def make_backend(self) -> EmpowerBackend:
        kind, why = choose_backend(self.cfg)
        self.chosen = {"name": kind, "reason": why}
        return BACKENDS[kind](self.cfg)

    def time_scale(self) -> float:
        return 1.0

    def _open(self, hw: EmpowerBackend) -> None:
        try:
            hw.open()
        except DeviceFault:
            raise
        except Exception as e:                             # noqa: BLE001
            raise DeviceFault(f"cannot connect to Empower through the {hw.name} backend: "
                              f"{type(e).__name__}: {e}") from None

    def _hw(self) -> EmpowerBackend:
        if self.hw is None:
            hw = self.make_backend()
            try:
                self._open(hw)
            except DeviceFault as e:
                # auto-chosen Toolkit that will not log in, on a PC that also has a Web API address: use that,
                # and say so in the backend signal rather than failing the lab over the better route
                if hw.name == "toolkit" and self.cfg.get("backend", "auto") not in BACKENDS and self.cfg.get("address"):
                    hw = WebApiBackend(self.cfg)
                    self._open(hw)
                    self.chosen = {"name": "web_api", "reason": f"the Toolkit was found but did not connect ({e}); "
                                                                 "using the Web API address instead"}
                else:
                    raise
            self.hw = hw
        return self.hw

    def on_read(self, name: str):
        if name == "connected":
            try:
                self._hw()
                return True
            except DeviceFault:
                return False
        if name == "backend":
            if self.hw is None:
                try:
                    self._hw()
                except DeviceFault as e:
                    try:
                        kind, why = choose_backend(self.cfg)
                    except DeviceFault as e2:
                        return {"name": None, "can_abort": False, "connected": False, "reason": str(e2)}
                    return {"name": kind, "can_abort": BACKENDS[kind].can_abort, "connected": False,
                            "reason": f"{why}; not connected: {e}"}
            return {"name": self.hw.name, "can_abort": bool(self.hw.can_abort), "connected": True,
                    "reason": self.chosen["reason"]}
        if name == "system_status":
            return self._hw().status()
        if name == "busy":
            return self.is_busy
        if name == "robot_access_ready":
            return not self.is_busy                        # vials may be loaded while no sample set from here runs
        if name == "last_result":
            return self.last_result
        raise InvalidValue(f"unknown signal {name}")

    def on_estop(self) -> None:
        """Best effort: a backend that can abort does; the Web API cannot, and the base reports stopped: false."""
        if self.hw is not None and self.hw.can_abort:
            self.hw.abort()

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

    def _results(self, hw: EmpowerBackend, name: str, since: float, run_mode: str) -> tuple[str | None, list[dict]]:
        """Rows from the backend when it can read them, else from the export folder."""
        if run_mode != "RunOnly":
            try:
                rows = hw.results(name)
            except Exception as e:                         # noqa: BLE001
                rows = [{"error": f"{type(e).__name__}: {e}"}]
            if rows is not None:
                return hw.name, rows
        exported = self._exported(since)
        return ("export_dir" if exported else None), exported

    def _wait_idle(self, job: Job | None, hw: EmpowerBackend, name: str, poll: float, limit: float,
                   seen_running: bool = False) -> dict:
        """Poll until the system has been seen running and is idle again. Returns the last status."""
        t0, status = time.monotonic(), {}
        while True:
            if job is not None:
                self.checkpoint(job, phase="acquiring")
            status = hw.status()
            idle = is_idle(status)
            seen_running = seen_running or not idle
            if seen_running and idle:
                return status
            elapsed = time.monotonic() - t0
            if not seen_running and elapsed > 10 * poll + 30 * self.time_scale():
                raise DeviceFault(f"sample set {name} did not start; Empower status: {status}")
            if elapsed > limit:
                raise DeviceFault(f"sample set {name} still running after {self.cfg.get('max_run_hours', 24)} h")
            self.emit_signal("system_status", status)
            time.sleep(poll)

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
        try:
            try:
                status = self._wait_idle(job, hw, name, poll, limit)
            except JobCancelled:
                if not hw.can_abort:
                    raise DeviceFault(f"cancel requested but the {hw.name} backend cannot stop sample set {name}; "
                                      "it is still running in Empower. Stop it in Run Samples, then safety/reset") from None
                hw.abort()                                 # honoured: Empower aborts, we wait until it says so
                self._wait_idle(None, hw, name, poll, 10 * poll + 60 * self.time_scale(), seen_running=True)
                raise
        finally:
            self.is_busy = False
        source, rows = self._results(hw, name, started, p["run_mode"])
        result = {"sample_set_method": ssm, "sample_set_name": name, "run_mode": p["run_mode"], "plates": plates,
                  "injections": len(lines), "samples": len(p["samples"]), "final_status": status,
                  "elapsed_s": round((time.time() - started) / self.time_scale(), 1),
                  "backend": hw.name, "results_from": source, "result_rows": rows,
                  "exported_rows": rows if source == "export_dir" else []}
        self.last_result = result
        self.emit_signal("last_result", result)
        return result

    # ---- setup-time checks (`mhp node setup`): no driver instance, nothing moves ------------ #
    @classmethod
    def discover(cls, cfg: dict, what: str) -> list:
        hw = EmpowerBackend(cfg)
        hw.open()
        if what == "nodes" and hasattr(hw.h, "GetNodeNames"):
            return list(hw.h.GetNodeNames())
        if what == "systems" and cfg.get("node") and hasattr(hw.h, "GetSystemNames"):
            return list(hw.h.GetSystemNames(node=cfg["node"]))
        return []

    @classmethod
    def probe(cls, cfg: dict) -> str:
        hw = EmpowerBackend(cfg)
        try:
            hw.open()
        except ImportError:
            raise DeviceFault("opti-hplc-handler is not installed (pip install opti-hplc-handler)") from None
        except Exception as e:                               # noqa: BLE001
            raise DeviceFault(f"cannot log into {cfg.get('address')} as {cfg.get('username')}: {type(e).__name__}: {e}") from None
        status = hw.status()
        return f"Empower at {cfg.get('address')} answers; {cfg.get('system')} is {'idle' if is_idle(status) else 'busy'}"
