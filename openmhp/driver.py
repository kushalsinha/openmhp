"""MHP driver base class.

A driver is an MHP *server*: it owns one physical device and exposes it through
the five MHP primitives:

    describe   - the device descriptor (identity, physics, notes, capabilities)
    signals    - things you can READ   (temperature, position, lid state ...)
    settings   - things you can WRITE  (setpoints, speeds, modes ...)
    actions    - things you can INVOKE (run protocol, home, move to ...) -> jobs
    safety     - limits, interlocks, approval levels, e-stop, watchdog

Vendor code lives in a few hooks: ``on_read``, ``on_write``, ``on_invoke``,
``on_estop``, and optionally ``validate_params`` (side-effect free, used by dry
runs and real runs alike) and ``on_fault``. Everything else - typed validation,
limits, interlocks, leases, the watchdog, job tracking and the state machine -
is handled here so that every MHP device behaves the same way.

Error handling contract for vendor hooks:
  * raise an MHPError subclass (InvalidValue, LimitViolation, ...) to reject a
    request BEFORE anything was sent to the device; the device state is unchanged.
  * any other exception means the outcome is unknown: the driver latches `fault`,
    runs ``on_fault`` to reach a safe state, and refuses actuation until a
    verified ``safety/reset``.
"""
from __future__ import annotations

import math
import threading
import time
import uuid
import weakref
from dataclasses import dataclass, field
from typing import Any, Callable

from . import PROTOCOL_VERSION


# --------------------------------------------------------------------------- #
# Errors (JSON-RPC error codes reserved by MHP in the -32000..-32099 range)
# --------------------------------------------------------------------------- #
class MHPError(Exception):
    code = -32000

    def __init__(self, message: str, data: Any = None):
        super().__init__(message)
        self.message = message
        self.data = data


class MethodNotFound(MHPError):        code = -32601
class LimitViolation(MHPError):        code = -32010
class InterlockOpen(MHPError):         code = -32011
class ApprovalRequired(MHPError):      code = -32012
class Forbidden(MHPError):             code = -32013
class InvalidValue(MHPError):          code = -32014
class MethodRequired(MHPError):        code = -32015
class DeviceFault(MHPError):           code = -32020
class DeviceBusy(MHPError):            code = -32021
class EStopActive(MHPError):           code = -32022
class NotLeased(MHPError):             code = -32030
class UnknownName(MHPError):           code = -32040
class JobNotFound(MHPError):           code = -32041
class NotSupported(MHPError):          code = -32050


class JobCancelled(Exception):
    """Raised inside on_invoke by checkpoint() when a job was cancelled; not an error."""


TERMINAL = ("done", "failed", "cancelled")


def _digest(value) -> str:
    import hashlib
    import json
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:12]
_TYPES = {"number", "integer", "boolean", "string", "object", "array"}
_NOTED_DRY_RUN_LEASE = "needsLease"


# --------------------------------------------------------------------------- #
# Jobs: the result of invoking an action
# --------------------------------------------------------------------------- #
@dataclass
class Job:
    id: str
    action: str
    params: dict
    owner: str | None = None
    state: str = "queued"           # queued | running | waiting_operator | done | failed | cancelled
    progress: float = 0.0
    result: Any = None
    error: str | None = None
    outcome: str | None = None      # "unknown" when a failure may have left the device in an unknown physical state
    waiting: str | None = None      # what the job is waiting for (e.g. an operator instruction)
    method: dict | None = None      # {name, version, hash, overrides?} when the job runs a saved method
    project: str | None = None      # the project this run belongs to, when the caller said
    started: float = field(default_factory=time.time)
    finished: float | None = None
    cancel_requested: bool = False
    paused: bool = False

    def snapshot(self) -> dict:
        return {
            "id": self.id, "action": self.action, "state": self.state, "paused": self.paused,
            "progress": round(self.progress, 3), "result": self.result, "error": self.error,
            "outcome": self.outcome, "waiting": self.waiting, "owner": self.owner,
            "method": self.method, "project": self.project,
            "started": self.started, "finished": self.finished,
        }


# --------------------------------------------------------------------------- #
# Value validation (shared by settings and action parameters)
# --------------------------------------------------------------------------- #
def _has_control_chars(s: str) -> bool:
    return any(ord(c) < 0x20 or ord(c) == 0x7F for c in s)


def reject_control_chars(value: Any, where: str) -> None:
    """Strings sent toward a device must not carry command delimiters (CR, LF, NUL, ...)."""
    if isinstance(value, str):
        if _has_control_chars(value):
            raise InvalidValue(f"{where}: control characters are not allowed in values")
    elif isinstance(value, dict):
        for k, v in value.items():
            reject_control_chars(k, where)
            reject_control_chars(v, f"{where}.{k}")
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            reject_control_chars(v, f"{where}[{i}]")


def is_finite_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def check_type(where: str, typ: str, value: Any) -> None:
    if value is None:
        raise InvalidValue(f"{where}: a value is required (null is not allowed)")
    if typ not in _TYPES:
        raise InvalidValue(f"{where}: the descriptor declares unknown type {typ!r}")
    ok = {
        "number": is_finite_number(value),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "string": isinstance(value, str),
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
    }[typ]
    if not ok:
        extra = " (must be finite)" if typ == "number" and isinstance(value, float) else ""
        raise InvalidValue(f"{where}: expected {typ}{extra}, got {type(value).__name__} {value!r}", {"type": typ})
    reject_control_chars(value, where)


def check_bounds(where: str, value: Any, bound: Any) -> None:
    """bound: [min, max] | {min, max} | {enum: [...]}; list values are checked element-wise."""
    if isinstance(bound, dict) and "enum" in bound:
        values = value if isinstance(value, list) else [value]
        for v in values:
            if v not in bound["enum"]:
                raise LimitViolation(f"{where}={v!r} not in {bound['enum']}", bound)
        return
    if isinstance(bound, (list, tuple)) and len(bound) == 2:
        lo, hi = bound
    elif isinstance(bound, dict):
        lo, hi = bound.get("min"), bound.get("max")
    else:
        raise InvalidValue(f"{where}: malformed limits {bound!r} in the descriptor")
    values = value if isinstance(value, list) else [value]
    for v in values:
        if not is_finite_number(v):
            raise InvalidValue(f"{where}: expected a finite number, got {v!r}", {"min": lo, "max": hi})
        if lo is not None and v < lo:
            raise LimitViolation(f"{where}={v} below min {lo}", {"min": lo, "max": hi})
        if hi is not None and v > hi:
            raise LimitViolation(f"{where}={v} above max {hi}", {"min": lo, "max": hi})


# --------------------------------------------------------------------------- #
# Watchdog: one scheduler thread for every driver that declares safety.watchdog_s
# --------------------------------------------------------------------------- #
class _WatchdogScheduler:
    def __init__(self):
        self._drivers: "weakref.WeakSet[Driver]" = weakref.WeakSet()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def register(self, drv: "Driver") -> None:
        with self._lock:
            self._drivers.add(drv)
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._loop, name="mhp-watchdog", daemon=True)
                self._thread.start()

    def unregister(self, drv: "Driver") -> None:
        with self._lock:
            self._drivers.discard(drv)

    def _loop(self) -> None:
        while True:
            with self._lock:
                drivers = list(self._drivers)
            interval = 0.25
            for d in drivers:
                wd = d.watchdog_s
                if wd and d.lease is not None:
                    interval = min(interval, wd / 4)
                    d._watchdog_check()
            time.sleep(max(0.005, interval))


_WATCHDOGS = _WatchdogScheduler()

# Methods that never wait behind device I/O: stopping, status and lease bookkeeping.
_UNLOCKED = {"safety/estop", "ping", "jobs/status", "jobs/list", "jobs/cancel", "jobs/pause",
             "session/acquire", "session/renew", "session/release", "device/describe", "safety/limits",
             "signals/list", "settings/list", "actions/list", "resources/list", "resources/read", "initialize",
             "methods/list", "methods/get", "methods/find", "methods/diff"}


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #
class Driver:
    """Subclass this. Set ``descriptor`` and implement the vendor hooks."""

    descriptor: dict = {}
    package_dir: str | None = None            # set to a device package folder to load descriptor + instructions
    instructions: str = ""                    # Level 2: DEVICE.md body
    package = None                            # DevicePackage, when loaded from a folder

    def __init__(self):
        self.state = "idle"                       # idle | busy | fault | estop
        self.fault_reason: str | None = None
        self.lease: str | None = None             # session id holding control
        self.lease_expires: float = 0.0           # time.monotonic() deadline
        self.jobs: dict[str, Job] = {}
        self._active: set[str] = set()
        self.subscribers: list[Callable[[dict], None]] = []
        self._lock = threading.RLock()            # serialises vendor I/O for ordinary requests
        self._state_lock = threading.RLock()      # short critical sections: state, jobs, lease
        self._last_seen: dict[str, float] = {}
        self._closed = False
        self._methods = None
        if self.package_dir and self.package is None:
            from .package import load_package
            self.attach_package(load_package(self.package_dir))
        self._reindex()
        self.setup()
        self._arm_watchdog()

    def _reindex(self):
        self._index = {
            "signals":  {s["name"]: s for s in self.descriptor.get("signals", [])},
            "settings": {s["name"]: s for s in self.descriptor.get("settings", [])},
            "actions":  {a["name"]: a for a in self.descriptor.get("actions", [])},
        }

    def attach_package(self, pkg) -> None:
        """Use a DevicePackage as this driver's descriptor, instructions and resources."""
        self.package = pkg
        self.descriptor = pkg.descriptor
        self.instructions = pkg.instructions
        self._reindex()
        if hasattr(self, "_state_lock"):
            self._arm_watchdog()

    def close(self) -> None:
        """Stop background supervision for this instance (used when a device is removed or reloaded)."""
        self._closed = True
        _WATCHDOGS.unregister(self)

    # ---- methods: SPEC §4.5, a primitive on every device ----------------------- #
    methods_dir: str | None = None            # a driver without a package may pin the store

    def method_driven(self) -> list[str]:
        """M1: the actions declared with `methods: true`."""
        return [n for n, a in self._index["actions"].items() if a.get("methods") is True]

    @property
    def methods(self):
        if self._methods is None:
            import os
            from pathlib import Path
            from .methods import MethodStore
            if self.methods_dir:
                root = Path(self.methods_dir)
            elif self.package is not None:
                root = Path(self.package.dir) / "methods"                          # M2: Level 3 of the package
            else:
                home = Path(os.environ.get("OPENMHP_HOME", Path.home() / ".openmhp"))
                root = home / "methods" / str(self.descriptor["device"]["id"])
            self._methods = MethodStore(root, capable=bool(self.method_driven()), check=self._method_check,
                                        method_driven=self.method_driven)
        return self._methods

    def _method_check(self, action: str, params: dict) -> None:
        """M5: the device's own parameter gate, run when a method is saved. State, interlocks, leases and busy are
        run-time conditions and are not checked."""
        spec = self._index["actions"].get(action)
        if spec is None:
            raise UnknownName(f"unknown action '{action}'")
        if spec.get("approval") == "forbid":
            raise Forbidden(f"'{action}' may not be operated by an agent, so no method can be saved for it")
        self._check_params(spec, params)

    def _require_capable(self) -> None:
        if not self.method_driven():
            raise NotSupported("this device declares no method-driven action (methods: true on an action in descriptor.yaml), "
                               "so it keeps no methods", {"capability": "methods"})

    def _resolve_method(self, p: dict) -> tuple[dict, dict | None, str | None]:
        """M6 and M7: turn an invoke request into (params, provenance, project)."""
        from .methods import MethodError, params_for, provenance
        name = p.get("name")
        spec = self._index["actions"].get(name) or {}
        project = p.get("project") if isinstance(p.get("project"), str) and p.get("project") else None
        compound = p.get("compound") if isinstance(p.get("compound"), str) and p.get("compound") else None
        raw = p.get("params") if p.get("params") is not None else {}
        mref = p.get("method")
        if mref is None:
            if spec.get("methods") is True and not raw:
                if compound:
                    found = self.methods.find(compound, project, action=name)
                else:
                    cands = self.methods.list(action=name, project=project) or self.methods.list(action=name)
                    found = {"choice": "several" if cands else "none", "candidates": cands,
                             "ask": ("Which method should I run" + (f" for project {project}" if project else "") + "? "
                                     + ", ".join(f"{c['project']}/{c['name']}" for c in cands)) if cands else
                                    "No saved method on this instrument. Ask the person for the parameters, run once with them, and save them."}
                raise MethodRequired(f"'{name}' runs a saved method: pass method={{name, project?}} (see methods/find), or explicit params",
                                     {**found, "action": name, "project": project, "compound": compound})
            return raw, None, project
        if isinstance(mref, str):
            mref = {"name": mref}
        if not isinstance(mref, dict) or not mref.get("name"):
            raise InvalidValue("method must be {name, project?, version?, overrides?}")
        try:
            m = self.methods.get(mref["name"], mref.get("project"), mref.get("version"))
        except MethodError as e:
            raise UnknownName(str(e)) from None
        if m.get("action") != name:
            raise InvalidValue(f"method {m['project']}/{m['name']} is for action '{m.get('action')}', not '{name}'")
        if m.get("status") != "active":
            raise InvalidValue(f"method {m['project']}/{m['name']} is retired; save it again to reactivate it")
        overrides = mref.get("overrides") or {}
        if not isinstance(overrides, dict):
            raise InvalidValue("method.overrides must be an object")
        params = params_for(m, overrides, raw)
        applied = {**overrides, **raw}
        return params, provenance(m, applied or None), project or m.get("project")

    def _record_method_run(self, job: Job) -> None:
        if job.method:
            try:
                self.methods.record_run(job.method, {"job": job.id, "session": job.owner, "state": job.state,
                                                     "overrides": job.method.get("overrides"), "project": job.project,
                                                     "result_digest": _digest(job.result) if job.result is not None else None})
            except Exception:                                          # noqa: BLE001  a record must not fail the job
                pass

    def rpc_methods_list(self, p, client):
        if not self.method_driven():
            return {"methods": [], "count": 0, "compounds": [], "projects": [], "actions": [], "method_driven": [],
                    "note": "this device declares no method-driven action"}
        return {"methods": self.methods.list(p.get("compound"), p.get("project"), p.get("action"), p.get("query"),
                                             retired=p.get("retired") is True), **self.methods.overview()}

    def rpc_methods_find(self, p, client):
        from .methods import MethodError
        if not self.method_driven():
            return {"choice": "none", "candidates": [], "ask": None, "note": "this device declares no method-driven action"}
        try:
            return self.methods.find(p.get("compound"), p.get("project"), p.get("action"))
        except MethodError as e:
            raise InvalidValue(str(e)) from None

    def rpc_methods_get(self, p, client):
        from .methods import MethodError
        self._require_capable()
        try:
            return self.methods.get(p.get("name"), p.get("project"), p.get("version"))
        except MethodError as e:
            raise UnknownName(str(e)) from None

    def rpc_methods_diff(self, p, client):
        from .methods import MethodError
        self._require_capable()
        try:
            a = self.methods.get(p.get("a"), p.get("project"), p.get("aVersion"))
            b = self.methods.get(p.get("b") or p.get("a"), p.get("project") if not p.get("b") else None, p.get("bVersion"))
        except MethodError as e:
            raise UnknownName(str(e)) from None
        return self.methods.diff(a, b)

    def rpc_methods_save(self, p, client):
        from .methods import MethodError, card
        self._require_capable()
        try:
            rec = self.methods.save(p.get("method"), by=client, note=p.get("note"))
        except MethodError as e:
            raise InvalidValue(str(e)) from None
        self.notify("methods/saved", {"method": card(rec), "by": client})
        return {"saved": card(rec), "validated": True,
                "note": "checked by the device: types, required parameters, limits and whole-request validation all passed"}

    def rpc_methods_delete(self, p, client):
        from .methods import MethodError, card
        self._require_capable()
        try:
            rec = self.methods.retire(p.get("name"), p.get("project"))
        except MethodError as e:
            raise UnknownName(str(e)) from None
        self.notify("methods/retired", {"method": card(rec), "by": client})
        return {"retired": True, "method": card(rec), "note": "kept for provenance; save it again to reactivate"}

    # ---- vendor hooks -------------------------------------------------- #
    def setup(self) -> None:                       # open serial port, etc.
        pass

    def on_read(self, name: str) -> Any:
        raise NotImplementedError

    def on_write(self, name: str, value: Any) -> dict | None:
        """Apply a validated setting. May return a dict merged into the response."""
        raise NotImplementedError

    def on_invoke(self, job: Job) -> Any:
        """Run synchronously in a worker thread. Call ``self.checkpoint(job, x)``
        between steps so pause and cancel work."""
        raise NotImplementedError

    def validate_params(self, action: str, params: dict) -> None:
        """Side-effect-free check of a whole action request, run for dry runs and real
        runs before anything moves. Raise InvalidValue or LimitViolation."""

    def on_estop(self) -> None:                    # cut power, brake, etc.
        pass

    def on_fault(self, reason: str) -> None:
        """Called once when the driver latches a fault with an unknown outcome.
        Default: the emergency-stop behaviour, to remove energy and motion."""
        self.on_estop()

    def verify_recovery(self) -> tuple[bool, str]:
        """Called by safety/reset. Default: every signal must be readable."""
        for name in self._index["signals"]:
            try:
                self.on_read(name)
            except Exception as e:                 # noqa: BLE001
                return False, f"signal '{name}' unreadable: {type(e).__name__}: {e}"
        return True, "all signals readable"

    # ---- helpers for vendor code -------------------------------------- #
    def progress(self, job: Job, fraction: float, **extra) -> None:
        job.progress = max(0.0, min(1.0, fraction))
        self.notify("jobs/progress", {"job": job.snapshot(), **extra})

    def checkpoint(self, job: Job, fraction: float | None = None, **extra) -> None:
        """Call between steps of a long action: reports progress, blocks while the job
        is paused, and raises JobCancelled once cancellation was requested."""
        if fraction is not None:
            self.progress(job, fraction, **extra)
        while job.paused and not job.cancel_requested:
            time.sleep(0.05)
        if job.cancel_requested:
            raise JobCancelled(job.id)

    def notify(self, method: str, params: dict) -> None:
        for cb in list(self.subscribers):
            try:
                cb({"jsonrpc": "2.0", "method": f"notifications/{method}", "params": params})
            except Exception:                      # noqa: BLE001
                pass

    def emit_signal(self, name: str, value: Any) -> None:
        self.notify("signals/update", {"name": name, "value": value, "ts": time.time()})

    # ---- watchdog and leases ------------------------------------------- #
    @property
    def watchdog_s(self) -> float | None:
        wd = (self.descriptor.get("safety") or {}).get("watchdog_s")
        return float(wd) if is_finite_number(wd) and wd > 0 else None

    def _arm_watchdog(self) -> None:
        if self.watchdog_s and not self._closed:
            _WATCHDOGS.register(self)

    def _lease_holder(self) -> str | None:
        """The current holder, or None if unleased or the lease expired."""
        if self.lease is not None and time.monotonic() < self.lease_expires:
            return self.lease
        return None

    def _watchdog_check(self) -> None:
        wd = self.watchdog_s
        if not wd or self._closed:
            return
        with self._state_lock:
            holder = self.lease
            if holder is None or self.state == "estop":
                return
            now = time.monotonic()
            silent = now - self._last_seen.get(holder, 0.0)
            if silent <= wd and now < self.lease_expires:
                return
            reason = (f"watchdog: no request from lease holder {holder!r} for {silent:.2f}s (limit {wd}s)" if silent > wd
                      else f"watchdog: lease held by {holder!r} expired without release")
            self._enter_estop_locked()
        threading.Thread(target=self._run_stop_hook, args=("watchdog", reason), daemon=True).start()

    def _touch(self, client: str) -> None:
        self._last_seen[client] = time.monotonic()

    def _check_lease(self, client: str, *, required: bool, dry_run: bool = False) -> dict:
        with self._state_lock:
            holder = self._lease_holder()
        if holder is not None and holder != client:
            if dry_run:
                return {"leaseHeldBy": holder}
            raise NotLeased("device is leased to another client", {"holder": holder})
        if required and holder != client:
            if dry_run:
                return {_NOTED_DRY_RUN_LEASE: True}
            raise NotLeased("this device declares a watchdog: acquire a lease (session/acquire) and keep it renewed "
                            "before operating it", {"reason": "lease_required", "watchdog_s": self.watchdog_s})
        return {}

    # ---- safety gates -------------------------------------------------- #
    def _check_state(self) -> None:
        with self._state_lock:
            state, reason = self.state, self.fault_reason
        if state == "estop":
            raise EStopActive("emergency stop is active; call safety/reset")
        if state == "fault":
            raise DeviceFault(f"device is in fault state ({reason}); call safety/reset", {"reason": reason})

    def _check_interlocks(self, spec: dict) -> None:
        for interlock in spec.get("interlocks", []) or []:
            try:
                v = self.on_read(interlock)
            except Exception as e:                 # noqa: BLE001  unreadable counts as open
                raise InterlockOpen(f"interlock '{interlock}' could not be read ({type(e).__name__}: {e}); treated as open",
                                    {"interlock": interlock})
            if v is not True:
                raise InterlockOpen(f"interlock '{interlock}' is open (read {v!r})", {"interlock": interlock})

    def _check_setting_value(self, spec: dict, value: Any) -> None:
        name = spec["name"]
        typ = spec.get("type", "number")
        check_type(name, typ, value)
        lim = spec.get("limits") or {}
        if typ in ("number", "integer") and ("min" in lim or "max" in lim):
            check_bounds(name, value, {"min": lim.get("min"), "max": lim.get("max")})
        if "enum" in lim:
            check_bounds(name, value, {"enum": lim["enum"]})

    def _check_params(self, spec: dict, params: Any) -> None:
        name = spec["name"]
        if not isinstance(params, dict):
            raise InvalidValue(f"{name}: params must be an object")
        declared = spec.get("params")
        if isinstance(declared, dict) and declared:
            unknown = sorted(set(params) - set(declared))
            if unknown:
                raise InvalidValue(f"{name}: unknown parameter(s) {unknown}; declared: {sorted(declared)}")
        for req in spec.get("required", []) or []:
            if req not in params or params[req] is None:
                raise InvalidValue(f"{name}: missing required parameter '{req}'")
        for pname, bound in (spec.get("limits") or {}).items():
            if pname in params:
                check_bounds(f"{name}.{pname}", params[pname], bound)
        reject_control_chars(params, name)
        try:
            self.validate_params(name, params)
        except MHPError:
            raise
        except (ValueError, TypeError, KeyError) as e:
            raise InvalidValue(f"{name}: {e}") from None

    def _check_busy(self, spec: dict, kind: str) -> None:
        with self._state_lock:
            active = [self.jobs[j] for j in self._active]
        if not active:
            return
        if kind == "setting":
            if spec.get("during_job") is True:
                return
            raise DeviceBusy(f"a job is running ({active[0].action}); '{spec['name']}' is not declared safe to change "
                             "during a job (during_job: true)")
        if spec.get("concurrent") is True:
            return
        raise DeviceBusy(f"device is busy with job {active[0].id} ({active[0].action})")

    def _gate(self, spec: dict, client: str, *, kind: str, value: Any = None, params: dict | None = None,
              approved: bool = False, dry_run: bool = False) -> dict:
        """State, approval, interlocks, value/params, lease, busy. Dry runs report approval,
        lease and busy conditions as notes instead of raising, so a plan can show them."""
        notes: dict = {}
        self._check_state()
        approval = spec.get("approval", "auto")
        if approval == "forbid":
            raise Forbidden(f"'{spec['name']}' may not be operated by an agent")
        if approval == "confirm" and approved is not True:
            if not dry_run:
                raise ApprovalRequired(f"'{spec['name']}' requires a person's confirmation", {"approval": "confirm"})
            notes["needsApproval"] = True
        self._check_interlocks(spec)
        if kind == "setting":
            self._check_setting_value(spec, value)
        else:
            self._check_params(spec, params if params is not None else {})
        notes.update(self._check_lease(client, required=bool(self.watchdog_s), dry_run=dry_run))
        try:
            self._check_busy(spec, kind)
        except DeviceBusy as e:
            if not dry_run:
                raise
            notes["busyNow"] = e.message
        return notes

    def _latch_fault(self, reason: str) -> None:
        with self._state_lock:
            if self.state == "estop":
                return
            self.state, self.fault_reason = "fault", reason
        try:
            self.on_fault(reason)
        except Exception as e:                     # noqa: BLE001
            reason = f"{reason}; safe-state hook failed: {type(e).__name__}: {e}"
            self.fault_reason = reason
        self.notify("safety/fault", {"reason": reason})

    def _recompute_state_locked(self) -> None:
        if self.state in ("fault", "estop"):
            return
        self.state = "busy" if self._active else "idle"

    # ---- RPC surface --------------------------------------------------- #
    def rpc(self, method: str, params: dict, client: str = "anon") -> Any:
        params = params or {}
        handler = getattr(self, "rpc_" + method.replace("/", "_"), None)
        if handler is None:
            raise MethodNotFound(f"unknown method {method}")
        self._touch(client)
        if method in _UNLOCKED:
            return handler(params, client)
        with self._lock:
            return handler(params, client)

    # lifecycle
    def rpc_initialize(self, p, client):
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "device": {k: self.descriptor["device"].get(k) for k in ("id", "class", "make", "model")},
            "capabilities": {
                "signals": True, "settings": True, "actions": True, "methods": bool(self.method_driven()),
                "subscribe": True, "lease": True, "estop": bool(self.descriptor.get("safety", {}).get("estop", False)),
                "watchdog_s": self.watchdog_s, "resources": self.package is not None,
            },
            "session": client,
        }

    def rpc_ping(self, p, client):
        with self._state_lock:
            return {"ok": True, "state": self.state, "fault_reason": self.fault_reason,
                    "lease": self._lease_holder(), "ts": time.time()}

    # describe: three detail tiers so a host never loads more than it needs.
    def rpc_device_describe(self, p, client):
        detail = p.get("detail", "full")
        if p.get("select"):
            out = self.card()
            for section, names in p["select"].items():
                out[section] = [self._index[section][n] for n in names if n in self._index.get(section, {})]
            return out
        if detail == "card":
            return self.card()
        if detail == "summary":
            return self.summary()
        return {**self.descriptor, "mhp": PROTOCOL_VERSION, "state": self.state}

    def card(self) -> dict:
        """Level 1. The DEVICE.md frontmatter plus live state and capability names."""
        d = self.descriptor["device"]
        notes = d.get("notes", "")
        description = d.get("description") or (notes.split(". ")[0].rstrip(".") + ("." if notes else ""))
        return {
            "id": d["id"], "class": d["class"], "make": d.get("make"), "model": d.get("model"),
            "location": d.get("location"), "tags": d.get("tags", []),
            "description": description,
            "state": self.state,
            "signals": list(self._index["signals"]), "settings": list(self._index["settings"]),
            "actions": list(self._index["actions"]),
        }

    def summary(self) -> dict:
        """Level 2. Card + operating instructions + a slim capability table."""
        slim = lambda items, keys: [{k: i[k] for k in keys if k in i} for i in items]  # noqa: E731
        return {
            **self.card(),
            "instructions": self.instructions,
            "physical": self.descriptor.get("physical", {}),
            "signals": slim(self.descriptor.get("signals", []), ("name", "type", "unit")),
            "settings": slim(self.descriptor.get("settings", []), ("name", "type", "unit", "limits", "approval", "during_job")),
            "actions": slim(self.descriptor.get("actions", []), ("name", "duration", "approval", "interlocks", "required", "limits", "methods")),
            "methods": ({**self.methods.overview(),
                         "how": "methods/find {compound, project} -> actions/invoke {name, method: {name, project, overrides?}, project}"}
                        if self.method_driven() else None),
            "safety": self.descriptor.get("safety", {}),
            "resources": self.package.resources if self.package else [],
        }

    # resources: Level 3, loaded only when asked for by path
    def rpc_resources_list(self, p, client):
        return {"resources": self.package.resources if self.package else []}

    def rpc_resources_read(self, p, client):
        if not self.package:
            raise UnknownName("this device has no package resources")
        try:
            return self.package.read_resource(p["path"])
        except (FileNotFoundError, PermissionError) as e:
            raise UnknownName(f"resource {p['path']}: {e}")

    # signals
    def rpc_signals_list(self, p, client):
        return {"signals": self.descriptor.get("signals", [])}

    def rpc_signals_read(self, p, client):
        names = p.get("names") or list(self._index["signals"])
        out = {}
        for n in names:
            if n not in self._index["signals"]:
                raise UnknownName(f"unknown signal '{n}'")
            out[n] = self.on_read(n)
        return {"values": out, "ts": time.time()}

    def rpc_signals_subscribe(self, p, client):
        return {"subscribed": p.get("names") or "all"}

    # settings
    def rpc_settings_list(self, p, client):
        return {"settings": self.descriptor.get("settings", [])}

    def rpc_settings_write(self, p, client):
        name = p.get("name")
        spec = self._index["settings"].get(name)
        if spec is None:
            raise UnknownName(f"unknown setting '{name}'")
        if "value" not in p:
            raise InvalidValue(f"{name}: a value is required")
        value = p["value"]
        dry = p.get("dryRun") is True
        notes = self._gate(spec, client, kind="setting", value=value, approved=p.get("approved") is True, dry_run=dry)
        if dry:
            return {"ok": True, "dryRun": True, "wouldWrite": {name: value}, **notes}
        try:
            extra = self.on_write(name, value)
        except MHPError:
            raise                                  # rejected before anything was sent
        except Exception as e:                     # noqa: BLE001  may have reached the device
            reason = f"write {name}={value!r} failed with an unknown outcome: {type(e).__name__}: {e}"
            self._latch_fault(reason)
            raise DeviceFault(reason + "; the device is latched in fault", {"outcome": "unknown"}) from None
        self.notify("settings/changed", {"name": name, "value": value, "by": client})
        return {"ok": True, "name": name, "value": value, **(extra if isinstance(extra, dict) else {})}

    # actions -> jobs
    def rpc_actions_list(self, p, client):
        return {"actions": self.descriptor.get("actions", [])}

    def rpc_actions_invoke(self, p, client):
        name = p.get("name")
        spec = self._index["actions"].get(name)
        if spec is None:
            raise UnknownName(f"unknown action '{name}'")
        params, prov, project = self._resolve_method(p)
        dry = p.get("dryRun") is True
        notes = self._gate(spec, client, kind="action", params=params, approved=p.get("approved") is True, dry_run=dry)
        if spec.get("methods") is True and prov is None and project and p.get("compound"):
            found = self.methods.find(p["compound"], project, action=name)
            if found["choice"] != "one" or found.get("newProject"):
                notes["methodHint"] = (f"no saved method for {p['compound']} in project {project}; if these parameters work, "
                                       f"methods/save them under that project so the next run can find them")
        job = Job(id="job_" + uuid.uuid4().hex[:8], action=name, params=params, owner=client, method=prov, project=project)
        if dry:
            return {"job": {**job.snapshot(), "state": "dryRun"}, **notes}
        with self._state_lock:                     # admission and registration are one step
            self._check_state()
            self._check_busy(spec, "action")
            self.jobs[job.id] = job
            self._active.add(job.id)
            self._recompute_state_locked()
            snap = job.snapshot()
        threading.Thread(target=self._run_job, args=(job,), daemon=True).start()
        return {"job": snap}

    def _run_job(self, job: Job):
        with self._state_lock:
            if job.state == "queued":
                job.state = "running"
        self.notify("jobs/started", {"job": job.snapshot()})
        result, error, final = None, None, "done"
        try:
            result = self.on_invoke(job)
            final = "cancelled" if job.cancel_requested else "done"
        except JobCancelled:
            final = "cancelled"
        except Exception as e:                     # noqa: BLE001
            final, error = "failed", f"{type(e).__name__}: {e}"
        with self._state_lock:                     # publish completion and device state atomically
            job.result, job.error, job.state, job.waiting = result, error, final, None
            job.finished = time.time()
            if final == "done":
                job.progress = 1.0
            if final == "failed":
                job.outcome = "unknown"
            self._active.discard(job.id)
            self._recompute_state_locked()
        if final == "failed":
            self._latch_fault(f"job {job.id} ({job.action}) failed: {error}")
        self._record_method_run(job)
        self.notify("jobs/finished", {"job": job.snapshot()})

    def _job(self, jid: str) -> Job:
        job = self.jobs.get(jid)
        if job is None:
            raise JobNotFound(f"no job {jid}")
        return job

    def rpc_jobs_status(self, p, client):
        with self._state_lock:
            return {"job": self._job(p["id"]).snapshot()}

    def rpc_jobs_list(self, p, client):
        with self._state_lock:
            return {"jobs": [j.snapshot() for j in self.jobs.values()]}

    def rpc_jobs_pause(self, p, client):
        job = self._job(p["id"])
        spec = self._index["actions"].get(job.action, {})
        if spec.get("pausable") is not True:
            raise NotSupported(f"'{job.action}' does not support pause; use jobs/cancel or safety/estop")
        with self._state_lock:
            if job.state in TERMINAL:
                raise DeviceBusy(f"job {job.id} already {job.state}")
            job.paused = True
        self.notify("jobs/paused", {"job": job.snapshot(), "by": client})
        return {"job": job.snapshot()}

    def rpc_jobs_resume(self, p, client):
        job = self._job(p["id"])
        self._check_state()
        self._check_lease(client, required=bool(self.watchdog_s))
        with self._state_lock:
            job.paused = False
        self.notify("jobs/resumed", {"job": job.snapshot(), "by": client})
        return {"job": job.snapshot()}

    def rpc_jobs_cancel(self, p, client):
        job = self._job(p["id"])
        spec = self._index["actions"].get(job.action, {})
        if spec.get("cancellable") is False:
            raise NotSupported(f"'{job.action}' cannot be cancelled safely mid-run; use safety/estop to stop the device")
        with self._state_lock:
            if job.state not in TERMINAL:
                job.cancel_requested = True
                job.paused = False
        self.notify("jobs/cancelling", {"job": job.snapshot(), "by": client})
        return {"job": job.snapshot()}

    # safety
    def rpc_safety_limits(self, p, client):
        return {
            "settings": {s["name"]: s.get("limits", {}) for s in self.descriptor.get("settings", [])},
            "actions": {a["name"]: a.get("limits", {}) for a in self.descriptor.get("actions", [])},
            "interlocks": self.descriptor.get("safety", {}).get("interlocks", []),
            "approval": {**{s["name"]: s.get("approval", "auto") for s in self.descriptor.get("settings", [])},
                         **{a["name"]: a.get("approval", "auto") for a in self.descriptor.get("actions", [])}},
            "watchdog_s": self.watchdog_s,
        }

    def _enter_estop_locked(self) -> None:
        self.state = "estop"
        for jid in list(self._active):
            j = self.jobs[jid]
            j.cancel_requested, j.paused = True, False
        self.lease = None

    def _run_stop_hook(self, by: str, reason: str | None) -> dict:
        stop_error = None
        try:
            self.on_estop()
        except Exception as e:                     # noqa: BLE001
            stop_error = f"{type(e).__name__}: {e}"
        self.notify("safety/estop", {"by": by, "reason": reason, "stopped": stop_error is None, "stop_error": stop_error})
        return {"state": "estop", "stopped": stop_error is None, "stop_error": stop_error}

    def rpc_safety_estop(self, p, client):
        """Never waits behind ordinary requests. A stop hook that fails is reported, not hidden."""
        with self._state_lock:
            self._enter_estop_locked()
        return self._run_stop_hook(client, p.get("reason"))

    def rpc_safety_reset(self, p, client):
        self._check_lease(client, required=bool(self.watchdog_s))
        with self._state_lock:
            if self._active:
                raise DeviceBusy(f"cannot reset while jobs are still active: {sorted(self._active)}")
        ok, detail = self.verify_recovery()
        if not ok:
            raise DeviceFault(f"recovery not verified: {detail}", {"detail": detail})
        with self._state_lock:
            self.state, self.fault_reason = "idle", None
        self.notify("safety/reset", {"by": client, "verified": detail})
        return {"state": "idle", "verified": detail}

    # leases: exclusive control, renewed by the holder
    def rpc_session_acquire(self, p, client):
        ttl = p.get("ttl", 60)
        if not is_finite_number(ttl) or not 0 < ttl <= 3600:
            raise InvalidValue("ttl must be a number of seconds between 0 and 3600")
        with self._state_lock:
            holder = self._lease_holder()
            if holder is not None and holder != client:
                raise NotLeased("device is leased to another client", {"holder": holder})
            self.lease, self.lease_expires = client, time.monotonic() + float(ttl)
            self._last_seen[client] = time.monotonic()
        return {"holder": client, "ttl": float(ttl), "watchdog_s": self.watchdog_s}

    def rpc_session_renew(self, p, client):
        ttl = p.get("ttl", 60)
        if not is_finite_number(ttl) or not 0 < ttl <= 3600:
            raise InvalidValue("ttl must be a number of seconds between 0 and 3600")
        with self._state_lock:
            if self._lease_holder() != client:
                raise NotLeased("lease lost: this session no longer holds the device", {"reason": "lease_lost"})
            self.lease_expires = time.monotonic() + float(ttl)
        return {"holder": client, "ttl": float(ttl)}

    def rpc_session_release(self, p, client):
        with self._state_lock:
            if self.lease == client:
                self.lease = None
            return {"holder": self._lease_holder()}
