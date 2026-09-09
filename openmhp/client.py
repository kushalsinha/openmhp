"""MHP client SDK.

    dev = connect("http://bench-pc:8765")          # or "stdio:python -m ..." or "local:pkg.mod:Class"
    dev.read("block_temperature")
    dev.write("target_temperature", 95)
    job = dev.invoke("run_protocol", steps=[...])
    dev.wait(job)

``Lab`` groups several devices so a script can orchestrate them in one place.
"""
from __future__ import annotations

import importlib
import itertools
import json
import shlex
import subprocess
import sys
import threading
import time
import urllib.request
from typing import Any

from .driver import Driver, MHPError


class RemoteError(MHPError):
    """An MHP error raised on the device side and re-raised here."""


class Device:
    """Uniform client over any transport."""

    def __init__(self, name: str = "device"):
        self.name = name
        self._ids = itertools.count(1)
        self.info = self.call("initialize", {"clientInfo": {"name": "openmhp-client"}})

    # transport-specific
    def _send(self, msg: dict) -> dict:
        raise NotImplementedError

    def call(self, method: str, params: dict | None = None) -> Any:
        msg = {"jsonrpc": "2.0", "id": next(self._ids), "method": method, "params": params or {}}
        resp = self._send(msg)
        if "error" in resp:
            e = resp["error"]
            err = RemoteError(e["message"], e.get("data"))
            err.code = e["code"]
            raise err
        return resp["result"]

    # convenience API mirroring the primitives
    def describe(self, detail="full") -> dict: return self.call("device/describe", {"detail": detail})
    def resources(self) -> list:            return self.call("resources/list")["resources"]
    def resource(self, path: str) -> str:   return self.call("resources/read", {"path": path})["text"]
    def limits(self) -> dict:               return self.call("safety/limits")
    def read(self, *names: str) -> Any:
        vals = self.call("signals/read", {"names": list(names)} if names else {})["values"]
        return vals[names[0]] if len(names) == 1 else vals
    def write(self, name: str, value: Any, approved=False, dry_run=False) -> dict:
        return self.call("settings/write", {"name": name, "value": value,
                                            "approved": approved, "dryRun": dry_run})
    def invoke(self, name: str, approved=False, dry_run=False, **params) -> dict:
        return self.call("actions/invoke", {"name": name, "params": params,
                                            "approved": approved, "dryRun": dry_run})["job"]
    def status(self, job: dict | str) -> dict:
        jid = job if isinstance(job, str) else job["id"]
        return self.call("jobs/status", {"id": jid})["job"]
    def cancel(self, job: dict | str) -> dict:
        jid = job if isinstance(job, str) else job["id"]
        return self.call("jobs/cancel", {"id": jid})["job"]
    def wait(self, job: dict | str, poll: float = 0.2, timeout: float | None = None) -> dict:
        t0 = time.time()
        while True:
            j = self.status(job)
            if j["state"] in ("done", "failed", "cancelled"):
                if j["state"] == "failed":
                    raise RemoteError(f"job {j['id']} failed: {j['error']}", j)
                return j
            if timeout and time.time() - t0 > timeout:
                raise TimeoutError(f"job {j['id']} still {j['state']} after {timeout}s")
            time.sleep(poll)
    def acquire(self, ttl: float = 60) -> dict:  return self.call("session/acquire", {"ttl": ttl})
    def release(self) -> dict:                   return self.call("session/release")
    def estop(self, reason: str = "") -> dict:   return self.call("safety/estop", {"reason": reason})
    def reset(self) -> dict:                     return self.call("safety/reset")

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()


class LocalDevice(Device):
    """In-process: talk to a Driver object directly (tests, notebooks)."""

    def __init__(self, driver: Driver, name="device"):
        self.driver = driver
        super().__init__(name)

    def _send(self, msg):
        from .transport import dispatch
        return dispatch(self.driver, msg, client="local")


class HttpDevice(Device):
    def __init__(self, url: str, name="device", client_id="openmhp"):
        self.url = url.rstrip("/")
        self.client_id = client_id
        super().__init__(name)

    def _send(self, msg):
        req = urllib.request.Request(
            self.url + "/rpc", data=json.dumps(msg).encode(),
            headers={"Content-Type": "application/json", "X-MHP-Client": self.client_id})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())


class StdioDevice(Device):
    """Spawn a driver as a subprocess and talk over its stdin/stdout."""

    def __init__(self, cmd: str, name="device"):
        self.proc = subprocess.Popen(shlex.split(cmd), stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, text=True, bufsize=1)
        self._pending: dict[int, dict] = {}
        self._cv = threading.Condition()
        self.notifications: list[dict] = []
        threading.Thread(target=self._reader, daemon=True).start()
        super().__init__(name)

    def _reader(self):
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

    def _send(self, msg):
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        with self._cv:
            while msg["id"] not in self._pending:
                self._cv.wait(timeout=60)
            return self._pending.pop(msg["id"])


def connect(target: str, name: str = "device") -> Device:
    """target: 'http://host:port' | 'stdio:<command>' | 'local:<module>:<DriverClass>'"""
    if target.startswith("http://") or target.startswith("https://"):
        return HttpDevice(target, name)
    if target.startswith("stdio:"):
        return StdioDevice(target[len("stdio:"):], name)
    if target.startswith("local:"):
        mod, cls = target[len("local:"):].rsplit(":", 1)
        return LocalDevice(getattr(importlib.import_module(mod), cls)(), name)
    if target.startswith("pkg:"):                 # a device package folder
        from .package import load_driver
        return LocalDevice(load_driver(target[len("pkg:"):]), name)
    raise ValueError(f"unknown target {target!r}")


class Lab:
    """A named set of devices, connected lazily on first use.

        Lab({'arm': 'http://...', 'thermo': 'local:...'})       # explicit map
        Lab.from_directory('http://directory:18900')            # thousands of devices, none loaded
        lab.find('heat a 96-well plate to 95 C', cls='thermocycler')   -> cards
        lab['thermocycler-01']                                  -> Device (resolved via directory)
    """

    def __init__(self, targets: dict[str, str] | None = None, directory=None):
        self.targets: dict[str, str] = dict(targets or {})
        self.directory = directory          # Directory object, or a Device speaking directory/*
        self._devices: dict[str, Device] = {}

    @classmethod
    def from_directory(cls, directory) -> "Lab":
        if isinstance(directory, str):
            directory = connect(directory, "directory")
        return cls({}, directory)

    def _dir(self, method: str, params: dict):
        if self.directory is None:
            raise KeyError("no directory attached to this Lab")
        if isinstance(self.directory, Device):
            return self.directory.call(method, params)
        return self.directory.rpc(method, params, "lab")

    def find(self, query: str = "", limit: int = 5, **filters) -> list[dict]:
        if self.directory is None:           # small labs: scan our own devices' cards
            cards = [self[n].call("device/describe", {"detail": "card"}) for n in self.targets]
            q = query.lower().split()
            return [c for c in cards if all(t in str(c).lower() for t in q)][:limit]
        params = {"query": query, "limit": limit}
        params.update({("class" if k == "cls" else k): v for k, v in filters.items() if v is not None})
        return self._dir("directory/search", params)["results"]

    def __getitem__(self, name: str) -> Device:
        if name not in self._devices:
            target = self.targets.get(name) or self._dir("directory/get", {"id": name})["target"]
            self.targets[name] = target
            self._devices[name] = connect(target, name)
        return self._devices[name]

    def __contains__(self, name: str) -> bool:
        return name in self.targets or name in self._devices

    @property
    def devices(self) -> dict[str, Device]:      # only those actually connected
        return dict(self._devices)

    def __iter__(self):
        return iter(self._devices.values())

    def estop_all(self, reason="lab-wide stop"):
        """Stops every *connected* device; a directory-backed lab stops what this session touched."""
        return {n: d.estop(reason) for n, d in self._devices.items()}

    def describe_all(self, detail="summary") -> dict:
        return {n: d.call("device/describe", {"detail": detail}) for n, d in self._devices.items()}
