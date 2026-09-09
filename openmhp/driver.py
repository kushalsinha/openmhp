"""MHP driver base class.

A driver is an MHP *server*: it owns one physical device and exposes it through
the five MHP primitives:

    describe   - the device descriptor (identity, physics, notes, capabilities)
    signals    - things you can READ   (temperature, position, lid state ...)
    settings   - things you can WRITE  (setpoints, speeds, modes ...)
    actions    - things you can INVOKE (run protocol, home, move to ...) -> jobs
    safety     - limits, interlocks, approval levels, e-stop, watchdog

Vendor code lives in three small hooks: ``on_read``, ``on_write``, ``on_invoke``.
Everything else - limit enforcement, interlocks, leases, job tracking, the
state machine - is handled here so that every MHP device behaves the same way.
"""
from __future__ import annotations

import threading
import time
import uuid
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
class DeviceFault(MHPError):           code = -32020
class DeviceBusy(MHPError):            code = -32021
class EStopActive(MHPError):           code = -32022
class NotLeased(MHPError):             code = -32030
class UnknownName(MHPError):           code = -32040
class JobNotFound(MHPError):           code = -32041


# --------------------------------------------------------------------------- #
# Jobs: the result of invoking an action
# --------------------------------------------------------------------------- #
@dataclass
class Job:
    id: str
    action: str
    params: dict
    state: str = "queued"           # queued | running | done | failed | cancelled
    progress: float = 0.0
    result: Any = None
    error: str | None = None
    started: float = field(default_factory=time.time)
    finished: float | None = None
    cancel_requested: bool = False

    def snapshot(self) -> dict:
        return {
            "id": self.id, "action": self.action, "state": self.state,
            "progress": round(self.progress, 3), "result": self.result,
            "error": self.error, "started": self.started, "finished": self.finished,
        }


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #
class Driver:
    """Subclass this. Set ``descriptor`` and implement the three hooks."""

    descriptor: dict = {}
    package_dir: str | None = None            # set to a device package folder to load descriptor + instructions
    instructions: str = ""                    # Level 2: DEVICE.md body
    package = None                            # DevicePackage, when loaded from a folder

    def __init__(self):
        self.state = "idle"                       # idle | busy | fault | estop
        self.lease: str | None = None             # client id holding control
        self.lease_expires: float = 0.0
        self.jobs: dict[str, Job] = {}
        self.subscribers: list[Callable[[dict], None]] = []
        self._lock = threading.RLock()
        if self.package_dir and self.package is None:
            from .package import load_package
            self.attach_package(load_package(self.package_dir))
        self._reindex()
        self.setup()

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

    # ---- vendor hooks -------------------------------------------------- #
    def setup(self) -> None:                       # open serial port, etc.
        pass

    def on_read(self, name: str) -> Any:
        raise NotImplementedError

    def on_write(self, name: str, value: Any) -> None:
        raise NotImplementedError

    def on_invoke(self, job: Job) -> Any:
        """Run synchronously in a worker thread. Call ``self.progress(job, x)``
        and check ``job.cancel_requested`` for long actions."""
        raise NotImplementedError

    def on_estop(self) -> None:                    # cut power, brake, etc.
        pass

    # ---- helpers for vendor code -------------------------------------- #
    def progress(self, job: Job, fraction: float, **extra) -> None:
        job.progress = max(0.0, min(1.0, fraction))
        self.notify("jobs/progress", {"job": job.snapshot(), **extra})

    def notify(self, method: str, params: dict) -> None:
        for cb in list(self.subscribers):
            try:
                cb({"jsonrpc": "2.0", "method": f"notifications/{method}", "params": params})
            except Exception:
                pass

    def emit_signal(self, name: str, value: Any) -> None:
        self.notify("signals/update", {"name": name, "value": value, "ts": time.time()})

    # ---- safety gates -------------------------------------------------- #
    def _gate(self, spec: dict, client: str, value: Any = None, approved: bool = False):
        if self.state == "estop":
            raise EStopActive("emergency stop is active; call safety/reset")
        if self.state == "fault":
            raise DeviceFault("device is in fault state; call safety/reset")
        approval = spec.get("approval", "auto")
        if approval == "forbid":
            raise Forbidden(f"'{spec['name']}' may not be operated by an agent")
        if approval == "confirm" and not approved:
            raise ApprovalRequired(
                f"'{spec['name']}' requires human confirmation; re-send with approved=true "
                f"after elicitation", {"approval": "confirm"})
        for interlock in spec.get("interlocks", []):
            if not self.on_read(interlock):
                raise InterlockOpen(f"interlock '{interlock}' is open", {"interlock": interlock})
        if value is not None and "limits" in spec:
            lim = spec["limits"]
            if isinstance(value, (int, float)):
                if "min" in lim and value < lim["min"]:
                    raise LimitViolation(f"{spec['name']}={value} below min {lim['min']}", lim)
                if "max" in lim and value > lim["max"]:
                    raise LimitViolation(f"{spec['name']}={value} above max {lim['max']}", lim)
            if "enum" in lim and value not in lim["enum"]:
                raise LimitViolation(f"{spec['name']}={value!r} not in {lim['enum']}", lim)
        if self.lease and self.lease != client and time.time() < self.lease_expires:
            raise NotLeased(f"device is leased to another client", {"holder": self.lease})

    # ---- RPC surface --------------------------------------------------- #
    def rpc(self, method: str, params: dict, client: str = "anon") -> Any:
        params = params or {}
        with self._lock:
            handler = getattr(self, "rpc_" + method.replace("/", "_"), None)
            if handler is None:
                raise MethodNotFound(f"unknown method {method}")
            return handler(params, client)

    # lifecycle
    def rpc_initialize(self, p, client):
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "device": {k: self.descriptor["device"].get(k) for k in ("id", "class", "make", "model")},
            "capabilities": {
                "signals": True, "settings": True, "actions": True,
                "subscribe": True, "lease": True, "estop": self.descriptor.get("safety", {}).get("estop", False),
                "resources": self.package is not None,
            },
        }

    def rpc_ping(self, p, client):
        return {"ok": True, "state": self.state, "ts": time.time()}

    # describe: three detail tiers so a host never loads more than it needs.
    #   card    ~40 tokens   identity, one line of notes, tags, state, capability names
    #   summary ~200 tokens  card + every signal/setting/action as name/type/unit/approval
    #   full    everything   the complete descriptor incl. notes, limits, params, examples
    # `select` fetches the full spec of named items only: {"actions": ["run_protocol"]}
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
            "settings": slim(self.descriptor.get("settings", []), ("name", "type", "unit", "limits", "approval")),
            "actions": slim(self.descriptor.get("actions", []), ("name", "duration", "approval", "interlocks")),
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
        # transport layer registers the callback; here we just acknowledge
        return {"subscribed": p.get("names") or "all"}

    # settings
    def rpc_settings_list(self, p, client):
        return {"settings": self.descriptor.get("settings", [])}

    def rpc_settings_write(self, p, client):
        name, value = p["name"], p["value"]
        spec = self._index["settings"].get(name)
        if spec is None:
            raise UnknownName(f"unknown setting '{name}'")
        self._gate(spec, client, value, p.get("approved", False))
        if p.get("dryRun"):
            return {"ok": True, "dryRun": True, "wouldWrite": {name: value}}
        self.on_write(name, value)
        self.notify("settings/changed", {"name": name, "value": value, "by": client})
        return {"ok": True, "name": name, "value": value}

    # actions -> jobs
    def rpc_actions_list(self, p, client):
        return {"actions": self.descriptor.get("actions", [])}

    def rpc_actions_invoke(self, p, client):
        name = p["name"]
        spec = self._index["actions"].get(name)
        if spec is None:
            raise UnknownName(f"unknown action '{name}'")
        self._gate(spec, client, None, p.get("approved", False))
        if self.state == "busy" and not spec.get("concurrent", False):
            raise DeviceBusy("device is busy with another job")
        job = Job(id="job_" + uuid.uuid4().hex[:8], action=name, params=p.get("params", {}))
        if p.get("dryRun"):
            return {"job": {**job.snapshot(), "state": "dryRun"}}
        self.jobs[job.id] = job
        self.state = "busy"
        threading.Thread(target=self._run_job, args=(job,), daemon=True).start()
        return {"job": job.snapshot()}

    def _run_job(self, job: Job):
        job.state = "running"
        self.notify("jobs/started", {"job": job.snapshot()})
        try:
            job.result = self.on_invoke(job)
            job.state = "cancelled" if job.cancel_requested else "done"
            job.progress = 1.0
        except Exception as e:                     # noqa: BLE001
            job.state, job.error = "failed", f"{type(e).__name__}: {e}"
            with self._lock:
                self.state = "fault"
        finally:
            job.finished = time.time()
            with self._lock:
                if self.state == "busy":
                    self.state = "idle"
            self.notify("jobs/finished", {"job": job.snapshot()})

    def rpc_jobs_status(self, p, client):
        job = self.jobs.get(p["id"])
        if job is None:
            raise JobNotFound(f"no job {p['id']}")
        return {"job": job.snapshot()}

    def rpc_jobs_list(self, p, client):
        return {"jobs": [j.snapshot() for j in self.jobs.values()]}

    def rpc_jobs_cancel(self, p, client):
        job = self.jobs.get(p["id"])
        if job is None:
            raise JobNotFound(f"no job {p['id']}")
        job.cancel_requested = True
        return {"job": job.snapshot()}

    # safety
    def rpc_safety_limits(self, p, client):
        return {
            "settings": {s["name"]: s.get("limits", {}) for s in self.descriptor.get("settings", [])},
            "interlocks": self.descriptor.get("safety", {}).get("interlocks", []),
            "approval": {**{s["name"]: s.get("approval", "auto") for s in self.descriptor.get("settings", [])},
                         **{a["name"]: a.get("approval", "auto") for a in self.descriptor.get("actions", [])}},
        }

    def rpc_safety_estop(self, p, client):
        self.state = "estop"
        for j in self.jobs.values():
            if j.state in ("queued", "running"):
                j.cancel_requested = True
        self.on_estop()
        self.notify("safety/estop", {"by": client, "reason": p.get("reason")})
        return {"state": self.state}

    def rpc_safety_reset(self, p, client):
        if any(j.state == "running" for j in self.jobs.values()):
            raise DeviceBusy("cannot reset while a job is still running")
        self.state = "idle"
        self.notify("safety/reset", {"by": client})
        return {"state": self.state}

    # leases: exclusive control for orchestration
    def rpc_session_acquire(self, p, client):
        ttl = float(p.get("ttl", 60))
        if self.lease and self.lease != client and time.time() < self.lease_expires:
            raise NotLeased("device is leased to another client", {"holder": self.lease})
        self.lease, self.lease_expires = client, time.time() + ttl
        return {"holder": client, "expires": self.lease_expires}

    def rpc_session_release(self, p, client):
        if self.lease == client:
            self.lease = None
        return {"holder": self.lease}
