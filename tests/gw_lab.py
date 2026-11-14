"""A simulated lab for gateway tests: a gateway served in-process over TLS, one lab PC ("bench") with a
thermocycler, a simulated OB1 and a robot arm, and small HTTP helpers. Set OPENMHP_HOME before importing.
"""
import contextlib
import io
import json
import shutil
import socket
import ssl
import threading
import time
import urllib.error
import urllib.request


def start_lab():
    from openmhp import gateway as G, relay as R
    from openmhp.package import load_driver
    if not shutil.which("openssl"):
        return None
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0))
        port = so.getsockname()[1]
    with contextlib.redirect_stderr(io.StringIO()):
        assert G.init(server_name="127.0.0.1", listen=port) == 0
        assert G.pair() == 0
    state = G.load()
    gw = G.Gateway(state)
    srv = G.make_server(gw, "127.0.0.1", port)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"https://127.0.0.1:{port}"
    ctx = ssl.create_default_context(cafile=state["cert"])
    drivers = {}
    for folder, sim in (("openmhp/devices/thermocycler-01", False), ("supported-devices/elveflow-ob1", True),
                        ("openmhp/devices/arm-01", False)):
        d = load_driver(folder, sim=sim)
        drivers[d.descriptor["device"]["id"]] = d
    code = next(iter(G.load()["codes"]))
    with contextlib.redirect_stderr(io.StringIO()):
        cfg = R.join(base, code, drivers, name="bench", quiet=True)
        node = R.RelayClient(cfg, drivers)
        node.start()
    end = time.time() + 10
    while time.time() < end and not all(d in gw.nodes.get("bench", G.Node("x")).devices for d in drivers):
        time.sleep(0.05)

    def rpc(token, path, method, params=None):
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}).encode()
        req = urllib.request.Request(f"{base}/{path}/rpc", data=body, method="POST",
                                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def get(token, path):
        req = urllib.request.Request(f"{base}/{path}", headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")
    return gw, drivers, rpc, get, node, base, ctx
