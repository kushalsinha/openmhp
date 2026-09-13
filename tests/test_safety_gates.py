"""Behavioral tests for the safety gates and runtime guarantees SPEC.md declares MUST hold: typed and
bounded values, watchdog and lease enforcement, the elicitation trust boundary, plan-mode isolation,
fail-closed state on an uncertain outcome, and the transports around all of it. No hardware; only localhost.

    PYTHONPATH=. python tests/test_safety_gates.py
"""
import asyncio
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, ".")
os.environ["OPENMHP_HOME"] = tempfile.mkdtemp(prefix="openmhp-safety-tests-")
HOME = Path(os.environ["OPENMHP_HOME"])

from openmhp import client as C                                                 # noqa: E402
from openmhp.adapters import Action, BoundDriver, Setting, Signal               # noqa: E402
from openmhp.client import Lab, LocalDevice, RemoteError                        # noqa: E402
from openmhp.driver import (ApprovalRequired, DeviceBusy, DeviceFault, InterlockOpen,  # noqa: E402
                            InvalidValue, LimitViolation, NotLeased, NotSupported)
from openmhp.mcp_bridge import Bridge, StdioLoop, make_mcp_http_server          # noqa: E402
from openmhp.runs import PlanLab, RunLog                                         # noqa: E402


def drv(settings=(), actions=(), signals=(), **kw):
    return BoundDriver(device={"id": "test", "class": "generic"}, signals=signals, settings=settings, actions=actions, **kw)


def expect(code, fn):
    try:
        fn()
    except RemoteError as e:
        assert e.code == code, f"expected {code}, got {e.code}: {e.message}"
        return e
    raise AssertionError(f"expected error {code}, but the call succeeded")


def register(target, driver):
    C._inprocess[target] = (driver, "")


def fails(exc):
    def raiser(*a, **k):
        raise exc
    return raiser


def test_setting_values_are_typed_finite_and_bounded():
    got = []
    d = LocalDevice(drv(settings=[Setting("temp", got.append, limits={"min": 20, "max": 300}),
                                   Setting("mode", got.append, type="string", limits={"enum": ["a", "b"]}),
                                   Setting("on", got.append, type="boolean"),
                                   Setting("count", got.append, type="integer", limits={"min": 0, "max": 10})]))
    for bad in ["500", None, float("nan"), float("inf"), True]:
        expect(InvalidValue.code, lambda v=bad: d.write("temp", v))
    expect(LimitViolation.code, lambda: d.write("temp", 301))
    expect(InvalidValue.code, lambda: d.write("mode", "a\r\nSTOP"))
    expect(LimitViolation.code, lambda: d.write("mode", "c"))
    expect(InvalidValue.code, lambda: d.write("on", 1))
    expect(InvalidValue.code, lambda: d.write("count", 2.5))
    d.write("temp", 150); d.write("on", True); d.write("count", 3)
    assert got == [150, True, 3]


def test_action_params_are_enforced_in_dry_runs_and_runs():
    hits = []
    d = LocalDevice(drv(actions=[
        Action("dose", lambda j, p: hits.append(p), params={"volume": "uL"}, required=["volume"], limits={"volume": [0, 10]}),
        Action("dose_many", lambda j, p: hits.append(p), params={"vols": "uL each"}, limits={"vols": [0, 10]})]))
    expect(LimitViolation.code, lambda: d.invoke("dose", volume=1000))
    expect(LimitViolation.code, lambda: d.invoke("dose", dry_run=True, volume=1000))
    expect(InvalidValue.code, lambda: d.invoke("dose"))
    expect(InvalidValue.code, lambda: d.invoke("dose", volume=5, extra=1))
    expect(LimitViolation.code, lambda: d.invoke("dose_many", vols=[1, 2, 11]))
    d.wait(d.invoke("dose", volume=5))
    assert hits == [{"volume": 5}]
    from openmhp.devices.sim_thermocycler import SimThermocycler
    tc = LocalDevice(SimThermocycler())
    expect(LimitViolation.code, lambda: tc.invoke("run_protocol", dry_run=True, steps=[{"temp": 95}, {"temp": 500}], cycles=1))
    expect(InvalidValue.code, lambda: tc.invoke("run_protocol", dry_run=True, steps=[{"temp": 95}], cycles=True))
    assert tc.invoke("run_protocol", dry_run=True, steps=[{"temp": 95, "hold_s": 1}], cycles=2)["state"] == "dryRun"


def test_watchdog_stops_a_silent_lease_holder():
    stops = []
    w = drv(settings=[Setting("x", lambda v: None, limits={"min": 0, "max": 1})], safety={"watchdog_s": 0.1},
            estop=lambda: stops.append("stop"))
    w.rpc("session/acquire", {"ttl": 60}, "owner")            # a raw client that never renews
    time.sleep(0.6)
    assert w.state == "estop" and stops == ["stop"] and w.lease is None
    w2 = drv(settings=[Setting("x", lambda v: None, limits={"min": 0, "max": 1})], safety={"watchdog_s": 0.2},
             estop=lambda: stops.append("stop2"))
    c = LocalDevice(w2)
    c.write("x", 1)                                            # acquires the required lease and keeps a heartbeat
    time.sleep(0.8)
    assert w2.state == "idle" and "stop2" not in stops
    c.release()
    expect(NotLeased.code, lambda: LocalDevice(w2).call("settings/write", {"name": "x", "value": 1}, _auto_lease=False))
    w.close(); w2.close()


def test_sessions_have_their_own_leases():
    v = []
    d = drv(settings=[Setting("x", v.append, limits={"min": 0, "max": 10})])
    a, b = LocalDevice(d), LocalDevice(d)
    assert a.session != b.session
    a.acquire(ttl=0.3)
    expect(NotLeased.code, lambda: b.write("x", 1))
    time.sleep(0.7)                                            # the heartbeat keeps a's lease past its ttl
    expect(NotLeased.code, lambda: b.write("x", 2))
    a.release()
    b.write("x", 3)
    assert v == [3]
    d.rpc("safety/estop", {}, "someone")
    a.acquire()
    expect(NotLeased.code, lambda: b.reset())                  # recovery belongs to the holder
    a.reset(); a.release()
    lab = Lab()
    assert lab.child().session != lab.session


def test_model_cannot_approve_confirm_gated_operations():
    b = Bridge(home=HOME / "t05")
    ran, asked = [], []
    register("local:probe.t05", drv(actions=[Action("move", lambda j, p: ran.append(1), approval="confirm")]))
    b.lab.targets["test"] = "local:probe.t05"
    b.client_caps, b.send_request = {"elicitation": {}}, lambda m, p: asked.append(p["message"]) or {"action": "decline"}
    expect(ApprovalRequired.code, lambda: b.call_tool("mhp_invoke", {"device": "test", "name": "move", "approved": True, "wait": True}))
    assert asked and "move" in asked[0] and ran == []
    b.send_request = lambda m, p: {"action": "accept", "content": {"confirm": True}}
    b.call_tool("mhp_invoke", {"device": "test", "name": "move", "wait": True})
    assert ran == [1]
    b.send_request = lambda m, p: {"action": "decline"}
    r = b.call_tool("mhp_run", {"script": "lab['test'].call('actions/invoke', {'name': 'move', 'approved': True})"})
    assert not r["ok"] and ran == [1]
    b.client_caps = {}
    e = expect(ApprovalRequired.code, lambda: b.call_tool("mhp_invoke", {"device": "test", "name": "move"}))
    assert "no trusted confirmation channel" in e.message


def test_plan_mode_never_actuates():
    v = []
    d = LocalDevice(drv(settings=[Setting("x", v.append, limits={"min": 0, "max": 10})], actions=[Action("go", lambda j, p: v.append("go"))]))
    lab = Lab()
    lab._devices["test"] = d
    plan = PlanLab(lab)
    pd = plan["test"]
    pd.call("settings/write", {"name": "x", "value": 2})
    pd.call("actions/invoke", {"name": "go"})
    pd.call("safety/reset", {})
    pd.call("jobs/cancel", {"id": "x"})
    pd.write("x", 3); pd.invoke("go")
    assert v == []
    assert [s["kind"] for s in plan.plan] == ["write", "invoke", "rpc", "rpc", "write", "invoke"]


def test_estop_does_not_wait_and_fleet_stop_reaches_every_device():
    entered, release, stopped = threading.Event(), threading.Event(), threading.Event()

    def slow(v):
        entered.set(); release.wait(5)
    d = drv(settings=[Setting("x", slow, limits={"min": 0, "max": 1})], estop=stopped.set)
    t = threading.Thread(target=lambda: d.rpc("settings/write", {"name": "x", "value": 1}, "a")); t.start()
    assert entered.wait(2)
    threading.Thread(target=lambda: d.rpc("safety/estop", {}, "b")).start()
    assert stopped.wait(1.0), "e-stop waited behind a blocked write"
    release.set(); t.join()

    from openmhp.drivers.serial_ascii import SerialAsciiDriver
    gate = threading.Event()

    class Link:
        def __init__(self): self.sent = []
        def write(self, b): self.sent.append(b.decode().strip())
        def readline(self): gate.wait(5); return b"20.0\r\n"
    desc = {"device": {"id": "s", "class": "generic"}, "signals": [{"name": "t", "type": "number"}], "settings": [], "actions": [],
            "safety": {"estop": True}, "serial": {"read": {"t": "IN"}, "estop": ["STOP"]}}
    link = Link()
    sd = type("S", (SerialAsciiDriver,), {"descriptor": desc, "link": link})()
    reader = threading.Thread(target=lambda: sd.rpc("signals/read", {"names": ["t"]}, "a")); reader.start(); time.sleep(0.1)
    t0 = time.monotonic()
    out = sd.rpc("safety/estop", {}, "b")
    assert out["stopped"] and "STOP" in link.sent and time.monotonic() - t0 < 1.5
    gate.set(); reader.join()

    lab, attempts = Lab(), []

    class Stop:
        def __init__(self, n, slow=False): self.n, self.slow = n, slow
        def estop(self, reason):
            attempts.append(self.n)
            if self.n == 1:
                raise OSError("offline")
            if self.slow:
                time.sleep(3)
            return {"state": "estop", "stopped": True}
    lab._devices = {"a": Stop(1), "b": Stop(2), "c": Stop(3, slow=True)}
    t0 = time.monotonic()
    r = lab.estop_all(timeout=1.0)
    assert sorted(attempts) == [1, 2, 3] and time.monotonic() - t0 < 2
    assert r["a"]["ok"] is False and r["b"]["ok"] is True and r["c"]["ok"] is False


def test_busy_is_derived_from_all_active_jobs():
    release = threading.Event()
    d = drv(settings=[Setting("sp", lambda v: None, limits={"min": 0, "max": 1}),
                      Setting("light", lambda v: None, type="boolean", during_job=True)],
            actions=[Action("long", lambda j, p: release.wait(5)), Action("quick", lambda j, p: None, concurrent=True)])
    c = LocalDevice(d)
    j = c.invoke("long")
    c.wait(c.invoke("quick"))
    assert d.state == "busy" and c.status(j)["state"] == "running"
    expect(DeviceBusy.code, lambda: c.invoke("long"))
    expect(DeviceBusy.code, lambda: c.write("sp", 1))
    c.write("light", True)
    release.set()
    assert c.wait(j)["state"] == "done" and d.state == "idle"


def test_uncertain_write_latches_fault_and_reaches_a_safe_state():
    safe = []
    d = drv(settings=[Setting("x", fails(OSError("reply lost")), limits={"min": 0, "max": 1})],
            signals=[Signal("t", read=lambda: 1)], estop=lambda: safe.append("safe"))
    c = LocalDevice(d)
    e = expect(DeviceFault.code, lambda: c.write("x", 1))
    assert e.data == {"outcome": "unknown"} and d.state == "fault" and safe == ["safe"]
    expect(DeviceFault.code, lambda: c.write("x", 0))
    d2 = LocalDevice(drv(settings=[Setting("x", fails(OSError("never")), limits={"min": 0, "max": 1})]))
    expect(LimitViolation.code, lambda: d2.write("x", 5))
    assert d2.driver.state == "idle"                           # validation errors are not faults
    sensor = {"ok": False}

    def read_t():
        if not sensor["ok"]:
            raise OSError("offline")
        return 1
    d3 = LocalDevice(drv(signals=[Signal("t", read=read_t)], settings=[Setting("x", fails(OSError("lost")), limits={"min": 0, "max": 1})]))
    expect(DeviceFault.code, lambda: d3.write("x", 1))
    expect(DeviceFault.code, lambda: d3.reset())               # recovery must be verified
    sensor["ok"] = True
    assert d3.reset()["state"] == "idle"


def test_serial_booleans_fail_closed():
    from openmhp.drivers.serial_ascii import SerialAsciiDriver
    reply = {"text": "1"}

    class Link:
        def write(self, b): pass
        def readline(self): return (reply["text"] + "\r\n").encode()
    desc = {"device": {"id": "s", "class": "generic"}, "signals": [{"name": "lid", "type": "boolean"}], "settings": [],
            "actions": [{"name": "go", "interlocks": ["lid"]}], "safety": {"estop": True},
            "serial": {"read": {"lid": "LID?"}, "actions": {"go": ["GO"]}, "estop": ["STOP"]}}
    sd = type("S", (SerialAsciiDriver,), {"descriptor": desc, "link": Link()})()
    for text in ["not closed", "ERROR", "10", ""]:
        try:
            sd._parse("lid", text); raise AssertionError(text)
        except ValueError:
            pass
    assert sd._parse("lid", "CLOSED") is True and sd._parse("lid", "0") is False
    c = LocalDevice(sd)
    reply["text"] = "ERROR"
    expect(InterlockOpen.code, lambda: c.invoke("go"))
    reply["text"] = "1"
    assert c.wait(c.invoke("go"))["state"] == "done"


def test_runs_never_touch_the_protocol_stream():
    b = Bridge(home=HOME / "t11")
    proto = io.StringIO()
    loop = StdioLoop(b, out=proto)
    old = sys.stdout
    r1 = b.runs.start("import time\nfor i in range(20):\n    print('run one', i)\n    time.sleep(0.01)", background=True)
    r2 = b.runs.start("import time\nfor i in range(20):\n    print('run two', i)\n    time.sleep(0.01)", background=True)
    assert (Path(r1["run"]["dir"]) / "meta.json").is_file()   # a background run is recorded before it finishes
    for i in range(20):
        loop.write({"jsonrpc": "2.0", "id": i, "result": {}}); time.sleep(0.005)
    for r in (r1, r2):
        b.runs.runs[r["run"]["id"]].thread.join()
    assert sys.stdout is old
    lines = proto.getvalue().splitlines()
    assert len(lines) == 20 and all(json.loads(line)["jsonrpc"] == "2.0" for line in lines)
    o1 = b.runs.read(r1["run"]["id"], "stdout.txt")["text"]
    o2 = b.runs.read(r2["run"]["id"], "stdout.txt")["text"]
    assert "run one" in o1 and "run two" not in o1 and "run two" in o2 and "jsonrpc" not in o1 + o2


def test_adapter_outcomes_match_the_backend():
    from openmhp.adapters.madsci import madsci_node
    posts = []

    class Http:
        def __init__(self, honours_cancel): self.honours, self.cancelled = honours_cancel, False
        def get(self, p):
            if p == "/info": return {"actions": {"spin": {}}}
            if p in ("/state", "/status"): return {}
            return {"action_id": "a", "status": "cancelled" if (self.cancelled and self.honours) else "running"}
        def post(self, p, body=None):
            posts.append(p)
            if p.endswith("/cancel"):
                self.cancelled = True
            return {"action_id": "a", "status": "running"}
    m = LocalDevice(madsci_node("", device={"id": "m", "class": "generic"}, http=Http(True), poll_s=0.01))
    j = m.invoke("spin"); time.sleep(0.05); m.cancel(j)
    assert m.wait(j, poll=0.02)["state"] == "cancelled" and "/action/a/cancel" in posts
    stubborn = madsci_node("", device={"id": "m2", "class": "generic"}, http=Http(False), poll_s=0.01, cancel_timeout_s=0.2)
    m2 = LocalDevice(stubborn)
    j2 = m2.invoke("spin"); time.sleep(0.05); m2.cancel(j2)
    try:
        m2.wait(j2, poll=0.02); raise AssertionError("expected failure")
    except RemoteError:
        pass
    assert m2.status(j2)["outcome"] == "unknown" and stubborn.state == "fault"

    from openmhp.adapters.pylabrobot import plr_device
    complete = threading.Event()

    class Machine:
        async def work(self):
            await asyncio.sleep(0.3); complete.set()
        async def stop(self): pass
    p = LocalDevice(plr_device(Machine(), device={"id": "plr", "class": "generic"}, actions=["work"], setup=False, action_timeout_s=0.05))
    j3 = p.invoke("work")
    try:
        p.wait(j3, poll=0.01); raise AssertionError("expected failure")
    except RemoteError:
        pass
    assert not complete.wait(0.6), "a timed-out PyLabRobot coroutine kept running"
    p2 = LocalDevice(plr_device(Machine(), device={"id": "plr2", "class": "generic"}, actions=["work"], setup=False))
    expect(NotSupported.code, lambda: p2.cancel(p2.invoke("work")))


def test_operator_actions_wait_for_a_person():
    from openmhp.drivers.manual import ManualDriver

    class Centrifuge(ManualDriver):
        descriptor = {"device": {"id": "cf", "class": "centrifuge"},
                      "signals": [{"name": "actual_speed", "type": "number"}],
                      "settings": [{"name": "speed", "type": "number", "limits": {"min": 100, "max": 15000}}],
                      "actions": [{"name": "spin", "duration": "long"}], "safety": {"estop": False, "watchdog_s": None}}
    c = LocalDevice(Centrifuge())
    r = c.write("speed", 5000)
    assert r["applied"] is False and c.read("actual_speed") is None
    j = c.invoke("spin")
    time.sleep(0.3)
    assert c.status(j)["state"] == "waiting_operator"
    try:
        c.wait(j, poll=0.05, timeout=0.3); raise AssertionError("wait returned before the operator acted")
    except TimeoutError:
        pass
    expect(ApprovalRequired.code, lambda: c.invoke("acknowledge", job=j["id"]))
    c.wait(c.invoke("record", approved=True, signal="actual_speed", value=4980))
    c.wait(c.invoke("acknowledge", approved=True, job=j["id"], done=True))
    assert c.wait(j)["state"] == "done" and c.read("actual_speed") == 4980


def test_ids_cannot_escape_their_roots():
    b = Bridge(home=HOME / "t14")
    outside = HOME / "t14-outside"
    outside.mkdir()
    (outside / "marker.txt").write_text("marker")
    for rid in [str(outside), "../t14-outside", "..", "20260101-000000-abcd/../../t14-outside"]:
        try:
            b.runs.read(rid, "marker.txt"); raise AssertionError(rid)
        except (FileNotFoundError, PermissionError):
            pass
    for bad in ["../x", "/tmp/x", "a/b", "..", "UPPER"]:
        for op in ("new", "write", "validate"):
            try:
                b.lab_op({"op": op, "id": bad, "files": {"DEVICE.md": "x"}}); raise AssertionError((op, bad))
            except ValueError:
                pass
        try:
            b.lab_op({"op": "onboard", "id": bad, "answers": {"make": "x"}}); raise AssertionError(bad)
        except ValueError:
            pass


def test_mcp_http_needs_a_token_and_a_trusted_origin():
    b = Bridge(home=HOME / "t15")
    srv = make_mcp_http_server(b, port=0, token="secret-token", allowed_origins=("https://good.example",))
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}).encode()

    def post(headers):
        req = urllib.request.Request(f"http://127.0.0.1:{port}/mcp", data=body, headers={"Content-Type": "application/json", **headers})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code
    try:
        assert post({}) == 401
        assert post({"Authorization": "Bearer wrong"}) == 401
        assert post({"Authorization": "Bearer secret-token", "Origin": "https://evil.example"}) == 403
        assert post({"Authorization": "Bearer secret-token", "Host": "evil.example"}) == 403
        assert post({"Authorization": "Bearer secret-token"}) == 200
        assert post({"Authorization": "Bearer secret-token", "Origin": "https://good.example"}) == 200
    finally:
        srv.shutdown()
    init = b.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}})["result"]
    assert init["protocolVersion"] == "2025-06-18"


def test_cell_handoffs_are_checked():
    from openmhp.devices.sim_arm import SimArm
    from openmhp.devices.sim_thermocycler import SimThermocycler
    tc, arm = LocalDevice(SimThermocycler()), LocalDevice(SimArm())
    arm.wait(arm.invoke("home"))
    arm.wait(arm.invoke("pick_plate", location="deck_A1"))
    try:
        arm.wait(arm.invoke("place_plate", location="thermocycler")); raise AssertionError("loaded through a closed lid")
    except RemoteError as e:
        assert "lid is closed" in e.message
    from openmhp.fleet import Fleet
    for target in list(C._inprocess):
        C.drop_inprocess(target)
    b = Bridge(fleet=Fleet(HOME / "t16" / "fleet.json"))
    for name in ("thermocycler-01", "arm-01"):
        b.call_tool("mhp_lab", {"op": "add", "target": f"openmhp/devices/{name}"})
    r = b.call_tool("mhp_run", {"recipe": "pcr-with-plate-transfer", "params": {"thermocycler": "thermocycler-99"}, "plan": True})
    assert not r["ok"] and "belongs to thermocycler-01" in r["plan"]["verdict"]


def test_safety_card_reports_only_real_evidence():
    from openmhp.package import load_package
    from openmhp.safety import safety_card
    from openmhp.validate import validate
    bad = drv(settings=[Setting("x", lambda v: None, limits={"max": 1}, approval="forbid")], safety={"watchdog_s": 10}, estop=lambda: None)
    card = safety_card(LocalDevice(bad))
    assert all(p["status"] == "not exercised" for p in card["probes"] if p["kind"] == "write")
    assert not any(p["result"].startswith("refused as expected") for p in card["probes"])
    assert "not exercised: 2" in card["text"] and "not a safety certification" in card["text"]
    good = drv(settings=[Setting("x", lambda v: None, limits={"min": 0, "max": 1})], estop=lambda: None)
    assert [p["status"] for p in safety_card(LocalDevice(good))["probes"]] == ["passed", "passed", "passed"]
    pkg = HOME / "t17pkg"
    pkg.mkdir()
    (pkg / "DEVICE.md").write_text("---\nid: t17\nclass: hotplate\nlocation: here\ntags: [x]\n"
                                   "description: A test hotplate package used to check that the validator catches empty limits and missing stop commands.\n---\n# T17\n")
    (pkg / "descriptor.yaml").write_text("settings:\n  - {name: sp, type: number, limits: {}}\nsafety: {estop: true, watchdog_s: 10}\n"
                                         "serial: {write: {sp: 'SP {value}'}}\n")
    err, _ = validate(load_package(pkg))
    assert any("needs limits" in e for e in err) and any("serial.estop" in e for e in err)


def test_run_log_survives_restarts_and_runs_are_audited():
    home = HOME / "t18"
    log = RunLog(home)
    for i in range(600):
        log.write("tick", i=i)
    log2 = RunLog(home)
    assert log2.seq == 600
    assert [e["seq"] for e in log2.window(10, limit=5)["events"]] == [11, 12, 13, 14, 15]
    assert log2.write("after")["seq"] == 601
    b = Bridge(home=HOME / "t18b")
    v = []
    register("local:probe.t18", drv(settings=[Setting("x", v.append, limits={"min": 0, "max": 9})]))
    b.lab.targets["aud"] = "local:probe.t18"
    r = b.call_tool("mhp_run", {"script": "lab['aud'].write('x', 4)\ntry:\n    lab['aud'].write('x', 99)\nexcept Exception:\n    pass"})
    assert r["ok"] and v == [4]
    events = b.log.since(0, 1000)
    rid = r["run"]["id"]
    assert any(e["kind"] == "write" and e.get("run") == rid and e["value"] == 4 for e in events)
    assert any(e["kind"] == "refused" and e.get("run") == rid and e["code"] == LimitViolation.code for e in events)
    dead = "20260101-000000-dead"
    folder = HOME / "t18b" / "runs" / dead
    folder.mkdir(parents=True)
    (folder / "meta.json").write_text(json.dumps({"id": dead, "name": "x", "state": "running", "started": 1, "finished": None, "pid": 999999}))
    b2 = Bridge(home=HOME / "t18b")
    assert next(m for m in b2.runs.list() if m["id"] == dead)["state"] == "interrupted"


def test_nested_executor_cannot_report_false_unreachable():
    from openmhp.directory import Directory
    di = Directory(ping_timeout=0.05)
    for i in range(128):
        di.add({"id": str(i), "class": "generic"}, "unused", probe=lambda: "idle")
    states = di.refresh(list(di.cards))
    assert sum(s == "unreachable" for s in states.values()) == 0
    di.add({"id": "ghost", "class": "generic"}, "http://127.0.0.1:1")
    assert di.refresh(["ghost"])["ghost"] == "unreachable"
    di._pool.shutdown(wait=False)


def test_remove_and_reload_invalidate_routing_and_drivers():
    from openmhp.fleet import Fleet
    home = HOME / "t20"
    home.mkdir()
    pkg = home / "pkgs" / "ika"
    shutil.copytree("packages/ika-c-mag-hs7", pkg)
    b = Bridge(fleet=Fleet(home / "fleet.json"))
    did = b.call_tool("mhp_lab", {"op": "add", "target": str(pkg), "sim": True})["added"]["id"]
    b.call_tool("mhp_read", {"device": did, "names": ["plate_temperature"]})
    time.sleep(0.02)
    desc = pkg / "descriptor.yaml"
    desc.write_text(desc.read_text().replace("max: 300", "max: 250"))
    b.lab.forget(did)
    try:
        b.lab[did]; raise AssertionError("a changed package was silently reused")
    except Exception as e:
        assert "changed on disk" in str(e)
    assert "reloaded" in b.call_tool("mhp_lab", {"op": "reload", "id": did})
    expect(LimitViolation.code, lambda: b.call_tool("mhp_write", {"device": did, "name": "target_temperature", "value": 260}))
    b.call_tool("mhp_lab", {"op": "remove", "id": did})
    try:
        b.lab[did]; raise AssertionError("removed device still reachable")
    except Exception:
        pass
    b.call_tool("mhp_lab", {"op": "add", "target": "openmhp/devices/thermocycler-01"})
    copy = home / "tc-copy"
    shutil.copytree("openmhp/devices/thermocycler-01", copy)
    try:
        b.call_tool("mhp_lab", {"op": "add", "target": str(copy)}); raise AssertionError("duplicate id accepted")
    except ValueError as e:
        assert "already in the lab" in str(e)


def test_factory_packages_keep_their_capabilities():
    from openmhp.package import load_driver
    pkg = HOME / "t21"
    pkg.mkdir()
    (pkg / "DEVICE.md").write_text("---\nid: fac-01\nclass: liquid_handler\nlocation: bay 1\ntags: [x]\n"
                                   "description: A factory-built test device whose capabilities come from bindings in driver.py.\n---\n# Factory\n")
    (pkg / "descriptor.yaml").write_text("safety: {estop: true, watchdog_s: null}\nactions:\n  - {name: aspirate, limits: {vol: [0, 100]}, notes: from yaml}\n")
    (pkg / "driver.py").write_text("from openmhp.adapters import BoundDriver, Action\n"
                                   "DEVICE = BoundDriver(device={}, actions=[Action('aspirate', lambda j, p: p, params={'vol': 'uL'}), "
                                   "Action('dispense', lambda j, p: p)], estop=lambda: None)\n")
    c = LocalDevice(load_driver(pkg))
    card = c.call("device/describe", {"detail": "card"})
    assert card["id"] == "fac-01" and card["actions"] == ["aspirate", "dispense"]
    expect(LimitViolation.code, lambda: c.invoke("aspirate", vol=500))
    assert c.wait(c.invoke("aspirate", vol=50))["result"] == {"vol": 50}
    (pkg / "descriptor.yaml").write_text("actions:\n  - {name: ghost}\n")
    try:
        load_driver(pkg); raise AssertionError("an unbound capability was accepted")
    except ValueError as e:
        assert "no binding" in str(e)


def test_entry_points_fail_cleanly():
    from openmhp.client import StdioDevice
    t0 = time.monotonic()
    try:
        StdioDevice(f"{sys.executable} -c pass"); raise AssertionError("expected ConnectionError")
    except ConnectionError:
        pass
    assert time.monotonic() - t0 < 10

    from openmhp.recipes import with_params
    env = {"__mhp_params__": {"device": None, "flag": True, "note": "x'); import os #"}}
    exec(with_params("PARAMS = {'device': 'a', 'flag': False}\n"), env)
    assert env["PARAMS"] == env["__mhp_params__"]

    from openmhp import cli
    from openmhp.fleet import Fleet
    assert cli.main(["lab", "add", "packages/ika-c-mag-hs7", "--sim"]) == 0
    assert any(i.endswith("-sim") for i in Fleet().devices)

    b = Bridge(home=HOME / "t22")
    written, reads = [], {"n": 0}

    def flaky():
        reads["n"] += 1
        if reads["n"] > 2:
            raise OSError("sensor offline")
        return 20.0
    register("local:probe.t22", drv(signals=[Signal("temp", read=flaky)], settings=[Setting("sp", written.append, limits={"min": 0, "max": 100})]))
    b.lab.targets["heater"] = "local:probe.t22"
    r = b.call_tool("mhp_run", {"recipe": "timed-hold", "params": {"device": "heater", "setting": "sp", "signal": "temp", "setpoint": 20,
                                                                     "hold_minutes": 1, "log_every_s": 0.01, "safe_setpoint": 5}})
    assert not r["ok"] and written[-1] == 5, (r, written)

    register("local:probe.t22b", drv(signals=[Signal("t", read=lambda: 1)]))
    b.lab.targets["loop"] = "local:probe.t22b"
    t0 = time.monotonic()
    slept = b.call_tool("mhp_run", {"script": "import time\nfor i in range(10000):\n    time.sleep(60)\nprint('slept')", "plan": True})
    assert time.monotonic() - t0 < 5 and slept["plan"]["virtual_seconds"] >= 600000 and slept["ok"]
    endless = b.call_tool("mhp_run", {"script": "while True:\n    lab['loop'].read('t')", "plan": True})
    assert endless["ok"] and "truncated" in endless["plan"]["verdict"]


if __name__ == "__main__":
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn(); print("ok  ", name)
            except Exception as e:                       # noqa: BLE001
                failed += 1
                import traceback
                print("FAIL", name, f"{type(e).__name__}: {e}")
                traceback.print_exc(limit=3)
    print(f"{failed} failed")
    sys.exit(1 if failed else 0)
