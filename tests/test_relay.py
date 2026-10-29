"""End-to-end test of the MHP relay (SPEC 9.2): a gateway served in-process over TLS, a lab PC that joins
with a pairing code and relays a simulated OB1 and the bundled thermocycler, and agents that know only the
gateway. Stdlib only, no root, no nginx. Covers: 401s, describe/read/invoke/wait, SSE through the relay,
leases per agent identity, the directory, node offline → 503 (never re-sent), reconnect → re-register, check().

    PYTHONPATH=. python tests/test_relay.py
"""
import contextlib
import io
import json
import os
import shutil
import socket
import ssl
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, ".")
os.environ["OPENMHP_HOME"] = tempfile.mkdtemp(prefix="openmhp-relay-tests-")
HOME = Path(os.environ["OPENMHP_HOME"])

SKIP = None if shutil.which("openssl") else "openssl is needed to make the gateway's certificate"
try:
    import pytest
    pytestmark = pytest.mark.skipif(bool(SKIP), reason=SKIP or "")
except ImportError:
    pytest = None


class raises:
    def __init__(self, exc):
        self.exc, self.value = exc, None
    def __enter__(self):
        return self
    def __exit__(self, et, ev, tb):
        assert et is not None and issubclass(et, self.exc), f"expected {self.exc.__name__}, got {et}: {ev}"
        self.value = ev
        return True


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(pred, timeout=10, what="condition"):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return
        time.sleep(0.05)
    raise TimeoutError(what)


def wait_quiet(node, timeout):
    """Until the node's client has really stopped: no poll in progress and none started for a moment.
    (Between two back-to-back polls there is a sub-millisecond gap with no poll in progress.)"""
    end = time.time() + timeout
    while time.time() < end:
        if node.polling == 0 and time.time() - node.last_poll > 0.7:
            return
        time.sleep(0.05)
    raise TimeoutError("node client did not stop polling")


def test_relay_end_to_end():
    from openmhp import gateway as G, relay as R
    from openmhp.client import RemoteError, connect
    from openmhp.driver import NotLeased
    from openmhp.package import load_driver

    # ---- gateway: init (no terminal: everything passed in), serve on a free port in a thread
    port = free_port()
    log = io.StringIO()
    with contextlib.redirect_stderr(log):
        assert G.init(server_name="127.0.0.1", listen=port) == 0
    state = G.load()
    assert state["self_signed"] and Path(state["cert"]).is_file()
    gw = G.Gateway(state)
    srv = G.make_server(gw, "127.0.0.1", port)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"https://127.0.0.1:{port}"
    ctx = ssl.create_default_context(cafile=state["cert"])
    os.environ["SSL_CERT_FILE"] = state["cert"]                 # HttpDevice uses the default context
    ssl._create_default_https_context = lambda: ctx

    def raw(path, token=None, method="GET", body=None, headers=None):
        req = urllib.request.Request(base + path, data=body, method=method,
                                     headers={**({"Authorization": f"Bearer {token}"} if token else {}), **(headers or {})})
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=10) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    # ---- agents
    with contextlib.redirect_stderr(log):
        assert G.add_agent("agent-a") == 0 and G.add_agent("agent-b") == 0
    tokens = {n: t for t, n in G.load()["agents"].items()}
    A, B = tokens["agent-a"], tokens["agent-b"]
    assert raw("/")[0] == 401 and raw("/", token="nope")[0] == 401
    st, doc = raw("/", token=A)
    assert st == 200 and doc["devices"] == []

    # ---- lab PC joins with a code, relays two simulated instruments
    ob1 = load_driver("supported-devices/elveflow-ob1", sim=True)
    tc = load_driver("openmhp/devices/thermocycler-01")
    drivers = {ob1.descriptor["device"]["id"]: ob1, tc.descriptor["device"]["id"]: tc}
    with contextlib.redirect_stderr(log):
        assert G.pair() == 0
    code = next(iter(G.load()["codes"]))
    with raises(SystemExit) as ei:
        R.join(base, "0000-0000", drivers, name="bench", quiet=True)
    assert "refused the code" in str(ei.value)
    cfg = R.join(base, code, drivers, name="bench", quiet=True)
    assert cfg["name"] == "bench" and R.NODE_FILE.is_file() and Path(cfg["pin"]).is_file()
    with raises(SystemExit):                                   # single use
        R.join(base, code, drivers, name="bench2", quiet=True)
    node = R.RelayClient(cfg, drivers)
    node.start()
    oid = ob1.descriptor["device"]["id"]
    wait_for(lambda: raw("/", token=A)[1]["devices"] == sorted(f"bench/{d}" for d in drivers), what="registration")

    # ---- an ordinary client through the relay: nameplate, card, signals, job, SSE
    os.environ["OPENMHP_DEVICE_TOKEN"] = A
    assert raw(f"/bench/{oid}/mhp.json", token=A)[1]["device"]["id"] == oid
    a = connect(f"{base}/bench/{oid}/", "ob1", session="spoofed")
    assert a.describe("card")["id"] == oid
    assert "pressure_ch1" in a.read("pressure_ch1", "connected")
    seen = []
    a.subscribe(seen.append)
    time.sleep(0.3)                                            # let the SSE thread connect before events fly
    job = a.invoke("vent")
    a.wait(job, timeout=30)
    assert a.status(job)["state"] == "done"
    wait_for(lambda: seen, what="SSE event through the relay")

    # ---- identity is the gateway's: same agent token shares the lease, another agent is refused
    a.acquire(ttl=30)
    a2 = connect(f"{base}/bench/{oid}/", "ob1", session="another-spoof")
    a2.write("pressure_setpoint_ch1", 100)
    os.environ["OPENMHP_DEVICE_TOKEN"] = B
    b = connect(f"{base}/bench/{oid}/", "ob1", session="agent-a")
    with raises(RemoteError) as ei:
        b.write("pressure_setpoint_ch1", 200)
    assert ei.value.code == NotLeased.code, ei.value
    a.release()
    b.write("pressure_setpoint_ch1", 200)

    # ---- directory: one URL, every relayed device, targets are gateway URLs, live state from the node
    d = connect(f"{base}/directory/", "dir")
    res = d.call("directory/search", {"query": "thermocycler"})["results"]
    assert res and res[0]["target"].startswith(f"{base}/bench/") and res[0]["state"] not in (None, "offline")

    # ---- node goes away: 503, nothing queued; comes back: re-registers, works, nothing replayed
    node.close()
    wait_quiet(gw.nodes["bench"], G.POLL_S + 20)
    gw.nodes["bench"].last_poll -= 5                             # a dropped link shows within seconds, not OFFLINE_S
    st, err = raw(f"/bench/{oid}/rpc", token=B, method="POST", body=b'{"jsonrpc":"2.0","id":1,"method":"ping"}',
                  headers={"Content-Type": "application/json"})
    assert st == 503 and "offline" in err["error"]
    assert d.call("directory/search", {"query": "thermocycler"})["results"][0]["state"] == "offline"
    node2 = R.RelayClient(R.load_node_config(), drivers)
    node2.start()
    wait_for(lambda: gw.nodes["bench"].online, what="reconnect")
    b.read("connected")
    for n in gw.nodes.values():
        assert not n.inflight

    # ---- the client turns a gateway refusal into words, not a traceback (node offline → RemoteError)
    node2.close()
    wait_quiet(gw.nodes["bench"], G.POLL_S + 20)
    gw.nodes["bench"].last_poll -= 5
    with raises(RemoteError) as ei:
        b.read("connected")
    assert "offline" in str(ei.value) and "nothing was sent" in str(ei.value)

    # ---- a PC that lost node.json pairs again and gets its own name back; the old token is dead
    old_token = R.load_node_config()["token"]
    with contextlib.redirect_stderr(log):
        assert G.pair() == 0
    code2 = next(c for c in G.load()["codes"])
    cfg2 = R.join(base, code2, drivers, name="bench", quiet=True)
    assert cfg2["name"] == "bench" and cfg2["token"] != old_token
    gw.refresh()
    assert old_token not in gw.node_by_token
    node2 = R.RelayClient(cfg2, drivers)
    node2.start()
    wait_for(lambda: gw.nodes.get("bench") is not None and gw.nodes["bench"].online, what="re-pair reconnect")
    assert b.read("connected")

    # ---- a request the node does not answer in time is dropped, with a clear message
    gw.nodes["bench"].queue.put({"rid": "ghost", "device": oid, "kind": "rpc", "client": "x", "trusted": True, "body": {}})
    st, err = raw(f"/bench/{oid}/rpc", token=B, method="POST", body=b'{"jsonrpc":"2.0","id":2,"method":"ping"}',
                  headers={"Content-Type": "application/json", "X-MHP-Timeout": "20"})
    assert st == 200                                             # unknown rids are discarded by the node; real one answered

    # ---- status/check see the live picture
    with contextlib.redirect_stderr(log):
        assert G.check() == 0, log.getvalue()
        assert G.status() == 0
    assert "everything is in order" in log.getvalue() and "lab PC 'bench': online" in log.getvalue()
    for dev in (a, a2, b, d):
        dev.close()
    node2.close()
    srv.shutdown()
    os.environ.pop("OPENMHP_DEVICE_TOKEN", None)


if __name__ == "__main__":
    if SKIP:
        print("skipped:", SKIP)
    else:
        test_relay_end_to_end()
        print("ok: relay end to end")
