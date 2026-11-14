"""`mhp gateway`: the office-side half of the MHP relay (SPEC 9.2). Lab PCs behind a firewall dial OUT
to this process and register their instruments; agents reach those instruments here over plain MHP
HTTP, as if each were a device on the LAN. Written for the person at the bench, not for an agent: every
command either finishes the job or prints the one thing to do next.

    mhp gateway init                  make this machine the gateway (asks name and port; makes a certificate)
    mhp gateway serve                 run it (add --install-service to keep it running across reboots)
    mhp gateway pair                  print a one-time code for a lab PC:  mhp node <dir> --join <this url> <code>
    mhp gateway pair-agent [name]     print a one-time code for an agent machine:  mhp agent --join <this url> <code>
    mhp gateway add-agent <name>      let one agent machine through by hand; prints the token to paste there
    mhp gateway status | check        what is connected, which lab PCs run an old OpenMHP, and what to fix
    mhp gateway ssh [users] [apply]   let scientists' machines run mhp-gw and copy files over SSH (keys arrive at pairing)

Agent face (bearer = agent token):  POST /agent/join (code, no token)    GET /    GET /<node>/<device>/mhp.json    POST /<node>/<device>/rpc
                                    GET /<node>/<device>/events (SSE)         /directory/{rpc,mhp.json}
Node face  (bearer = node token):   POST /relay/join  POST /relay/register  GET /relay/next (long poll)
                                    POST /relay/reply  POST /relay/events
A request to a node is handed over exactly once. If the node is offline, or does not answer in time,
the agent gets 503/504 and the request is dropped, never re-sent (SPEC 7.6).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import platform
import queue
import re
import secrets
import shutil
import errno
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__
from . import update_check as U
from .directory import Directory

HOME = Path(os.environ.get("OPENMHP_HOME", "~/.openmhp")).expanduser()
GW_DIR = HOME / "gateway"
STATE = GW_DIR / "gateway.json"
OFFLINE_S = 45            # no /relay/next from a node for this long: offline
POLL_S = 25               # how long /relay/next may wait before answering empty
REQUEST_TIMEOUT_S = 120   # default wait for a node's reply; X-MHP-Timeout raises it
CODE_TTL_S = 15 * 60                  # a lab PC code: typed within minutes by the person at the bench
AGENT_CODE_TTL_S = 60 * 60            # an agent code: sent in chat, redeemed when the person gets to it


def say(*lines: str) -> None:
    print("\n".join(lines), file=sys.stderr)


# ---- state -------------------------------------------------------------------------------------
def load() -> dict | None:
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.is_file() else None


def save(state: dict) -> None:
    GW_DIR.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=1), encoding="utf-8")
    try:
        os.chmod(STATE, 0o600)
        os.chmod(GW_DIR, 0o700)                   # tokens and the TLS key: this account only, never a scientist's run
    except OSError:
        pass


def agent_url(state: dict, path: str = "") -> str:
    port = state.get("listen", 443)
    base = f"https://{state['server_name']}" + (f":{port}" if port != 443 else "")
    return f"{base}/{path.strip('/')}/" if path else base + "/"


def fingerprint_of(cert_path: str) -> str:
    der = ssl.PEM_cert_to_DER_cert(Path(cert_path).read_text(encoding="utf-8"))
    h = hashlib.sha256(der).hexdigest().upper()
    return ":".join(h[i:i + 2] for i in range(0, 16, 2))


def self_signed(name: str, ip: str) -> tuple[Path, Path] | None:
    openssl = shutil.which("openssl")
    crt, key = GW_DIR / "gateway.crt", GW_DIR / "gateway.key"
    if crt.is_file() and key.is_file():
        return crt, key
    if not openssl:
        return None
    GW_DIR.mkdir(parents=True, exist_ok=True)
    san = f"subjectAltName=DNS:{name},DNS:localhost,IP:127.0.0.1" + (f",IP:{ip}" if ip and ip != "127.0.0.1" else "")
    r = subprocess.run([openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "825", "-subj", f"/CN={name}",
                        "-addext", san, "-keyout", str(key), "-out", str(crt)], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    try:
        os.chmod(key, 0o600)
    except OSError:
        pass
    return crt, key


def local_ip() -> str:
    from .discovery import _local_ip
    return _local_ip()


def ask(prompt: str, default: str | None = None) -> str:
    if not sys.stdin.isatty():
        if default is None:
            raise SystemExit(f"{prompt}: no terminal to ask on; pass it as an option")
        return default
    ans = input(f"{prompt}" + (f" [{default}]" if default else "") + ": ").strip()
    return ans or (default or "")


def new_code() -> str:
    a = secrets.token_hex(2)
    b = secrets.token_hex(2)
    return f"{a}-{b}"


AGENT_401 = ("unknown agent token; pair this machine with a code from `mhp gateway pair-agent`:  "
             "mhp agent --join <gateway url> <code>")


# ---- the server --------------------------------------------------------------------------------
class Node:
    """Runtime side of one registered lab PC."""
    def __init__(self, name: str):
        self.name = name
        self.queue: queue.Queue = queue.Queue()
        self.inflight: dict[str, dict] = {}
        self.devices: dict[str, dict] = {}        # id -> {card, nameplate, state}
        self.last_seen = 0.0                      # any call from the node (for status display)
        self.last_poll = 0.0                      # when its last /relay/next ended
        self.polling = 0                          # /relay/next calls in progress; a live node always has one
        self.version: str | None = None           # the node's OpenMHP; None = 0.10.0 or older, which never said
        self.upgrade: str | None = None           # the command its owner runs to update it, as the node worked it out
        self.lock = threading.Lock()

    @property
    def online(self) -> bool:
        """A connected node is always inside a long poll. Liveness is judged on polls alone, so a stray event
        push from a dying client cannot keep a node 'online'. No poll for a few seconds means the link
        dropped; OFFLINE_S is the backstop for a poll that died without closing."""
        if self.polling > 0:
            return time.time() - self.last_seen < OFFLINE_S
        return time.time() - self.last_poll < 5


class Gateway:
    def __init__(self, state: dict):
        self.state = state
        self.state_mtime = STATE.stat().st_mtime if STATE.is_file() else 0
        self.nodes: dict[str, Node] = {}
        self.node_by_token: dict[str, str] = {}
        self.subs: dict[tuple[str, str], list] = {}
        self.directory = Directory(state_ttl=0.0)      # probes are in-memory lookups: always current
        self.lock = threading.Lock()
        self._index_tokens()

    # ---- state shared with the CLI (pair codes, agents) -------------------------------------
    def refresh(self) -> None:
        try:
            m = STATE.stat().st_mtime
        except OSError:
            return
        if m != self.state_mtime:
            fresh = load()
            if fresh:
                self.state, self.state_mtime = fresh, m
                self._index_tokens()

    def _index_tokens(self) -> None:
        self.node_by_token = {n["token"]: name for name, n in self.state.get("nodes", {}).items()}

    def persist(self) -> None:
        save(self.state)
        self.state_mtime = STATE.stat().st_mtime

    def agent_for(self, auth: str) -> str | None:
        self.refresh()
        tok = auth[7:] if auth.startswith("Bearer ") else ""
        for t, name in self.state.get("agents", {}).items():
            if hmac.compare_digest(t.encode(), tok.encode()):
                return name
        return None

    def node_for(self, auth: str) -> Node | None:
        self.refresh()
        tok = auth[7:] if auth.startswith("Bearer ") else ""
        for t, name in self.node_by_token.items():
            if hmac.compare_digest(t.encode(), tok.encode()):
                with self.lock:
                    node = self.nodes.setdefault(name, Node(name))
                node.last_seen = time.time()
                return node
        return None

    def is_admin(self, auth: str) -> bool:
        return auth.startswith("Bearer ") and hmac.compare_digest(auth[7:].encode(), self.state.get("admin_token", "").encode())

    # ---- node face -----------------------------------------------------------------------------
    def join(self, body: dict) -> tuple[int, dict]:
        self.refresh()
        code = (body.get("code") or "").strip().lower()
        codes = self.state.setdefault("codes", {})
        for c in list(codes):
            if codes[c]["expires"] < time.time():
                del codes[c]
        if code not in codes or codes[code].get("kind", "node") != "node":
            self.persist()
            return 403, {"error": "unknown or expired pairing code"}
        del codes[code]
        want = re.sub(r"[^A-Za-z0-9._-]", "-", body.get("name") or "node") or "node"
        name = want
        n = 2
        # a PC pairing again (reinstalled, lost its node.json) takes its own name back, unless a node by that
        # name is connected right now: the code proves the operator's intent, the old token stops working
        while name in self.state.setdefault("nodes", {}) and (self.nodes.get(name) is not None and self.nodes[name].online):
            name = f"{want}-{n}"
            n += 1
        if name in self.state["nodes"]:
            old = self.nodes.pop(name, None)
            if old is not None:
                for did in list(old.devices):
                    self.directory.remove(f"{name}/{did}")
        token = secrets.token_urlsafe(32)
        self.state["nodes"][name] = {"token": token, "joined": time.strftime("%Y-%m-%dT%H:%M:%S")}
        self.persist()
        self._index_tokens()
        return 200, {"node_token": token, "name": name}

    def join_agent(self, body: dict) -> tuple[int, dict]:
        """`mhp agent --join`: a single-use code from `mhp gateway pair-agent` becomes this machine's agent token.
        A machine pairing again takes its name back and the old token stops working, as a lab PC does."""
        self.refresh()
        code = (body.get("code") or "").strip().lower()
        codes = self.state.setdefault("codes", {})
        for c in list(codes):
            if codes[c]["expires"] < time.time():
                del codes[c]
        if code not in codes or codes[code].get("kind") != "agent":
            self.persist()
            return 403, {"error": "unknown or expired agent code"}
        preset = codes.pop(code).get("name")
        name = re.sub(r"[^A-Za-z0-9._-]", "-", preset or body.get("name") or "agent") or "agent"
        agents = self.state.setdefault("agents", {})
        for t in [t for t, n in agents.items() if n == name]:
            del agents[t]
        token = secrets.token_urlsafe(24)
        agents[token] = name
        self.persist()
        return 200, {"agent_token": token, "name": name, "directory": agent_url(self.state, "directory"),
                     "ssh": self.register_scientist_key(name, body.get("ssh_key"))}

    def register_scientist_key(self, name: str, key: str | None) -> dict | None:
        """The machine's SSH key, kept in the scientist's profile so sshd accepts it for mhp-gw only.
        None when this gateway has no SSH access set up or the machine sent no key; an error the agent
        machine can show otherwise. Pairing itself never fails over SSH."""
        cfg = self.state.get("ssh")
        if not cfg or not key:
            return None
        from . import scientists as S, ssh_access as SA
        try:
            sci = S.check_name(name.lower())
            root = Path(cfg["lab_root"])
            if cfg.get("mode") == "users" and not S.folder(sci, root).is_dir():
                return {"error": f"no folder for scientist {sci!r} yet: the gateway operator runs `sudo mhp gateway "
                                 f"pair-agent {sci}` first, then this machine pairs with the new code"}
            S.create(sci, root=root, ssh_key=SA.check_key(key), agent=name)
        except ValueError as e:
            return {"error": str(e)}
        return {"host": cfg["host"], "port": cfg.get("port", 22), "login": SA.login_for(sci, cfg),
                "host_key": cfg["host_key"], "scientist": sci}

    def register(self, node: Node, body: dict) -> None:
        node.last_poll = time.time()              # registering counts as alive until the first poll arrives
        node.version, node.upgrade = body.get("openmhp"), body.get("upgrade")
        seen = set()
        for d in body.get("devices", []):
            did = d["id"]
            seen.add(did)
            node.devices[did] = {"card": d.get("card") or {}, "nameplate": d.get("nameplate") or {}, "state": d.get("state")}
            card = dict(node.devices[did]["card"])
            card["id"] = f"{node.name}/{did}" if card.get("id") != f"{node.name}/{did}" else card["id"]
            target = agent_url(self.state, f"{node.name}/{did}")
            self.directory.add(card, target, probe=lambda _n=node, _d=did: (_n.devices.get(_d) or {}).get("state") or "unknown" if _n.online else "offline")
        for did in list(node.devices):
            if did not in seen:
                del node.devices[did]
                self.directory.remove(f"{node.name}/{did}")
        # requests queued while the node was away must not run late and unexpected: fail them now
        for rid, slot in list(node.inflight.items()):
            if slot.get("queued_before_register"):
                slot["reply"] = (503, {"error": f"node '{node.name}' reconnected after this request was queued; not re-sent"})
                slot["event"].set()
        for rid in list(node.inflight):
            node.inflight[rid]["queued_before_register"] = True

    def next_requests(self, node: Node) -> list[dict]:
        out = []
        node.polling += 1
        try:
            out.append(node.queue.get(timeout=POLL_S))
            while True:
                out.append(node.queue.get_nowait())
        except queue.Empty:
            pass
        finally:
            node.polling -= 1
            node.last_seen = node.last_poll = time.time()
        return [r for r in out if r["rid"] in node.inflight]

    def reply(self, node: Node, body: dict) -> None:
        slot = node.inflight.get(body.get("rid"))
        if slot is None:
            return                                      # the agent gave up: drop, do not retry anything
        did = slot["device"]
        if did in node.devices and body.get("state") is not None:
            node.devices[did]["state"] = body["state"]
        slot["reply"] = (200, body.get("body", {}))
        slot["event"].set()

    def events(self, node: Node, body: dict) -> None:
        for ev in body.get("events", []):
            did = ev.get("device")
            if did in node.devices and ev.get("state") is not None:
                node.devices[did]["state"] = ev["state"]
            for q in list(self.subs.get((node.name, did), [])):
                q.put(ev.get("event"))

    # ---- agent face ----------------------------------------------------------------------------
    def relay(self, node: Node, device: str, kind: str, body: dict | None, client: str, timeout: float) -> tuple[int, dict]:
        if not node.online:
            ago = int(time.time() - node.last_seen) if node.last_seen else None
            return 503, {"error": f"node '{node.name}' is offline" + (f" (last seen {ago}s ago)" if ago is not None else " (never connected)")
                         + "; nothing was sent. Check `mhp node` on that PC."}
        rid = secrets.token_hex(8)
        slot = {"event": threading.Event(), "reply": None, "device": device}
        node.inflight[rid] = slot
        node.queue.put({"rid": rid, "device": device, "kind": kind, "client": client, "trusted": True, "body": body})
        try:
            if slot["event"].wait(timeout):
                code, reply = slot["reply"]
                note = self.outdated_note(node) if kind == "rpc" and (body or {}).get("method") == "device/describe" else None
                if note and isinstance(reply, dict) and isinstance(reply.get("result"), dict):
                    reply = {**reply, "result": {**reply["result"], "notice": note}}
                return code, reply
            return 504, {"error": f"node '{node.name}' did not answer within {int(timeout)}s; the request is dropped and will not "
                         "be re-sent. If it was an action, check jobs/status before repeating it."}
        finally:
            node.inflight.pop(rid, None)

    def outdated(self, node: Node) -> bool:
        return node.version is None or U.newer(U.latest_known(), node.version)

    def outdated_note(self, node: Node) -> str | None:
        """Said to an agent reading a device's description, so the person it works for hears it in passing."""
        if not self.outdated(node):
            return None
        have = f"OpenMHP {node.version}" if node.version else "OpenMHP 0.10.0 or older"
        return (f"This instrument is served by lab PC '{node.name}', which runs {have}; {U.latest_known()} is out. "
                "Mention once to the user that whoever looks after that PC can update it"
                + (f" with: {node.upgrade}" if node.upgrade else " (the gateway's `mhp gateway status` lists the command)")
                + ". It keeps working as it is; do not hold up the task for this.")

    def status_doc(self) -> dict:
        self.refresh()
        return {"gateway": self.state["server_name"], "openmhp": __version__, "latest": U.latest_known(), "nodes": {
            name: {"online": n.online, "last_seen": n.last_seen, "openmhp": n.version, "upgrade": n.upgrade,
                   "outdated": self.outdated(n),
                   "devices": {d: {"state": v.get("state"), "url": agent_url(self.state, f"{name}/{d}")} for d, v in n.devices.items()}}
            for name, n in self.nodes.items()} | {
            name: {"online": False, "last_seen": 0, "devices": {}} for name in self.state.get("nodes", {}) if name not in self.nodes}}


def make_server(gw: Gateway, host: str, port: int) -> ThreadingHTTPServer:
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _json(self, code: int, obj) -> None:
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(n) if n else b""
            return json.loads(raw) if raw else {}

        def _auth(self) -> str:
            return self.headers.get("Authorization", "")

        def _parts(self):
            return [p for p in self.path.split("?")[0].split("/") if p]

        # ---- node face ----
        def _node(self):
            node = gw.node_for(self._auth())
            if node is None:
                self._json(401, {"error": "unknown node token; join again with a fresh code from `mhp gateway pair`"})
            return node

        def do_POST(self):
            parts = self._parts()
            if parts[:1] == ["relay"]:
                if parts[1:] == ["join"]:
                    return self._json(*gw.join(self._body()))
                node = self._node()
                if node is None:
                    return
                if parts[1:] == ["register"]:
                    gw.register(node, self._body())
                    return self._json(200, {"ok": True, "name": node.name, "latest": U.latest_known()})
                if parts[1:] == ["reply"]:
                    gw.reply(node, self._body())
                    return self._json(200, {"ok": True})
                if parts[1:] == ["events"]:
                    gw.events(node, self._body())
                    return self._json(200, {"ok": True})
                return self._json(404, {"error": "relay: join | register | reply | events"})
            if parts == ["agent", "join"]:                 # no token yet: the code is the credential
                return self._json(*gw.join_agent(self._body()))
            # ---- agent face ----
            agent = gw.agent_for(self._auth())
            if agent is None:
                return self._json(401, {"error": AGENT_401})
            if parts == ["directory", "rpc"]:
                from .transport import dispatch
                msg = self._body()
                return self._json(200, dispatch(gw.directory, msg, agent, trusted=True) or {})
            if len(parts) == 3 and parts[2] == "rpc":
                node = gw.nodes.get(parts[0])
                if node is None or parts[1] not in node.devices:
                    return self._json(404, {"error": f"no device {parts[0]}/{parts[1]} behind this gateway"})
                timeout = float(self.headers.get("X-MHP-Timeout", REQUEST_TIMEOUT_S))
                return self._json(*gw.relay(node, parts[1], "rpc", self._body(), agent, timeout))
            return self._json(404, {"error": "POST /<node>/<device>/rpc or /directory/rpc"})

        def do_GET(self):
            parts = self._parts()
            if parts == ["relay", "next"]:
                node = self._node()
                if node is None:
                    return
                return self._json(200, {"requests": gw.next_requests(node)})
            if parts == ["relay", "status"]:
                if not gw.is_admin(self._auth()):
                    return self._json(401, {"error": "admin only"})
                return self._json(200, gw.status_doc())
            agent = gw.agent_for(self._auth())
            if agent is None:
                return self._json(401, {"error": AGENT_401})
            if not parts:
                return self._json(200, {"mhp_gateway": gw.state["server_name"], "directory": agent_url(gw.state, "directory"),
                                        "devices": sorted(f"{n}/{d}" for n, node in gw.nodes.items() for d in node.devices)})
            if parts == ["directory", "mhp.json"]:
                return self._json(200, gw.directory.rpc("device/describe", {}, agent))
            if parts == ["directory", "events"]:
                return self._sse(queue.Queue())
            if len(parts) == 3:
                node = gw.nodes.get(parts[0])
                if node is None or parts[1] not in node.devices:
                    return self._json(404, {"error": f"no device {parts[0]}/{parts[1]} behind this gateway"})
                if parts[2] == "mhp.json":
                    return self._json(200, node.devices[parts[1]]["nameplate"])
                if parts[2] == "events":
                    q: queue.Queue = queue.Queue()
                    key = (parts[0], parts[1])
                    gw.subs.setdefault(key, []).append(q)
                    try:
                        return self._sse(q)
                    finally:
                        gw.subs[key].remove(q)
            return self._json(404, {"error": "GET /, /<node>/<device>/mhp.json, /<node>/<device>/events, /directory/mhp.json"})

        def _sse(self, q: queue.Queue) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            try:
                while True:
                    try:
                        ev = q.get(timeout=15)
                        self.wfile.write(f"data: {json.dumps(ev)}\n\n".encode())
                    except queue.Empty:
                        self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ssl.SSLError):
                pass

    srv = ThreadingHTTPServer((host, port), H)
    srv.daemon_threads = True
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2    # nothing older answers here
    ctx.load_cert_chain(gw.state["cert"], gw.state["key"])
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    return srv


def bind_address(state: dict) -> str | None:
    """The one address this gateway answers on: the name given at `init`, resolved. Never every interface."""
    name = state["server_name"]
    try:
        return socket.gethostbyname(name)
    except OSError:
        return None


def serve(host: str | None = None, port: int | None = None) -> int:
    state = load()
    if state is None:
        say("no gateway on this machine yet. Run `mhp gateway init` first.")
        return 1
    gw = Gateway(state)
    port = port or state.get("listen", 443)
    if not host:
        host = bind_address(state)
        if host is None:
            say(f"'{state['server_name']}' does not resolve to an address on this network, so there is nothing to listen on.",
                "  Run `mhp gateway init --name <this machine's DNS name or IP>` with a name that resolves here.")
            return 1
    try:
        srv = make_server(gw, host, port)
    except PermissionError:
        say(f"port {port} needs administrator rights on this machine. Either run as administrator / with sudo, or",
            f"  mhp gateway init --listen 8443   and tell lab PCs and agents to use https://{state['server_name']}:8443")
        return 1
    except OSError as e:
        if getattr(e, "errno", None) in (errno.EADDRNOTAVAIL, 10049):      # 10049 is Windows' WSAEADDRNOTAVAIL
            say(f"{state['server_name']} resolves to {host}, but that address is not on this machine.",
                "  The gateway listens only on the address it was named with, so run it on that machine, or",
                f"  re-run `mhp gateway init --name <this machine's name or IP>` here.  (`--host <address>` overrides for one run.)")
            return 1
        say(f"cannot listen on {host}:{port}: {e}. Is another `mhp gateway serve` running?")
        return 1
    say(f"MHP gateway '{state['server_name']}' listening on https://{host}:{port}",
        f"  lab PCs join with:   mhp node <devices folder> --join {agent_url(state).rstrip('/')} <code from `mhp gateway pair`>",
        f"  agent machines join: mhp agent --join {agent_url(state).rstrip('/')} <code from `mhp gateway pair-agent`>", "  Ctrl-C to stop")
    U.watch(lambda v: say(f"OpenMHP {v} is out (this gateway runs {__version__}). `mhp gateway status` lists the lab PCs "
                          f"that are behind. To update the gateway itself: pip install -U openmhp, then restart `mhp gateway serve`."))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


# ---- commands ----------------------------------------------------------------------------------
def init(*, server_name: str | None = None, listen: int | None = None, cert: str | None = None, key: str | None = None) -> int:
    state = load() or {"agents": {}, "nodes": {}, "codes": {}}
    ip = local_ip()
    fqdn = socket.getfqdn()
    name = server_name or state.get("server_name") or ask(
        "Address lab PCs and agents will use for this gateway (a DNS name from IT, or this machine's IP)", fqdn if "." in fqdn else ip)
    port = int(listen or state.get("listen") or ask("Port to listen on (443 needs administrator rights; 8443 does not)", "443"))
    if cert and key:
        crt, k = Path(cert), Path(key)
        if not (crt.is_file() and k.is_file()):
            say(f"certificate or key not found: {crt}, {k}")
            return 1
        self_made = False
    elif state.get("cert") and Path(state["cert"]).is_file() and not state.get("self_signed"):
        crt, k, self_made = Path(state["cert"]), Path(state["key"]), False
    else:
        made = self_signed(name, ip)
        if made is None:
            say("could not make a certificate (openssl is not installed). Either install it, or ask IT for one and run:",
                "  mhp gateway init --cert <file.crt> --key <file.key>")
            return 1
        crt, k, self_made = *made, True
    state.update({"server_name": name, "listen": port, "cert": str(crt), "key": str(k), "self_signed": self_made, "ip": ip,
                  "admin_token": state.get("admin_token") or secrets.token_urlsafe(24)})
    save(state)
    say("", f"gateway '{name}' on port {port}. Settings: {STATE}",
        f"certificate: {'self-signed' if self_made else 'from IT'}, fingerprint {fingerprint_of(str(crt))}")
    if self_made:
        say("  lab PCs and agent machines pin this certificate when they join; nothing to copy by hand.",
            "  (when IT gives you a real certificate:  mhp gateway init --cert <file.crt> --key <file.key>)")
    say("", "Next:", "  1. mhp gateway serve            (add --install-service to keep it running across reboots)",
        "  2. mhp gateway pair             then run the printed line on each lab PC",
        "  3. mhp gateway pair-agent       then send the code to the person whose machine runs an AI agent",
        f"  4. the only network requirement: lab PCs and agent machines must reach {name}:{port} (over the office network or the VPN).",
        "     The gateway listens on that address only. Nothing inbound to the lab.")
    return 0


def pair() -> int:
    state = load()
    if state is None:
        say("no gateway on this machine yet. Run `mhp gateway init` first.")
        return 1
    code = new_code()
    state.setdefault("codes", {})[code] = {"expires": time.time() + CODE_TTL_S}
    save(state)
    say(f"pairing code (15 minutes, one lab PC):  {code}", "", "On the lab PC, in the folder that holds the device packages, run once:", "",
        f"  mhp node <devices folder> --join {agent_url(state).rstrip('/')} {code}", "",
        f"It will show the gateway certificate fingerprint {fingerprint_of(state['cert'])}; stop if it differs.",
        "From then on `mhp node <devices folder>` connects by itself.")
    return 0


def pair_agent(name: str | None = None) -> int:
    state = load()
    if state is None:
        say("no gateway on this machine yet. Run `mhp gateway init` first.")
        return 1
    ssh = state.get("ssh") or {}
    if ssh.get("mode") == "users":                 # each scientist gets their own Linux user before their machine joins
        from . import scientists as S, ssh_access as SA
        if not name:
            say("this gateway gives every scientist their own Linux user: name them, e.g.  sudo mhp gateway pair-agent alice")
            return 2
        try:
            sci = S.check_name(name.lower())
            for step in SA.apply_system_user(sci, ssh):
                say(f"  {step}")
        except (ValueError, PermissionError, RuntimeError) as e:
            say(str(e))
            return 1
        name = sci
        say(f"scientist '{sci}': Linux user {SA.login_for(sci, ssh)}, folder {S.folder(sci, Path(ssh['lab_root']))}", "")
    code = new_code()
    entry = {"expires": time.time() + AGENT_CODE_TTL_S, "kind": "agent"}
    if name:
        entry["name"] = re.sub(r"[^A-Za-z0-9._-]", "-", name)
    state.setdefault("codes", {})[code] = entry
    save(state)
    say(f"agent code (1 hour, one machine{', named ' + entry['name'] if name else ''}):  {code}", "",
        "Send it to the person. On their machine, once:", "",
        f"  mhp agent --join {agent_url(state).rstrip('/')} {code}", "",
        f"It will show the gateway certificate fingerprint {fingerprint_of(state['cert'])}; they should stop if it differs.",
        "From then on `mhp-mcp` on that machine reaches every instrument behind this gateway. Nothing to paste.")
    return 0


def add_agent(name: str) -> int:
    state = load()
    if state is None:
        say("no gateway on this machine yet. Run `mhp gateway init` first.")
        return 1
    name = re.sub(r"[^A-Za-z0-9._-]", "-", name)
    existing = next((t for t, n in state["agents"].items() if n == name), None)
    token = existing or secrets.token_urlsafe(24)
    state["agents"][token] = name
    save(state)
    say("", f"agent '{name}' may use the gateway. On that machine, run once:" if not existing else
        f"agent '{name}' already had a token; here it is again:", "", *agent_lines(state, token))
    return 0


def agent_lines(state: dict, token: str) -> list[str]:
    win = platform.system() == "Windows"
    kw = "set" if win else "export"
    lines = [f"  {kw} OPENMHP_DEVICE_TOKEN={token}"]
    if state.get("self_signed"):
        lines.append(f"  {kw} SSL_CERT_FILE=<copy of {state['cert']}>")
    lines.append(f"  mhp-mcp --directory {agent_url(state, 'directory')}          (or: mhp lab add <device url> from `mhp gateway status`)")
    return lines


def remove(kind: str, name: str) -> int:
    state = load()
    if state is None:
        say("no gateway on this machine.")
        return 1
    if kind == "node":
        if state["nodes"].pop(name, None) is None:
            say(f"no node '{name}'. Known: {', '.join(state['nodes']) or 'none'}")
            return 1
    else:
        toks = [t for t, n in state["agents"].items() if n == name]
        if not toks:
            say(f"no agent '{name}'. Known: {', '.join(sorted(set(state['agents'].values()))) or 'none'}")
            return 1
        for t in toks:
            del state["agents"][t]
    save(state)
    say(f"removed {kind} '{name}'" + (" (takes effect at its next request)" if kind == "node" else ""))
    return 0


def _live() -> dict | None:
    state = load()
    ctx = ssl.create_default_context(cafile=state["cert"]) if state.get("self_signed") else ssl.create_default_context()
    ctx.check_hostname = False
    req = urllib.request.Request(f"https://127.0.0.1:{state.get('listen', 443)}/relay/status",
                                 headers={"Authorization": f"Bearer {state['admin_token']}"})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=5) as r:
            return json.loads(r.read())
    except Exception:                                      # noqa: BLE001
        return None


NODE_UPGRADE_GENERIC = ('npx -y openmhp-cli@latest node <devices folder>   (or: pip install -U "openmhp[node]" && '
                        'mhp node <devices folder> --install-service)')     # for a node too old to say its own


def status() -> int:
    state = load()
    if state is None:
        say("no gateway on this machine. Run `mhp gateway init` to make one.")
        return 1
    live = _live()
    U.refresh()                                            # at most once a day; quiet when offline
    latest = U.latest_known((live or {}).get("latest"))
    say(f"gateway {agent_url(state)}   ({'running' if live else 'NOT running: mhp gateway serve'})   OpenMHP {__version__}",
        f"settings: {STATE}", f"certificate: {'self-signed, ' if state.get('self_signed') else ''}{state['cert']}", "")
    if U.newer(latest):
        say(f"OpenMHP {latest} is out. Update this gateway with:  pip install -U openmhp   then restart `mhp gateway serve`.", "")
    behind = []
    if not state["nodes"]:
        say("lab PCs: none joined yet. `mhp gateway pair`, then run the printed line on the lab PC.")
    for name in sorted(state["nodes"]):
        n = (live or {}).get("nodes", {}).get(name, {})
        when = n.get("last_seen") or 0
        flag = "online" if n.get("online") else (f"offline, last seen {int(time.time() - when)}s ago" if when else "offline")
        ver = ""
        if n.get("online") or n.get("openmhp"):
            v = n.get("openmhp")
            old = v is None or U.newer(latest, v)
            ver = f", OpenMHP {v or '0.10.0 or older'}" + (f"  BEHIND ({latest} is out)" if old else "")
            if old:
                behind.append((name, n.get("upgrade")))
        say(f"lab PC '{name}': {flag}{ver}")
        for did, d in sorted(n.get("devices", {}).items()):
            say(f"    {d['url']:62s} {d.get('state') or ''}")
    if behind:
        say("", f"{len(behind)} lab PC(s) run an older OpenMHP. They keep working; update each when convenient. On that PC run:")
        for name, cmd in behind:
            say(f"  {name}:  {cmd or NODE_UPGRADE_GENERIC}")
    say("", "agents allowed through: " + (", ".join(sorted(set(state["agents"].values()))) or "none yet (mhp gateway pair-agent)"))
    ssh = state.get("ssh")
    say("scientists over SSH: " + (f"{ssh['mode']} mode, {ssh['host']}:{ssh.get('port', 22)}, folders in {ssh['lab_root']}"
                                   if ssh else "off (mhp gateway ssh)"))
    say("", f"network requirement: lab PCs and agent machines must reach {state['server_name']}:{state.get('listen', 443)}. Nothing inbound to the lab.")
    return 0


def check() -> int:
    state = load()
    if state is None:
        say("no gateway on this machine. Run `mhp gateway init`.")
        return 1
    problems = 0

    def ok(msg):
        say(f"  OK   {msg}")

    def fix(msg, *how):
        nonlocal problems
        problems += 1
        say(f"  FIX  {msg}", *[f"       {h}" for h in how])

    say("gateway check", "")
    live = _live()
    if live is None:
        fix(f"nothing answers on port {state.get('listen', 443)}", "start it:  mhp gateway serve   (or mhp gateway serve --install-service)")
    else:
        ok(f"gateway is running on port {state.get('listen', 443)}")
        for name in sorted(state["nodes"]):
            n = live["nodes"].get(name, {})
            if n.get("online"):
                ok(f"lab PC '{name}' connected, {len(n.get('devices', {}))} device(s)")
            else:
                fix(f"lab PC '{name}' is not connected", f"on that PC, is `mhp node` running? It reconnects by itself; its window says why it cannot.")
    if not state["agents"]:
        fix("no agent is allowed through", "mhp gateway pair-agent, then `mhp agent --join ...` on the agent machine")
    elif live is not None:
        tok = next(iter(state["agents"]))
        ctx = ssl.create_default_context(cafile=state["cert"]) if state.get("self_signed") else ssl.create_default_context()
        ctx.check_hostname = False
        for name, n in live["nodes"].items():
            for did in n.get("devices", {}):
                req = urllib.request.Request(f"https://127.0.0.1:{state.get('listen', 443)}/{name}/{did}/mhp.json",
                                             headers={"Authorization": f"Bearer {tok}"})
                try:
                    with urllib.request.urlopen(req, context=ctx, timeout=5) as r:
                        ok(f"agents can see {name}/{did} ({json.loads(r.read())['device']['id']})")
                except Exception as e:                       # noqa: BLE001
                    fix(f"{name}/{did} fails through the gateway ({getattr(e, 'code', type(e).__name__)})")
    say("", "everything is in order" if not problems else f"{problems} thing(s) to fix, listed above")
    return 0 if not problems else 1


def ssh_setup(words: list[str]) -> int:
    """`mhp gateway ssh [users] [login=NAME] [port=N] [host=NAME] [host-key=FILE] [apply]`: turn on SSH access
    for scientists' machines. Without `apply` it records the settings and prints what to install; with
    `apply` (as root) it writes the sshd snippet and the key helper too."""
    from . import scientists as S, ssh_access as SA
    import getpass
    state = load()
    if state is None:
        say("no gateway on this machine yet. Run `mhp gateway init` first.")
        return 1
    opts = dict(w.split("=", 1) for w in words if "=" in w)
    flags = {w for w in words if "=" not in w}
    unknown = flags - {"users", "single", "apply"} | set(opts) - {"login", "port", "host", "host-key", "root"}
    if unknown:
        say(f"unknown: {', '.join(sorted(unknown))}. Usage: mhp gateway ssh [users] [login=NAME] [port=N] [host=NAME] "
            "[host-key=FILE] [root=DIR] [apply]")
        return 2
    service_user = os.environ.get("SUDO_USER") or getpass.getuser()
    hk = SA.host_key(opts.get("host-key"))
    if hk is None:
        say("cannot read this machine's SSH host key (is the OpenSSH server installed?). Give one with host-key=<file.pub>.")
        return 1
    old = state.get("ssh") or {}
    mode = "users" if "users" in flags else ("single" if "single" in flags else old.get("mode", "single"))
    # users mode: scientists' users must reach the lab root, so it lives outside this gateway's private folder
    lab_root = Path(opts.get("root") or old.get("lab_root") or ("/srv/openmhp" if mode == "users" else S.lab_root())).resolve()
    cfg = {"mode": mode,
           "login": opts.get("login") or old.get("login") or service_user,
           "port": int(opts.get("port") or old.get("port") or 22),
           "host": opts.get("host") or old.get("host") or state["server_name"],
           "host_key": hk, "lab_root": str(lab_root), "python": sys.executable,
           "service_user": service_user, "group": old.get("group", "mhp-scientists"), "openmhp_home": str(HOME.resolve())}
    state["ssh"] = cfg
    save(state)
    try:
        lab_root.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        say(f"cannot create {lab_root} as {getpass.getuser()}: run `sudo mkdir -p {lab_root} && sudo chown {service_user} {lab_root}` once.")
    say(f"scientists' machines will use SSH to {cfg['host']}:{cfg['port']} ({cfg['mode']} mode"
        + (f", account {cfg['login']}" if cfg["mode"] == "single" else ", one Linux user per scientist") + ")",
        f"their folders: {cfg['lab_root']}/scientists/", "")
    if "apply" in flags:
        if not hasattr(os, "geteuid") or os.geteuid() != 0:
            say("`apply` writes into /etc and /usr/local: run it with sudo.")
            return 1
        SA.HELPER_PATH.parent.mkdir(parents=True, exist_ok=True)
        SA.HELPER_PATH.write_text(SA.helper_script(cfg), encoding="utf-8")
        os.chmod(SA.HELPER_PATH, 0o755)
        SA.SNIPPET_PATH.write_text(SA.sshd_snippet(cfg), encoding="utf-8")
        say(f"wrote {SA.HELPER_PATH} and {SA.SNIPPET_PATH}. Reload sshd to use them:  sudo systemctl reload ssh")
    else:
        say(f"To finish, run once as root:  sudo {sys.executable} -m openmhp.cli gateway ssh apply",
            f"It writes {SA.HELPER_PATH}:", "", SA.helper_script(cfg), f"and {SA.SNIPPET_PATH}:", "", SA.sshd_snippet(cfg))
    say("Machines that pair from now on (mhp gateway pair-agent) get SSH access with no keys to paste.")
    return 0


def main(verb: str | None, args: list[str], *, server_name=None, listen=None, cert=None, key=None, host=None,
         install_service=False, dry_run_service=False) -> int:
    if verb in (None, "status", "list"):
        return status()
    if verb == "init":
        return init(server_name=server_name or (args[0] if args else None), listen=listen, cert=cert, key=key)
    if verb == "serve":
        if install_service or dry_run_service:
            from . import service as svc
            state = load()
            if state is None:
                say("run `mhp gateway init` first")
                return 1
            r = svc.install_command("openmhp-gateway", [sys.executable, "-m", "openmhp.cli", "gateway", "serve"],
                                    f"OpenMHP gateway {state['server_name']}", dry_run=dry_run_service)
            for step in r["steps"]:
                say(f"  {step}")
            say(("installed. " + r.get("note", "")) if r["ok"] else f"FAILED: {r.get('error') or 'see above'}")
            return 0 if r["ok"] else 1
        return serve(host, listen)
    if verb == "pair":
        return pair()
    if verb == "pair-agent":
        return pair_agent(args[0] if args else None)
    if verb == "add-agent":
        if not args:
            say("usage: mhp gateway add-agent <name of the agent machine>")
            return 2
        return add_agent(args[0])
    if verb in ("remove-node", "remove-agent"):
        if not args:
            say(f"usage: mhp gateway {verb} <name>")
            return 2
        return remove(verb.split("-")[1], args[0])
    if verb == "check":
        return check()
    if verb == "ssh":
        return ssh_setup(args)
    say(f"unknown gateway command {verb!r}. One of: init, serve, pair, pair-agent, add-agent, remove-agent, remove-node, status, check, ssh")
    return 2
