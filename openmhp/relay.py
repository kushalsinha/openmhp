"""Node side of the MHP relay (SPEC 9.2): a bench PC behind a firewall dials OUT to a gateway and
serves its instruments through that connection. Nothing listens for the outside; every call here is
the node contacting the gateway over HTTPS, which also passes corporate proxies (urllib honours
HTTPS_PROXY).

    mhp node C:\\lab\\devices --join https://gw.office ab12-cd34     once, with a code from `mhp gateway pair`
    mhp node C:\\lab\\devices                                        from then on: serves locally AND relays

The gateway's certificate is pinned at join (its fingerprint is shown, and `mhp gateway pair` prints
the same one), so a later impostor is refused. Requests arrive by long-poll, are answered through
transport.dispatch exactly as a local HTTP caller's would be, and are never replayed: a request the
link lost is failed at the gateway, not run twice (SPEC 7.6).
"""
from __future__ import annotations

import hashlib
import json
import os
import queue
import socket
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from .transport import dispatch

HOME = Path(os.environ.get("OPENMHP_HOME", "~/.openmhp")).expanduser()
NODE_FILE = HOME / "node.json"
PIN_FILE = HOME / "gateway-pin.pem"
POLL_S = 25                  # the gateway holds /relay/next this long before answering empty
EVENT_BATCH_S = 0.5


def say(*lines: str) -> None:
    print("\n".join(lines), file=sys.stderr)


def load_node_config() -> dict | None:
    return json.loads(NODE_FILE.read_text(encoding="utf-8")) if NODE_FILE.is_file() else None


def save_node_config(cfg: dict) -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    NODE_FILE.write_text(json.dumps(cfg, indent=1), encoding="utf-8")
    try:
        os.chmod(NODE_FILE, 0o600)
    except OSError:
        pass


def fingerprint(pem: str) -> str:
    der = ssl.PEM_cert_to_DER_cert(pem)
    h = hashlib.sha256(der).hexdigest().upper()
    return ":".join(h[i:i + 2] for i in range(0, 16, 2))      # first 8 bytes: enough to compare by eye


def fetch_cert(url: str) -> str:
    u = urlsplit(url)
    return ssl.get_server_certificate((u.hostname, u.port or 443))


def ssl_context(pin_pem_path: str | None) -> ssl.SSLContext:
    """Trust exactly the pinned certificate when there is one, the system store otherwise."""
    if pin_pem_path and Path(pin_pem_path).is_file():
        ctx = ssl.create_default_context(cafile=pin_pem_path)
        ctx.check_hostname = False        # the pin IS the identity; the name may be an IP or a lab-internal alias
    else:
        ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


def nameplate(driver) -> dict:
    return driver.rpc("device/describe", {}, "discovery")


def device_payload(drivers: dict) -> list[dict]:
    out = []
    for did, drv in drivers.items():
        plate = nameplate(drv)
        out.append({"id": did, "card": drv.card() if hasattr(drv, "card") else plate.get("device", {}),
                    "nameplate": plate, "state": getattr(drv, "state", None)})
    return out


class RelayClient:
    """Keeps one node's drivers reachable through a gateway. start() returns at once; the work runs on
    daemon threads and survives gateway restarts by re-registering."""

    def __init__(self, cfg: dict, drivers: dict):
        self.cfg, self.drivers = cfg, drivers
        self.base = cfg["gateway"].rstrip("/")
        self.ctx = ssl_context(cfg.get("pin"))
        self.events: queue.Queue = queue.Queue()
        self.stop = threading.Event()
        self.connected = False
        self.last_error: str | None = None
        self._subs = []

    # ---- http ------------------------------------------------------------------------------
    def _call(self, path: str, body: dict | None = None, timeout: float = 30) -> dict:
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode() if body is not None else None,
                                     method="POST" if body is not None else "GET",
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.cfg['token']}"})
        with urllib.request.urlopen(req, context=self.ctx, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")

    def register(self) -> None:
        self._call("/relay/register", {"name": self.cfg["name"], "devices": device_payload(self.drivers)})

    # ---- threads ---------------------------------------------------------------------------
    def start(self) -> None:
        for did, drv in self.drivers.items():
            cb = (lambda ev, _d=did, _drv=drv: self.events.put({"device": _d, "event": ev, "state": getattr(_drv, "state", None)}))
            drv.subscribers.append(cb)
            self._subs.append((drv, cb))
        threading.Thread(target=self._poll_loop, name="mhp-relay-poll", daemon=True).start()
        threading.Thread(target=self._event_loop, name="mhp-relay-events", daemon=True).start()

    def close(self) -> None:
        self.stop.set()
        for drv, cb in self._subs:
            try:
                drv.subscribers.remove(cb)
            except ValueError:
                pass

    def _poll_loop(self) -> None:
        backoff = 1.0
        while not self.stop.is_set():
            try:
                self.register()
                if not self.connected:
                    say(f"relay: connected to {self.base} as '{self.cfg['name']}'")
                self.connected, backoff, self.last_error = True, 1.0, None
                while not self.stop.is_set():
                    batch = self._call("/relay/next", timeout=POLL_S + 15)
                    for req in batch.get("requests", []):
                        threading.Thread(target=self._handle, args=(req,), daemon=True).start()
            except Exception as e:                             # noqa: BLE001  link down, gateway restarting, ...
                msg = f"{type(e).__name__}: {getattr(e, 'code', '') or e}".strip()
                if self.connected or self.last_error != msg:
                    say(f"relay: {self.base} unreachable ({msg}); retrying every {backoff:.0f}s. Instruments keep working locally.")
                self.connected, self.last_error = False, msg
                self.stop.wait(backoff)
                backoff = min(backoff * 2, 30)

    def _handle(self, req: dict) -> None:
        drv = self.drivers.get(req.get("device"))
        if drv is None:
            body = {"jsonrpc": "2.0", "id": (req.get("body") or {}).get("id"),
                    "error": {"code": -32040, "message": f"no device {req.get('device')!r} on this node"}}
        elif req.get("kind") == "nameplate":
            body = nameplate(drv)
        else:
            # the gateway authenticated the caller and names it; trusted is its statement (SPEC 7.2)
            body = dispatch(drv, req.get("body") or {}, req.get("client") or "relay", trusted=bool(req.get("trusted", True))) or {}
        try:
            self._call("/relay/reply", {"rid": req["rid"], "body": body, "state": getattr(drv, "state", None) if drv else None})
        except Exception as e:                                 # noqa: BLE001  the poll loop will reconnect
            say(f"relay: could not deliver reply {req.get('rid')}: {type(e).__name__}: {e}")

    def _event_loop(self) -> None:
        while not self.stop.is_set():
            try:
                first = self.events.get(timeout=1.0)
            except queue.Empty:
                continue
            batch = [first]
            end = time.time() + EVENT_BATCH_S
            while time.time() < end:
                try:
                    batch.append(self.events.get(timeout=max(0.0, end - time.time())))
                except queue.Empty:
                    break
            if not self.connected:
                continue                                       # events in a gap are dropped, as on SSE reconnect
            try:
                self._call("/relay/events", {"events": batch})
            except Exception:                                  # noqa: BLE001
                pass


# ---- joining -----------------------------------------------------------------------------------
def join(gateway_url: str, code: str, drivers: dict, name: str | None = None, *, quiet: bool = False) -> dict:
    """Pair this PC with a gateway once. Pins the gateway's certificate, exchanges the code for a node
    token, saves node.json. Raises with a plain message on every failure a person can act on."""
    gateway_url = gateway_url.rstrip("/")
    if not gateway_url.startswith("https://"):
        raise SystemExit(f"the gateway address must start with https:// (got {gateway_url})")
    name = name or socket.gethostname().split(".")[0]
    try:
        pem = fetch_cert(gateway_url)
    except OSError as e:
        raise SystemExit(f"cannot reach {gateway_url} ({e}). Is `mhp gateway serve` running there, and does this PC "
                         "have a route out (try opening the address in a browser)?") from None
    HOME.mkdir(parents=True, exist_ok=True)
    PIN_FILE.write_text(pem, encoding="utf-8")
    fp = fingerprint(pem)
    if not quiet:
        say(f"gateway certificate fingerprint: {fp}", "  (compare with what `mhp gateway pair` printed; stop if it differs)")
    ctx = ssl_context(str(PIN_FILE))
    req = urllib.request.Request(gateway_url + "/relay/join", method="POST",
                                 data=json.dumps({"code": code, "name": name, "devices": device_payload(drivers)}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=20) as r:
            ans = json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = (e.read() or b"").decode(errors="replace")
        if e.code == 403:
            raise SystemExit("the gateway refused the code. Codes last 15 minutes and work once: run `mhp gateway pair` "
                             "there again and retry with the new one.") from None
        raise SystemExit(f"the gateway answered {e.code}: {detail[:200]}") from None
    cfg = {"gateway": gateway_url, "token": ans["node_token"], "name": ans.get("name", name), "pin": str(PIN_FILE),
           "fingerprint": fp, "joined": time.strftime("%Y-%m-%dT%H:%M:%S")}
    save_node_config(cfg)
    return cfg
