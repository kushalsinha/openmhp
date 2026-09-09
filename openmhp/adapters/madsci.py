"""MADSci node -> MHP.

    from openmhp.adapters.madsci import madsci_node
    dev = madsci_node("http://192.168.1.40:2000",
                      device={"id": "pf400-01", "class": "robot_arm", "location": "bay 2",
                              "notes": "MADSci-managed PF400."})

MADSci nodes already speak REST with an action vocabulary, so the adapter
reads the node's own description and needs no hand-written bindings:

    GET  {url}/info          node info incl. actions and their args   -> MHP actions
    GET  {url}/state         node state dict                          -> MHP signals (one per key)
    GET  {url}/status        node status (busy, errored, ...)         -> MHP state
    POST {url}/action        {"action_name", "args"}                  <- actions/invoke
    GET  {url}/action/{id}   action result / status                    -> jobs/progress
    POST {url}/admin/{cmd}   safety_stop, reset                        <- safety/estop, safety/reset

Path names are class attributes so a lab can adjust them if its MADSci
version differs. `http` may be injected (any object with get/post returning
JSON-able dicts) for tests.
"""
from __future__ import annotations

import json
import time
import urllib.request

from .base import Action, BoundDriver, Signal


class _Http:
    def __init__(self, base: str, timeout: float = 30):
        self.base, self.timeout = base.rstrip("/"), timeout

    def _req(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}

    def get(self, path):        return self._req("GET", path)
    def post(self, path, body=None): return self._req("POST", path, body or {})


class MadsciPaths:
    info, state, status, action, action_result, admin = "/info", "/state", "/status", "/action", "/action/{id}", "/admin/{cmd}"


def madsci_node(url: str, *, device: dict, http=None, paths: type = MadsciPaths, poll_s: float = 0.5,
                approval: dict | None = None, physical: dict | None = None) -> BoundDriver:
    http = http or _Http(url)
    info = http.get(paths.info)
    approval = approval or {}
    node_actions = info.get("actions") or {}
    if isinstance(node_actions, list):                     # some versions return a list of {name, args, description}
        node_actions = {a["name"]: a for a in node_actions}

    state_keys = list((http.get(paths.state) or {}).keys())

    def sig(key):
        return Signal(key, read=lambda: (http.get(paths.state) or {}).get(key), type="string")

    def action(name, meta):
        def run(job, params):
            res = http.post(paths.action, {"action_name": name, "args": params})
            aid = res.get("action_id") or res.get("id")
            status = res.get("status")
            while aid and status not in ("succeeded", "failed", "cancelled", None):
                time.sleep(poll_s)
                res = http.get(paths.action_result.format(id=aid))
                status = res.get("status")
                if job.cancel_requested:
                    break
            if status == "failed":
                raise RuntimeError(res.get("errors") or res.get("error") or "MADSci action failed")
            return res
        args = meta.get("args") or {}
        params = {k: (v.get("description") or v.get("type") or "any") if isinstance(v, dict) else str(v) for k, v in args.items()} or None
        return Action(name, run=run, duration="long", params=params, approval=approval.get(name, "auto"),
                      notes=meta.get("description"))

    dev = dict(device)
    dev.setdefault("make", "MADSci")
    dev.setdefault("model", info.get("node_type") or info.get("module_name") or "node")

    driver = BoundDriver(
        device=dev, physical=physical,
        signals=[sig(k) for k in state_keys],
        actions=[action(n, m if isinstance(m, dict) else {}) for n, m in node_actions.items()],
        estop=lambda: http.post(paths.admin.format(cmd="safety_stop")),
        extra={"madsci": {"url": url, "node_id": info.get("node_id")}},
    )

    # MADSci also knows whether it is busy: fold that into the MHP state on ping.
    _ping = driver.rpc_ping

    def rpc_ping(p, client):
        out = _ping(p, client)
        try:
            st = http.get(paths.status) or {}
            if st.get("errored"):
                out["madsci"] = "errored"
            elif st.get("busy") and out["state"] == "idle":
                out["state"] = "busy"
        except Exception:                                    # noqa: BLE001
            pass
        return out
    driver.rpc_ping = rpc_ping
    return driver
