"""MHP transports: stdio (newline-delimited JSON-RPC) and HTTP (+SSE).

Both carry exactly the same JSON-RPC 2.0 messages; pick stdio for a driver
running on the bench PC next to the instrument, HTTP for a driver that must be
reachable across the lab network. ``GET /mhp.json`` serves the descriptor so
agents can discover a device with nothing but its URL.
"""
from __future__ import annotations

import json
import queue
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .driver import Driver, MHPError


def dispatch(driver: Driver, msg: dict, client: str) -> dict | None:
    """Turn one JSON-RPC request into one response (None for notifications)."""
    mid = msg.get("id")
    try:
        result = driver.rpc(msg.get("method", ""), msg.get("params") or {}, client)
        if mid is None:
            return None
        return {"jsonrpc": "2.0", "id": mid, "result": result}
    except MHPError as e:
        err = {"code": e.code, "message": e.message}
        if e.data is not None:
            err["data"] = e.data
    except KeyError as e:
        err = {"code": -32602, "message": f"missing param {e}"}
    except Exception as e:                          # noqa: BLE001
        err = {"code": -32603, "message": f"{type(e).__name__}: {e}"}
    return {"jsonrpc": "2.0", "id": mid, "error": err}


# ---------------------------------------------------------------- stdio ---- #
def serve_stdio(driver: Driver) -> None:
    out_lock = threading.Lock()

    def send(obj: dict) -> None:
        with out_lock:
            sys.stdout.write(json.dumps(obj) + "\n")
            sys.stdout.flush()

    driver.subscribers.append(send)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
            continue
        resp = dispatch(driver, msg, client="stdio")
        if resp is not None:
            send(resp)


# ----------------------------------------------------------------- http ---- #
def serve_http(driver: Driver, host: str = "127.0.0.1", port: int = 8765) -> None:
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

        def do_GET(self):
            if self.path == "/mhp.json":            # discovery document
                self._json(200, driver.rpc("device/describe", {}, "discovery"))
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
                return self._json(404, {"error": "POST /rpc"})
            n = int(self.headers.get("Content-Length", 0))
            client = self.headers.get("X-MHP-Client", self.client_address[0])
            try:
                msg = json.loads(self.rfile.read(n))
            except json.JSONDecodeError:
                return self._json(400, {"jsonrpc": "2.0", "id": None,
                                        "error": {"code": -32700, "message": "parse error"}})
            resp = dispatch(driver, msg, client)
            self._json(200, resp if resp is not None else {})

    srv = ThreadingHTTPServer((host, port), Handler)   # binds AND listens: we are accepting from here on
    print(f"MHP {driver.descriptor['device']['id']} listening on http://{host}:{port}", file=sys.stderr)

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
