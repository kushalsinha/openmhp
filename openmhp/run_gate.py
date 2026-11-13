"""The gateway's check on every request a run makes with its run token.

A run token stands for one run of one scientist. Its requests reach only the run's instruments, act as
`<scientist>/run-<id>` (so device leases and records name the person and the run), and pass the charter
before any lab PC sees them:

- reads, job status, leases, resources, methods and e-stop: allowed on the run's instruments
- settings/write and actions/invoke: only what the envelope lists, with every bounded value in range,
  before the deadline, within the experiment budget and the consumable limits
- `approved` from the run is never trusted: the gateway adds it only for a standing approval in scope
- an `always_ask` action, a reset after e-stop, or a confirm-gated action without a standing approval
  goes back to the scientist (error -32012 with data.charter = "ask_scientist")
- anything else: refused (-32013 with data.charter = "outside")

Usage (experiments, consumables, standing-approval uses) is counted only for requests the device
accepted, and kept in the gateway's own folder, where a run cannot edit it.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from . import charter as C

APPROVAL_REQUIRED, FORBIDDEN = -32012, -32013
READS = {"ping", "initialize", "device/describe", "signals/list", "signals/read", "settings/list", "actions/list",
         "jobs/status", "jobs/list", "jobs/wait", "resources/list", "resources/read", "safety/limits",
         "methods/list", "methods/get", "methods/find", "methods/diff", "methods/save",
         "session/acquire", "session/renew", "session/release", "safety/estop",
         "jobs/cancel", "jobs/pause", "jobs/resume"}
ASK = {"safety/reset"}


def _in_bounds(value, spec: dict) -> bool:
    if not spec:
        return True
    if "in" in spec:
        return value in spec["in"]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return (spec.get("min") is None or value >= spec["min"]) and (spec.get("max") is None or value <= spec["max"])


class RunGate:
    def __init__(self, charter: dict, folder: Path):
        self.charter = charter
        self.run, self.owner = charter["run"], charter["owner"]
        self.identity = f"{self.owner}/run-{self.run}"
        self.devices = {dev: alias for alias, dev in charter["instruments"].items()}
        self.folder = Path(folder)
        self.lock = threading.Lock()
        self.usage = self._load()

    # ---- usage, kept by the gateway --------------------------------------------------------
    def _load(self) -> dict:
        try:
            return json.loads((self.folder / "usage.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"experiments": 0, "consumables": {}, "approvals": {}}

    def _save(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        tmp = self.folder / "usage.json.tmp"
        tmp.write_text(json.dumps(self.usage), encoding="utf-8")
        os.replace(tmp, self.folder / "usage.json")

    # ---- the check -------------------------------------------------------------------------
    def allows_device(self, path: str) -> bool:
        return path in self.devices

    @staticmethod
    def _error(mid, code: int, message: str, **data) -> dict:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message, "data": data}}

    def check(self, path: str, msg: dict):
        """(message to send, None, commit) when allowed, or (None, JSON-RPC error reply, None) when not.
        Call commit(reply) after the device answered; it counts usage only if the device accepted."""
        mid, method = msg.get("id"), msg.get("method", "")
        params = dict(msg.get("params") or {})
        alias = self.devices.get(path)
        if alias is None:
            return None, self._error(mid, FORBIDDEN, f"{path} is not one of run {self.run}'s instruments", charter="outside"), None
        params.pop("approved", None)                          # only the gateway approves for a run
        if method in READS:
            return {**msg, "params": params}, None, None
        if method in ASK:
            return None, self._error(mid, APPROVAL_REQUIRED, f"{method} on {alias} needs the scientist",
                                     charter="ask_scientist", instrument=alias, method=method), None
        if method not in ("settings/write", "actions/invoke"):
            return None, self._error(mid, FORBIDDEN, f"{method} is not something run {self.run} may do", charter="outside"), None

        env = (self.charter.get("envelope") or {}).get(alias) or {}
        dry = params.get("dryRun") is True
        budgets = self.charter.get("budgets") or {}
        if not dry and budgets.get("deadline") and time.time() > C._when(budgets["deadline"]):
            return None, self._error(mid, FORBIDDEN, f"run {self.run} is past its deadline {budgets['deadline']}",
                                     charter="deadline"), None

        if method == "settings/write":
            name, value = params.get("name"), params.get("value")
            spec = (env.get("settings") or {}).get(name)
            if spec is None:
                return None, self._error(mid, FORBIDDEN, f"setting {name!r} on {alias} is outside the charter", charter="outside",
                                         instrument=alias, setting=name), None
            if not _in_bounds(value, spec):
                return None, self._error(mid, FORBIDDEN, f"{alias} {name} = {value!r} is outside the charter's {spec}",
                                         charter="outside", instrument=alias, setting=name, bounds=spec), None
            return {**msg, "params": params}, None, None

        # actions/invoke
        name, args = params.get("name"), params.get("params") or {}
        for a in self.charter.get("always_ask") or []:
            if a.get("instrument") == alias and a.get("action") in (None, "*", name):
                return None, self._error(mid, APPROVAL_REQUIRED, f"{alias} {name} always goes to the scientist first",
                                         charter="ask_scientist", instrument=alias, action=name), None
        spec = (env.get("actions") or {}).get(name)
        if spec is None:
            return None, self._error(mid, FORBIDDEN, f"action {name!r} on {alias} is outside the charter", charter="outside",
                                     instrument=alias, action=name), None
        if params.get("method") and spec:
            return None, self._error(mid, FORBIDDEN, f"{alias} {name} has bounded parameters, so the run must pass them "
                                     "explicitly rather than by a saved method", charter="outside", instrument=alias, action=name), None
        for p, b in spec.items():
            if p in args and not _in_bounds(args[p], b):
                return None, self._error(mid, FORBIDDEN, f"{alias} {name} {p} = {args[p]!r} is outside the charter's {b}",
                                         charter="outside", instrument=alias, action=name, param=p, bounds=b), None
        with self.lock:
            count = budgets.get("count") or {}
            counts = count.get("instrument") == alias and count.get("action") == name
            if counts and not dry and "experiments" in budgets and self.usage["experiments"] >= budgets["experiments"]:
                return None, self._error(mid, FORBIDDEN, f"run {self.run} has used all {budgets['experiments']} experiments",
                                         charter="budget", used=self.usage["experiments"]), None
            spend = {}
            for cname, c in (self.charter.get("consumables") or {}).items():
                for u in c.get("uses") or []:
                    if u.get("instrument") == alias and u.get("action") == name:
                        amount = float(args.get(u.get("param"), 0) or 0) * float(u.get("scale", 1))
                        spend[cname] = spend.get(cname, 0.0) + amount
                used = self.usage["consumables"].get(cname, 0.0)
                if cname in spend and not dry and used + spend[cname] > c["limit"] + 1e-12:
                    return None, self._error(mid, FORBIDDEN, f"{cname}: this needs {spend[cname]:g}, and only "
                                             f"{c['limit'] - used:g} of {c['limit']:g} is left", charter="consumable",
                                             consumable=cname, used=used, limit=c["limit"]), None
            standing = None
            for i, a in enumerate(self.charter.get("standing_approvals") or []):
                if a.get("instrument") != alias or a.get("action") != name:
                    continue
                if a.get("until") and time.time() > C._when(a["until"]):
                    continue
                if a.get("uses") is not None and self.usage["approvals"].get(str(i), 0) >= a["uses"]:
                    continue
                standing = i
                break
        if standing is not None:
            params["approved"] = True
        out = {**msg, "params": params}

        def commit(reply: dict) -> None:
            if dry or not isinstance(reply, dict) or "error" in reply:
                return
            with self.lock:
                if counts:
                    self.usage["experiments"] += 1
                for cname, amount in spend.items():
                    self.usage["consumables"][cname] = self.usage["consumables"].get(cname, 0.0) + amount
                if standing is not None:
                    self.usage["approvals"][str(standing)] = self.usage["approvals"].get(str(standing), 0) + 1
                self._save()

        return out, None, commit

    def translate(self, reply: dict) -> dict:
        """A device that still wants a person's confirmation means the scientist must be asked."""
        err = (reply or {}).get("error") if isinstance(reply, dict) else None
        if err and err.get("code") == APPROVAL_REQUIRED:
            data = dict(err.get("data") or {})
            data["charter"] = "ask_scientist"
            return {**reply, "error": {**err, "data": data}}
        return reply
