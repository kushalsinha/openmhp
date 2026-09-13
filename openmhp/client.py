"""MHP client SDK.

    dev = connect("http://bench-pc:8765")          # or "stdio:python -m ..." or "local:pkg.mod:Class"
    dev.read("block_temperature")
    dev.write("target_temperature", 95)
    job = dev.invoke("run_protocol", steps=[...])
    dev.wait(job)

Every Device has its own session id; leases and ownership are per session. A
session that acquires a lease keeps it alive with a heartbeat until release().
On a device that declares a watchdog, the first actuating call acquires the
lease automatically.

A Device may carry an ``approver``. When it does, callers cannot assert
approval themselves: ``approved`` is stripped and a confirm-gated request is
put to the approver (for example a human, via MCP elicitation), bound to the
exact request. Without an approver the SDK caller is the trusted host.

``Lab`` groups several devices so a script can orchestrate them in one place.
"""
from __future__ import annotations

import hashlib
import importlib
import itertools
import json
import shlex
import subprocess
import threading
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable

from .driver import ApprovalRequired, Driver, MHPError, NotLeased


class RemoteError(MHPError):
    """An MHP error raised on the device side and re-raised here."""


def _remote(code: int, message: str, data: Any = None) -> RemoteError:
    err = RemoteError(message, data)
    err.code = code
    return err


ACTUATING = {"settings/write", "actions/invoke", "jobs/resume", "safety/reset"}
_APPROVABLE = {"settings/write", "actions/invoke"}
_OBSERVED = {"settings/write", "actions/invoke", "signals/read", "jobs/pause", "jobs/resume", "jobs/cancel",
             "safety/estop", "safety/reset", "session/acquire", "session/release"}


class Device:
    """Uniform client over any transport."""

    timeout: float = 30.0

    def __init__(self, name: str = "device", session: str | None = None,
                 approver: Callable[["Device", str, dict], bool] | None = None,
                 observer: Callable[[dict], None] | None = None):
        self.name = name
        self.session = session or f"client-{uuid.uuid4().hex[:10]}"
        self.approver = approver
        self.observer = observer
        self._ids = itertools.count(1)
        self._hb_stop: threading.Event | None = None
        self._subscribers: list[Callable[[dict], None]] = []
        self.lease_lost = False
        self.info = self._raw_call("initialize", {"clientInfo": {"name": "openmhp-client"}})

    # transport-specific
    def _send(self, msg: dict) -> dict:
        raise NotImplementedError

    def _raw_call(self, method: str, params: dict | None = None) -> Any:
        msg = {"jsonrpc": "2.0", "id": next(self._ids), "method": method, "params": params or {}}
        resp = self._send(msg)
        if "error" in resp:
            e = resp["error"]
            raise _remote(e["code"], e["message"], e.get("data"))
        return resp["result"]

    def _observe(self, method: str, params: dict, **fields) -> None:
        if self.observer is None or method not in _OBSERVED:
            return
        try:
            self.observer({"device": self.name, "session": self.session, "method": method, "params": params, **fields})
        except Exception:                          # noqa: BLE001  auditing must not break control
            pass

    def call(self, method: str, params: dict | None = None, _auto_lease: bool = True, _approved: bool = False,
             _note: dict | None = None) -> Any:
        """Send one request. With an approver, `approved` from callers is dropped and only set after the approver
        says yes to this exact request (`_approved`). Approval and automatic lease acquisition compose in either
        order: each is resolved once, then the same request is sent again. `_note` adds fields to the audit record
        (a method's name, version and hash)."""
        params = dict(params or {})
        if method in _APPROVABLE and self.approver is not None:
            params.pop("approved", None)
            if _approved:
                params["approved"] = True
        extra = {**(_note or {}), **({"confirmed": True} if _approved else {})}
        try:
            result = self._raw_call(method, params)
            self._observe(method, params, result=result, **extra)
            return result
        except RemoteError as e:
            data = e.data if isinstance(e.data, dict) else {}
            if (e.code == NotLeased.code and data.get("reason") == "lease_required" and _auto_lease
                    and method in ACTUATING and params.get("dryRun") is not True):
                self.acquire()
                return self.call(method, params, _auto_lease=False, _approved=_approved, _note=_note)
            if (e.code == ApprovalRequired.code and self.approver is not None and method in _APPROVABLE
                    and params.get("dryRun") is not True and not _approved):
                if self.approver(self, method, params):
                    return self.call(method, params, _auto_lease=_auto_lease, _approved=True, _note=_note)
                self._observe(method, params, error={"code": e.code, "message": "declined by a person"})
                raise _remote(ApprovalRequired.code, f"a person declined '{params.get('name')}'",
                              {"approval": "confirm", "answer": "decline"}) from None
            self._observe(method, params, error={"code": e.code, "message": e.message}, **extra)
            raise

    # convenience API mirroring the primitives
    def describe(self, detail="full") -> dict: return self.call("device/describe", {"detail": detail})
    def resources(self) -> list:            return self.call("resources/list")["resources"]
    def resource(self, path: str) -> str:   return self.call("resources/read", {"path": path})["text"]
    def limits(self) -> dict:               return self.call("safety/limits")

    def read(self, *names: str) -> Any:
        vals = self.call("signals/read", {"names": list(names)} if names else {})["values"]
        return vals[names[0]] if len(names) == 1 else vals

    def write(self, name: str, value: Any, approved=False, dry_run=False) -> dict:
        return self.call("settings/write", {"name": name, "value": value, "approved": approved, "dryRun": dry_run})

    def invoke(self, name: str, approved=False, dry_run=False, **params) -> dict:
        return self.call("actions/invoke", {"name": name, "params": params, "approved": approved, "dryRun": dry_run})["job"]

    # methods: the device keeps the parameter sets its projects run (an MHP primitive, on every device)
    def methods(self, compound: str | None = None, project: str | None = None, action: str | None = None,
                query: str | None = None, retired: bool = False) -> dict:
        return self.call("methods/list", {k: v for k, v in (("compound", compound), ("project", project), ("action", action),
                                                             ("query", query), ("retired", retired)) if v})

    def method_find(self, compound: str, project: str | None = None, action: str | None = None) -> dict:
        """{choice: one|several|none, method|candidates, ask}. 'several' means a person should choose (§4.5 M8)."""
        return self.call("methods/find", {"compound": compound, **({"project": project} if project else {}),
                                          **({"action": action} if action else {})})

    def method(self, name: str, project: str | None = None, version: int | None = None) -> dict:
        """`name` is 'project/method' or a bare method id with `project` (default _shared)."""
        return self.call("methods/get", {"name": name, **({"project": project} if project else {}),
                                         **({"version": version} if version else {})})

    def method_save(self, method: dict, note: str | None = None) -> dict:
        """The device validates the parameters through its own gate before storing; a refused method is not saved."""
        return self.call("methods/save", {"method": method, **({"note": note} if note else {})})

    def method_retire(self, name: str, project: str | None = None) -> dict:
        return self.call("methods/delete", {"name": name, **({"project": project} if project else {})})

    def method_diff(self, a: str, b: str | None = None, a_version: int | None = None, b_version: int | None = None,
                    project: str | None = None) -> dict:
        return self.call("methods/diff", {"a": a, "b": b or a, "aVersion": a_version, "bVersion": b_version,
                                          **({"project": project} if project else {})})

    def run_method(self, name: str, overrides: dict | None = None, *, project: str | None = None, version: int | None = None,
                   run_project: str | None = None, compound: str | None = None, wait: bool = True,
                   timeout: float | None = None) -> dict:
        """Invoke a saved method ('project/method', or a bare id with `project`). The device resolves the parameters,
        applies `overrides` for this run only, and stamps the job with the method's project, name, version and hash.
        `run_project` says which project this run belongs to when it differs from the method's own."""
        m = self.method(name, project, version)
        mref = {"name": m["name"], "project": m["project"], **({"version": version} if version else {}),
                **({"overrides": overrides} if overrides else {})}
        req = {"name": m["action"], "method": mref, **({"project": run_project} if run_project else {}),
               **({"compound": compound} if compound else {})}
        job = self.call("actions/invoke", req)["job"]
        return self.wait(job, timeout=timeout) if wait else job

    # events pushed by the device (signal updates, job progress and completion, safety, operator instructions)
    def subscribe(self, cb: Callable[[dict], None]) -> None:
        """Receive the device's notifications as they happen, without asking. Each is a JSON-RPC
        notification dict: {"method": "notifications/...", "params": {...}}. Callbacks must be quick."""
        self._subscribers.append(cb)
        self._start_events()

    def _start_events(self) -> None:          # transport-specific; the base class has no push channel
        pass

    def _dispatch_event(self, msg: dict) -> None:
        for cb in list(self._subscribers):
            try:
                cb(msg)
            except Exception:                  # noqa: BLE001  a listener must not break the device
                pass

    @staticmethod
    def _jid(job: dict | str) -> str:
        return job if isinstance(job, str) else job["id"]

    def status(self, job: dict | str) -> dict:  return self.call("jobs/status", {"id": self._jid(job)})["job"]
    def pause(self, job: dict | str) -> dict:   return self.call("jobs/pause", {"id": self._jid(job)})["job"]
    def resume(self, job: dict | str) -> dict:  return self.call("jobs/resume", {"id": self._jid(job)})["job"]
    def cancel(self, job: dict | str) -> dict:  return self.call("jobs/cancel", {"id": self._jid(job)})["job"]

    def wait(self, job: dict | str, poll: float = 0.2, timeout: float | None = None) -> dict:
        t0 = time.monotonic()
        while True:
            j = self.status(job)
            if j["state"] in ("done", "failed", "cancelled"):
                if j["state"] == "failed":
                    raise _remote(-32020, f"job {j['id']} failed: {j['error']}", j)
                return j
            if timeout and time.monotonic() - t0 > timeout:
                raise TimeoutError(f"job {j['id']} still {j['state']} after {timeout}s")
            time.sleep(poll)

    def wait_until(self, signal: str, test: Callable[[Any], bool], *, timeout: float, poll: float = 1.0,
                   label: str = "") -> Any:
        """Poll a signal until test(value) is true. Plan mode records this as one step instead of looping."""
        t0 = time.monotonic()
        while True:
            v = self.read(signal)
            if test(v):
                return v
            if time.monotonic() - t0 > timeout:
                raise TimeoutError(f"{self.name}.{signal} did not reach {label or 'the condition'} within {timeout}s (last {v!r})")
            time.sleep(poll)

    # leases with heartbeat
    def acquire(self, ttl: float = 60) -> dict:
        r = self.call("session/acquire", {"ttl": ttl})
        self.lease_lost = False
        self._start_heartbeat(ttl, r.get("watchdog_s"))
        return r

    def _start_heartbeat(self, ttl: float, watchdog_s: float | None) -> None:
        self._stop_heartbeat()
        stop = self._hb_stop = threading.Event()
        interval = max(0.01, min(ttl, watchdog_s or ttl) / 3)

        def beat():
            while not stop.wait(interval):
                try:
                    self._raw_call("session/renew", {"ttl": ttl})
                except RemoteError as e:
                    if e.code == NotLeased.code:
                        self.lease_lost = True
                        return
                except Exception:                  # noqa: BLE001  transport hiccup: keep trying
                    continue
        threading.Thread(target=beat, name=f"mhp-heartbeat-{self.name}", daemon=True).start()

    def _stop_heartbeat(self) -> None:
        if self._hb_stop is not None:
            self._hb_stop.set()
            self._hb_stop = None

    def release(self) -> dict:
        self._stop_heartbeat()
        return self.call("session/release")

    def close(self) -> None:
        self._stop_heartbeat()
        try:
            self._raw_call("session/release")
        except Exception:                          # noqa: BLE001
            pass

    def estop(self, reason: str = "") -> dict:   return self.call("safety/estop", {"reason": reason})
    def reset(self) -> dict:                     return self.call("safety/reset")

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()


class LocalDevice(Device):
    """In-process: talk to a Driver object directly (tests, notebooks, packages hosted by the bridge)."""

    def __init__(self, driver: Driver, name="device", **kw):
        self.driver = driver
        super().__init__(name, **kw)

    def _send(self, msg):
        from .transport import dispatch
        return dispatch(self.driver, msg, client=self.session)

    def _start_events(self):
        if not getattr(self, "_events_on", False):
            self._events_on = True
            self.driver.subscribers.append(self._dispatch_event)

    def close(self):
        if getattr(self, "_events_on", False):
            try:
                self.driver.subscribers.remove(self._dispatch_event)
            except ValueError:
                pass
            self._events_on = False
        super().close()


class HttpDevice(Device):
    def __init__(self, url: str, name="device", client_id: str | None = None, **kw):
        self.url = url.rstrip("/")
        super().__init__(name, session=kw.pop("session", None) or client_id, **kw)

    def _send(self, msg):
        req = urllib.request.Request(
            self.url + "/rpc", data=json.dumps(msg).encode(),
            headers={"Content-Type": "application/json", "X-MHP-Client": self.session})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read())

    def _start_events(self):
        """Consume GET /events (Server-Sent Events) on a daemon thread and reconnect if it drops."""
        if getattr(self, "_sse_stop", None) is not None:
            return
        stop = self._sse_stop = threading.Event()
        self._sse_resp = None

        def pump():
            backoff = 0.5
            while not stop.is_set():
                try:
                    req = urllib.request.Request(self.url + "/events", headers={"X-MHP-Client": self.session})
                    resp = urllib.request.urlopen(req, timeout=60)     # the server keeps alive every 15 s
                    self._sse_resp = resp
                    backoff = 0.5
                    for raw in resp:
                        if stop.is_set():
                            break
                        line = raw.decode(errors="replace").strip()
                        if line.startswith("data:"):
                            try:
                                self._dispatch_event(json.loads(line[5:].strip()))
                            except json.JSONDecodeError:
                                continue
                except Exception:                  # noqa: BLE001  network hiccup: reconnect
                    pass
                finally:
                    self._sse_resp = None
                if not stop.is_set():
                    stop.wait(backoff)
                    backoff = min(backoff * 2, 10)
        threading.Thread(target=pump, name=f"mhp-events-{self.name}", daemon=True).start()

    def close(self):
        stop = getattr(self, "_sse_stop", None)
        if stop is not None:
            stop.set()
            resp = getattr(self, "_sse_resp", None)
            if resp is not None:
                try:
                    resp.close()
                except Exception:              # noqa: BLE001
                    pass
        super().close()


class StdioDevice(Device):
    """Spawn a driver as a subprocess and talk over its stdin/stdout."""

    def __init__(self, cmd: str, name="device", **kw):
        self.proc = subprocess.Popen(shlex.split(cmd), stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, text=True, bufsize=1)
        self._pending: dict[int, dict] = {}
        self._cv = threading.Condition()
        self._eof = False
        self.notifications: list[dict] = []
        threading.Thread(target=self._reader, daemon=True).start()
        super().__init__(name, **kw)

    def _reader(self):
        try:
            for line in self.proc.stdout:
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "id" in msg and msg["id"] is not None:
                    with self._cv:
                        self._pending[msg["id"]] = msg
                        self._cv.notify_all()
                else:
                    self.notifications.append(msg)
                    del self.notifications[:-1000]
                    self._dispatch_event(msg)
        finally:
            with self._cv:
                self._eof = True
                self._cv.notify_all()

    def _send(self, msg):
        if self._eof:
            raise ConnectionError(f"{self.name}: driver process has exited")
        try:
            self.proc.stdin.write(json.dumps(msg) + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            raise ConnectionError(f"{self.name}: driver process is not accepting input ({e})") from None
        deadline = time.monotonic() + self.timeout
        with self._cv:
            while msg["id"] not in self._pending:
                if self._eof:
                    raise ConnectionError(f"{self.name}: driver process exited before answering {msg['method']}")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"{self.name}: no answer to {msg['method']} within {self.timeout}s")
                self._cv.wait(remaining)
            return self._pending.pop(msg["id"])


# ------------------------------------------------------------------ in-process drivers ---- #
_inprocess: dict[str, tuple[Driver, str]] = {}   # target -> (driver, package fingerprint); shared by every client
_inprocess_lock = threading.Lock()


class PackageChanged(RuntimeError):
    """A package's files changed after its driver was loaded; reload it explicitly."""


def package_fingerprint(folder: str | Path) -> str:
    """What the driver enforces: descriptor, instructions, code, references and scripts. The `methods/`
    store is written by the device itself (SPEC 4.5) and is not part of the fingerprint."""
    h = hashlib.sha256()
    root = Path(folder)
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).parts
        if rel and rel[0] == "methods":
            continue
        if p.is_file() and "__pycache__" not in p.parts and not p.name.startswith("."):
            st = p.stat()
            h.update(f"{p.relative_to(root)}:{st.st_size}:{st.st_mtime_ns};".encode())
    return h.hexdigest()[:16]


def _load_inprocess(target: str) -> Driver:
    with _inprocess_lock:
        if target.startswith("local:"):
            if target not in _inprocess:
                mod, cls = target[len("local:"):].rsplit(":", 1)
                _inprocess[target] = (getattr(importlib.import_module(mod), cls)(), "")
            return _inprocess[target][0]
        from .package import load_driver
        sim = target.startswith("sim:")
        folder = target.split(":", 1)[1]
        fp = package_fingerprint(folder)
        if target in _inprocess:
            drv, old = _inprocess[target]
            if old != fp:
                raise PackageChanged(f"the package at {folder} changed on disk after it was loaded; "
                                     "reload it (mhp_lab op='reload') so the enforced configuration matches the files")
            return drv
        drv = load_driver(folder, sim=sim)
        _inprocess[target] = (drv, fp)
        return drv


def drop_inprocess(target: str) -> bool:
    """Forget an in-process driver so the next connect loads the package afresh."""
    with _inprocess_lock:
        entry = _inprocess.pop(target, None)
    if entry is not None:
        entry[0].close()
    return entry is not None


def connect(target: str, name: str = "device", **kw) -> Device:
    """target: 'http://host:port' | 'stdio:<command>' | 'local:<module>:<DriverClass>' | 'pkg:<folder>' | 'sim:<folder>'"""
    if target.startswith("http://") or target.startswith("https://"):
        return HttpDevice(target, name, **kw)
    if target.startswith("stdio:"):
        return StdioDevice(target[len("stdio:"):], name, **kw)
    if target.startswith(("local:", "pkg:", "sim:")):
        return LocalDevice(_load_inprocess(target), name, **kw)
    raise ValueError(f"unknown target {target!r}")


class Lab:
    """A named set of devices, connected lazily on first use.

        Lab({'arm': 'http://...', 'thermo': 'local:...'})       # explicit map
        Lab.from_directory('http://directory:18900')            # thousands of devices, none loaded
        lab.find('heat a 96-well plate to 95 C', cls='thermocycler')   -> cards
        lab['thermocycler-01']                                  -> Device (resolved via directory)

    All devices of one Lab share its session id. ``child()`` gives an independent
    session over the same targets (used for runs and plans).
    """

    planning = False

    def __init__(self, targets: dict[str, str] | None = None, directory=None, *, session: str | None = None,
                 approver=None, observer=None, on_connect: Callable[[str, Device], None] | None = None):
        self.targets: dict[str, str] = targets if isinstance(targets, dict) else dict(targets or {})
        self.directory = directory          # Directory object, or a Device speaking directory/*
        self.session = session or f"lab-{uuid.uuid4().hex[:10]}"
        self.approver, self.observer, self.on_connect = approver, observer, on_connect
        self._devices: dict[str, Device] = {}
        self._lock = threading.Lock()

    @classmethod
    def from_directory(cls, directory) -> "Lab":
        if isinstance(directory, str):
            directory = connect(directory, "directory")
        return cls({}, directory)

    def child(self, session: str | None = None, observer: Any = "inherit", approver: Any = "inherit") -> "Lab":
        return Lab(self.targets, self.directory, session=session,
                   approver=self.approver if approver == "inherit" else approver,
                   observer=self.observer if observer == "inherit" else observer,
                   on_connect=self.on_connect)

    def _dir(self, method: str, params: dict):
        if self.directory is None:
            raise KeyError("no directory attached to this Lab")
        if isinstance(self.directory, Device):
            return self.directory.call(method, params)
        return self.directory.rpc(method, params, "lab")

    def find(self, query: str = "", limit: int = 5, **filters) -> list[dict]:
        if self.directory is None:           # small labs: scan our own devices' cards
            cards = [self[n].call("device/describe", {"detail": "card"}) for n in list(self.targets)]
            q = query.lower().split()
            return [c for c in cards if all(t in str(c).lower() for t in q)][:limit]
        params = {"query": query, "limit": limit}
        params.update({("class" if k == "cls" else k): v for k, v in filters.items() if v is not None})
        return self._dir("directory/search", params)["results"]

    def __getitem__(self, name: str) -> Device:
        with self._lock:
            dev = self._devices.get(name)
        if dev is not None:
            return dev
        target = self.targets.get(name)
        if target is None:
            if self.directory is None:
                raise KeyError(f"no device {name!r} in this lab")
            target = self._dir("directory/get", {"id": name})["target"]
        dev = connect(target, name, session=self.session, approver=self.approver, observer=self.observer)
        with self._lock:
            if name in self._devices:                # another thread won the race
                dev.close()
                return self._devices[name]
            self._devices[name] = dev
        if self.on_connect:
            self.on_connect(name, dev)
        return dev

    def __contains__(self, name: str) -> bool:
        return name in self.targets or name in self._devices

    @property
    def devices(self) -> dict[str, Device]:      # only those actually connected
        return dict(self._devices)

    def __iter__(self):
        return iter(list(self._devices.values()))

    def forget(self, name: str) -> None:
        """Drop the connection to a device (releases this session's lease) and its target."""
        with self._lock:
            dev = self._devices.pop(name, None)
        self.targets.pop(name, None)
        if dev is not None:
            dev.close()

    def release_all(self) -> None:
        for d in list(self._devices.values()):
            try:
                d.release()
            except Exception:                        # noqa: BLE001
                pass

    def close(self) -> None:
        for d in list(self._devices.values()):
            d.close()

    def estop_all(self, reason="lab-wide stop", timeout: float = 10.0) -> dict:
        """Stops every connected device in parallel; one failure or slow device does not block the others."""
        devices = list(self._devices.items())
        results: dict[str, dict] = {}

        def one(n, d):
            try:
                r = d.estop(reason) or {}
                results[n] = {"ok": bool(r.get("stopped", True)), **r}
            except Exception as e:                   # noqa: BLE001
                results[n] = {"ok": False, "error": f"{type(e).__name__}: {e}"}

        threads = [threading.Thread(target=one, args=item, daemon=True) for item in devices]
        for t in threads:
            t.start()
        deadline = time.monotonic() + timeout
        for t in threads:
            t.join(max(0.0, deadline - time.monotonic()))
        for n, _ in devices:
            results.setdefault(n, {"ok": False, "error": f"no answer within {timeout}s"})
        return results

    def describe_all(self, detail="summary") -> dict:
        return {n: d.call("device/describe", {"detail": detail}) for n, d in self._devices.items()}
