"""MHP transports: stdio (newline-delimited JSON-RPC) and HTTP (+SSE).

Both carry exactly the same JSON-RPC 2.0 messages; pick stdio for a driver
running on the bench PC next to the instrument, HTTP for a driver that must be
reachable across the lab network. ``GET /mhp.json`` serves the descriptor so
agents can discover a device with nothing but its URL.
"""
from __future__ import annotations

import hmac
import json
import os
import secrets
import time
import queue
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .driver import ApprovalRequired, Driver, MHPError


def dispatch(driver: Driver, msg: dict, client: str, *, trusted: bool = True) -> dict | None:
    """Turn one JSON-RPC request into one response (None for notifications).

    ``trusted`` is the transport's statement that this caller is a host in the sense of SPEC 7.2:
    the side that can report what a person said. `approved: true` is exactly that report, so a
    caller the transport cannot place -- a stranger on the network reaching an open port -- has it
    dropped here, before the gates ever see it. Everything else it asked for is still served: the
    device simply refuses the step that needed a human, and says why.
    """
    mid = msg.get("id")
    params = msg.get("params") or {}
    ignored_approved = False
    if not trusted and isinstance(params, dict) and params.get("approved") is not None:
        params = {k: v for k, v in params.items() if k != "approved"}
        ignored_approved = True
    err_ts = time.time()                 # device-anchored, so a client can align it with its own receipt
    try:
        result = driver.rpc(msg.get("method", ""), params, client)
        if mid is None:
            return None
        return {"jsonrpc": "2.0", "id": mid, "result": result}
    except MHPError as e:
        # the taxonomy (C16) travels with every failure, so a caller branches on fields
        # rather than parsing prose; `state` is what the device is in now, which only it knows
        err = {"code": e.code, "message": e.message, "ts": err_ts, **e.taxonomy(),
               "state": getattr(driver, "state", None)}
        if e.data is not None:
            err["data"] = e.data
        if ignored_approved and e.code == ApprovalRequired.code:
            err["message"] += ("; the `approved` flag in this request was ignored because this channel cannot "
                               "assert it: it is neither this machine nor authenticated to this device")
            err["data"] = {**(e.data or {}), "ignoredApproved": True}
    except KeyError as e:
        err = {"code": -32602, "message": f"missing param {e}", "ts": err_ts}
    except Exception as e:                          # noqa: BLE001
        err = {"code": -32603, "message": f"{type(e).__name__}: {e}", "ts": err_ts}
    return {"jsonrpc": "2.0", "id": mid, "error": err}


# ------------------------------------------------------- authentication and the trust boundary ---- #
def is_loopback(addr: str) -> bool:
    """True for an address that no other machine can reach. `0.0.0.0` and `::` are not: they are
    every address this host has, which is the point of asking."""
    a = (addr or "").strip().strip("[]").lower()
    return a.startswith("127.") or a in ("::1", "0:0:0:0:0:0:0:1", "localhost")


def device_token_file(home: Path | None = None) -> Path:
    if home is None:
        from .fleet import HOME                       # late: fleet imports the client, which imports this
        home = HOME
    return Path(home) / "device_token"


def device_token(*, create: bool = False, home: Path | None = None) -> str | None:
    """OPENMHP_DEVICE_TOKEN, or the token in <home>/device_token (created with mode 0600).

    A server creates it when it is about to listen where another machine can reach it; a client
    only ever reads it. So a client on the same machine needs no configuration, and a client
    anywhere else is handed the secret deliberately. Same shape as the bridge's own http_token.
    """
    env = os.environ.get("OPENMHP_DEVICE_TOKEN")
    if env:
        return env
    path = device_token_file(home)
    if path.is_file():
        return path.read_text().strip() or None
    if not create:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    tok = secrets.token_urlsafe(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(tok)
    return tok


# ---------------------------------------------------------------- stdio ---- #
def utf8_stdio(*streams) -> None:
    """MHP and MCP over stdio are UTF-8. A pipe otherwise uses the locale's encoding, which on Windows is the
    ANSI code page, so a client's '°C' would arrive as 'Â°C'."""
    for s in streams:
        if hasattr(s, "reconfigure"):               # a real text stream, not a test double
            s.reconfigure(encoding="utf-8", errors=s.errors)


def serve_stdio(driver: Driver, *, stdin=None, stdout=None) -> None:
    """Newline-delimited JSON-RPC over stdin/stdout.

    Reading never waits on handling. An instrument has one serial port, so ordinary requests are
    still handled one at a time and in the order they arrive -- a client that pipelines a write and
    then a read means them that way round. But the calls that must not wait behind device I/O are
    answered the moment they are read, each on a thread of its own: `safety/estop` above all, and the
    status, describe and lease calls the driver already handles outside its request lock. Before this,
    a stop sent while a three-second read was in flight was not even *read* until the read finished,
    which made the one call an agent may always make the one call that queued. Over HTTP every
    request already arrives on its own thread; stdio was the odd one out.
    """
    from .driver import _UNLOCKED as NO_WAIT       # the driver's own list of what must not queue

    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    utf8_stdio(stdin, stdout)
    out_lock = threading.Lock()
    inbox: "queue.Queue[dict | None]" = queue.Queue()

    def send(obj: dict) -> None:
        with out_lock:
            stdout.write(json.dumps(obj) + "\n")
            stdout.flush()

    def answer(msg: dict) -> None:
        try:
            resp = dispatch(driver, msg, client="stdio")
            if resp is not None:
                send(resp)
        except Exception:                          # noqa: BLE001  dispatch answers its own errors; this is
            pass                                   # a broken pipe, and there is nowhere left to report it

    def ordinary() -> None:
        for msg in iter(inbox.get, None):
            answer(msg)

    worker = threading.Thread(target=ordinary, daemon=True, name="mhp-stdio-requests")
    worker.start()
    driver.subscribers.append(send)
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
            continue
        if msg.get("method") in NO_WAIT:
            threading.Thread(target=answer, args=(msg,), daemon=True).start()
        else:
            inbox.put(msg)
    inbox.put(None)                                # stdin closed: finish the request in flight, then stop
    worker.join(30.0)


# ----------------------------------------------------------------- http ---- #
class ExclusiveHTTPServer(ThreadingHTTPServer):
    """One server per port. HTTPServer sets SO_REUSEADDR, which on Linux and macOS only lets a restart rebind
    a port whose old connections are in TIME_WAIT, but on Windows lets a second server bind a port another one
    is listening on: a client could then reach either, so an agent could command a different device than the
    one it addressed. Windows rebinds past TIME_WAIT without the option, so it is off there, as
    socket.create_server() and asyncio also leave it."""
    allow_reuse_address = os.name != "nt"


def serve_http(driver: Driver, host: str = "127.0.0.1", port: int = 8765, *,
               token: str | bool | None = None) -> None:
    """Serve one device over HTTP (+SSE).

    ``token`` gates POST /rpc and GET /events with ``Authorization: Bearer <token>``. The default,
    None, means: nothing while the bind address is loopback, where the operating system is already
    the boundary, and a generated token (``~/.openmhp/device_token``) the moment the address is one
    another machine can reach -- a port that operates an instrument should not answer the whole
    network unasked. Pass False to serve it open anyway, behind a proxy that authenticates or on an
    isolated instrument VLAN; requests from off this machine are then served, but cannot assert
    `approved` (SPEC 7.2). GET /mhp.json is the device's nameplate and stays open either way, so
    `mhp lab scan` and discovery keep working.
    """
    generated = token is None
    if generated:
        token = False if is_loopback(host) else device_token(create=True)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):               # quiet
            pass

        def _json(self, code: int, obj) -> None:
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self) -> bool:
            if not token:
                return True
            auth = self.headers.get("Authorization", "")
            return auth.startswith("Bearer ") and hmac.compare_digest(auth[7:].encode(), str(token).encode())

        def _drain(self) -> None:
            """Read the body we are about to refuse, so the refusal is what the client sees.

            Replying without reading it leaves the request sitting in the socket buffer, and
            closing a socket with unread data sends a reset: on Windows the client's own send
            then fails with "connection aborted" and it never sees the 401 -- a device that
            looks unreachable instead of one that told you it wants a token.
            """
            try:
                n = int(self.headers.get("Content-Length", 0))
            except ValueError:
                n = 0
            while n > 0:
                chunk = self.rfile.read(min(n, 1 << 16))
                if not chunk:
                    break
                n -= len(chunk)

        def _unauthorized(self) -> None:
            self._drain()
            self._json(401, {"error": "this device requires 'Authorization: Bearer <token>'; the operator has "
                                      "the token (OPENMHP_DEVICE_TOKEN or ~/.openmhp/device_token on its host)"})

        def do_GET(self):
            if self.path == "/mhp.json":            # discovery document: the nameplate, not control
                self._json(200, driver.rpc("device/describe", {}, "discovery"))
            elif self.path == "/events" and not self._authorized():
                self._unauthorized()
            elif self.path == "/events":            # SSE stream of notifications
                q: queue.Queue = queue.Queue()
                driver.subscribers.append(q.put)
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
                except (BrokenPipeError, ConnectionResetError):
                    pass
                finally:
                    driver.subscribers.remove(q.put)
            else:
                self._json(404, {"error": "use POST /rpc, GET /mhp.json, GET /events"})

        def do_POST(self):
            if self.path != "/rpc":
                self._drain()
                return self._json(404, {"error": "POST /rpc"})
            if not self._authorized():
                return self._unauthorized()
            n = int(self.headers.get("Content-Length", 0))
            client = self.headers.get("X-MHP-Client", self.client_address[0])
            try:
                msg = json.loads(self.rfile.read(n))
            except json.JSONDecodeError:
                return self._json(400, {"jsonrpc": "2.0", "id": None,
                                        "error": {"code": -32700, "message": "parse error"}})
            # authenticated, or local: either way the transport can place this caller well enough
            # to pass on what it says about a person. Anything else gets its `approved` dropped.
            resp = dispatch(driver, msg, client, trusted=bool(token) or is_loopback(self.client_address[0]))
            self._json(200, resp if resp is not None else {})

    srv = ExclusiveHTTPServer((host, port), Handler)   # binds AND listens: we are accepting from here on
    print(f"MHP {driver.descriptor['device']['id']} listening on http://{host}:{port}", file=sys.stderr)
    if token and generated:
        where = "OPENMHP_DEVICE_TOKEN" if os.environ.get("OPENMHP_DEVICE_TOKEN") else str(device_token_file())
        print(f"  reachable from the network, so /rpc and /events require 'Authorization: Bearer <token>'; "
              f"the token is in {where}. On another machine: export OPENMHP_DEVICE_TOKEN=<token>", file=sys.stderr)
    elif not token and not is_loopback(host):
        print("  WARNING: no authentication and reachable from the network. Requests from off this machine "
              "are served but cannot confirm approval-gated operations.", file=sys.stderr)

    def _advertise() -> None:
        """Off the startup path on purpose. The socket accepts connections the moment the line
        above runs, so anything slow between there and serve_forever() leaves a client connected
        with nobody reading it. mDNS registration probes for name conflicts and waits out those
        timeouts on a network with no responder, which is seconds. Discovery is best-effort;
        answering the instrument's own port is not."""
        try:
            from .discovery import advertise
            if advertise(driver.descriptor["device"], port, host):
                print("  advertised as _mhp._tcp on the LAN", file=sys.stderr)
        except Exception as e:                       # noqa: BLE001  discovery is best-effort
            print(f"  (mDNS advertise skipped: {e})", file=sys.stderr)

    threading.Thread(target=_advertise, daemon=True).start()
    srv.serve_forever()
