"""Behavioral tests for the safety gates and runtime guarantees SPEC.md declares MUST hold: typed and
bounded values, watchdog and lease enforcement, the elicitation trust boundary, plan-mode isolation,
fail-closed state on an uncertain outcome, and the transports around all of it. No hardware; only localhost.

    PYTHONPATH=. python tests/test_safety_gates.py
"""
import asyncio
import csv
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
from openmhp.driver import (ApprovalRequired, DeviceBusy, DeviceFault, Forbidden, InterlockOpen,  # noqa: E402
                            InvalidValue, LimitViolation, NotLeased, NotSupported)
from openmhp.mcp_bridge import TOOLS, Bridge, StdioLoop, make_mcp_http_server   # noqa: E402
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


def test_a_watchdog_can_hand_an_instrument_over_instead_of_stopping_it():
    """`safety.watchdog_s` decided two things at once: that a lease is mandatory, and that silence
    e-stops the instrument. For a cell that electrolyses for hours the stop is itself the damage, so
    authors switched the whole field off -- and lost the mandatory lease and any detection with it.
    `watchdog_action: release` separates them: the silence is still caught and reported, the lease is
    dropped so another controller can take over, and the work keeps running."""
    def cell(safety):
        heard, stopped = [], []
        d = drv(signals=[Signal("current_mA", lambda: -150.0)],
                actions=[Action("electrolyse", lambda job, params: time.sleep(2) or {"coulombs": 12})],
                safety=safety, estop=lambda: stopped.append("opened"))
        d.subscribers.append(lambda m: heard.append(m["params"]) if m["method"].endswith("safety/watchdog") else None)
        return d, heard, stopped

    d, heard, stopped = cell({"estop": True, "watchdog_s": 0.2, "watchdog_action": "release"})
    expect(NotLeased.code, lambda: LocalDevice(d).call("actions/invoke", {"name": "electrolyse"}, _auto_lease=False))
    d.rpc("session/acquire", {"ttl": 60}, "controller")        # a controller that then dies
    jid = d.rpc("actions/invoke", {"name": "electrolyse"}, "controller")["job"]["id"]
    time.sleep(0.7)
    assert d.lease is None, "the dead holder kept the instrument"
    assert d.state == "busy" and not d.jobs[jid].cancel_requested, "the electrolysis was interrupted"
    assert stopped == [] and [(e["action"], e["stopped"], e["activeJobs"]) for e in heard] == [("release", False, [jid])]
    LocalDevice(d).acquire(ttl=60)                             # and another controller can take over
    d.close()

    d, heard, stopped = cell({"estop": True, "watchdog_s": 0.2})               # the default is unchanged
    d.rpc("session/acquire", {"ttl": 60}, "controller")
    time.sleep(0.7)
    assert d.state == "estop" and stopped == ["opened"] and heard[0]["action"] == "estop"
    d.close()

    d, _, stopped = cell({"estop": True, "watchdog_s": 0.2, "watchdog_action": "sit-tight"})
    d.rpc("session/acquire", {"ttl": 60}, "controller")        # an action it does not know fails safe
    time.sleep(0.7)
    assert d.state == "estop" and stopped == ["opened"]
    d.close()

    # A descriptor may not claim a stop the device cannot perform, and may not spell the action wrong.
    from openmhp.package import DevicePackage
    from openmhp.validate import validate

    def errors(safety):
        pkg = DevicePackage(HOME / "nowhere", {"id": "wd-01", "class": "generic", "make": "m", "model": "x"},
                            "", {"device": {"id": "wd-01"}, "signals": [], "settings": [], "actions": [],
                                 "safety": safety})
        return " | ".join(validate(pkg, location="bench 1")[0])

    assert "watchdog_action" in errors({"estop": False, "watchdog_s": 60})
    assert "must be 'estop' or 'release'" in errors({"estop": True, "watchdog_s": 60, "watchdog_action": "ignore"})
    assert "watchdog" not in errors({"estop": False, "watchdog_s": 60, "watchdog_action": "release"})
    assert "watchdog" not in errors({"estop": True, "watchdog_s": 60})

    # The finding itself: no shipped package may leave its controller unwatched unless a person runs it.
    from openmhp.package import load_package
    for d in sorted(Path("supported-devices").iterdir()) + sorted(Path("openmhp/devices").iterdir()):
        if not (d / "DEVICE.md").is_file():
            continue
        saf = load_package(d).descriptor.get("safety") or {}
        operator = saf.get("estop_kind") == "operator"
        assert saf.get("watchdog_s") or operator, f"{d.name} watches nothing and is not operator-run"
        assert not (saf.get("watchdog_s") and operator), f"{d.name} is operator-run but declares a watchdog"


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

    # every device includes the ones a script opened: a run works through its own Lab, with its own
    # session and its own leases, so a stop that walks one connection list spares the instrument the
    # script is driving -- which is the one case it exists for.
    from openmhp.devices.sim_thermocycler import SimThermocycler
    protocol = "lab['%s'].invoke('run_protocol', steps=[{'temp': 95, 'hold_s': 30}], cycles=20)"
    b = Bridge(home=HOME / "t6stop")
    for name in ("bench", "script-side"):
        C._inprocess[f"local:{name}.t6stop"] = (SimThermocycler(), "")
        b.lab.targets[name] = f"local:{name}.t6stop"
    b.call_tool("mhp_read", {"device": "bench", "signals": ["block_temperature"]})     # the bridge opens one
    b.call_tool("mhp_run", {"background": True, "script": protocol % "script-side" + "\nimport time\ntime.sleep(20)"})
    for _ in range(250):
        if b.lab.open_devices().get("script-side") is not None:
            break
        time.sleep(0.02)
    else:
        raise AssertionError("the run never opened its device")
    assert "script-side" not in b.lab.devices                      # and never appears in the bridge's own list
    r = b.call_tool("mhp_estop", {"device": "*", "reason": "smoke from the lid"})
    assert r["bench"]["ok"] and r["script-side"]["ok"], r
    assert [C._inprocess[f"local:{n}.t6stop"][0].state for n in ("bench", "script-side")] == ["estop", "estop"]

    # the run can be over while the protocol it started is not: an in-process driver outlives the lab
    C._inprocess["local:orphan.t6stop"] = (SimThermocycler(), "")
    b2 = Bridge(home=HOME / "t6stop2")
    b2.lab.targets["orphan"] = "local:orphan.t6stop"
    b2.call_tool("mhp_run", {"script": protocol % "orphan"})
    orphan = C._inprocess["local:orphan.t6stop"][0]
    assert orphan.state == "busy" and not b2.lab.devices           # nobody holds it open any more
    assert b2.call_tool("mhp_estop", {"device": "*"})["orphan"]["ok"]
    assert orphan.state == "estop"
    for target in ("local:bench.t6stop", "local:script-side.t6stop", "local:orphan.t6stop"):
        C.drop_inprocess(target)                                   # leave no stopped twin behind


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


def test_a_stop_is_read_and_answered_while_a_slow_request_is_in_flight():
    """`safety/estop` MUST NOT wait behind ordinary requests. Over HTTP each request arrives on its
    own thread, but stdio read one line, handled it, then read the next, so a stop sent while a
    three-second read was in flight was not even read until the read had finished. It is answered
    now while the read is still blocked, and ordinary requests still run in the order they arrive:
    one instrument, one queue."""
    import queue as q

    from openmhp.transport import serve_stdio
    entered, release = threading.Event(), threading.Event()

    def slow():
        entered.set()
        release.wait(5)
        return 20.0

    d = drv(signals=[Signal("t", slow)], settings=[Setting("x", lambda v: None, limits={"min": 0, "max": 9})],
            estop=lambda: None)
    answers, events, inbox = [], [], q.Queue()

    class Pipe:                                        # stdin as a pipe: lines arrive when pushed
        def __iter__(self):
            return iter(self.q.get, None)
        q = inbox

    class Sink:                                        # stdout, one complete message per write
        def write(self, text):
            if text.strip():
                m = json.loads(text)
                (answers if m.get("id") is not None else events).append(m)

        def flush(self):
            pass

    threading.Thread(target=lambda: serve_stdio(d, stdin=Pipe(), stdout=Sink()), daemon=True).start()

    def push(mid, method, params=None):
        inbox.put(json.dumps({"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}}) + "\n")

    def wait_for(mid, within=3.0):
        deadline = time.monotonic() + within
        while time.monotonic() < deadline:
            if any(a.get("id") == mid for a in list(answers)):
                return time.monotonic()
            time.sleep(0.01)
        raise AssertionError(f"no answer to {mid} within {within}s; got {[a.get('id') for a in answers]}")

    push(1, "signals/read", {"names": ["t"]})
    assert entered.wait(2), "the slow read never reached the device"
    t0 = time.monotonic()
    push(2, "safety/estop", {"reason": "smoke"})
    push(3, "settings/write", {"name": "x", "value": 1})
    push(4, "settings/write", {"name": "x", "value": 2})
    assert wait_for(2) - t0 < 1.0, "the stop queued behind the read"
    assert [a["id"] for a in answers] == [2] and d.state == "estop"      # answered, and the read still blocked
    assert any(e.get("method") == "notifications/safety/estop" for e in events), events
    release.set()
    wait_for(4)
    assert [a["id"] for a in answers] == [2, 1, 3, 4]                    # the stop jumped; the rest kept order
    inbox.put(None)


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


def test_a_script_is_handed_the_gated_surface_and_nothing_else():
    """A run script is code the host executes, so it sits inside the trust boundary while the model that wrote
    it does not. The lab it gets offers the audited device API only: the in-process driver, the untracked
    transport call and a Lab with hooks of its own are not reachable, every attempt is refused in terms that
    name the right call, and the attempt itself lands in the run log."""
    b = Bridge(home=HOME / "t31")
    moved = []
    register("local:probe.t31", drv(settings=[Setting("temp", moved.append, limits={"min": 4, "max": 105})],
                                   actions=[Action("go", lambda j, p: moved.append("go"), approval="confirm")]))
    b.lab.targets["thermo"] = "local:probe.t31"
    for script, reached in (("lab['thermo'].driver.on_write('temp', 900)", "driver"),
                            ("lab['thermo']._raw_call('settings/write', {'name': 'temp', 'value': 900})", "_raw_call"),
                            ("lab.child(approver=None)['thermo'].call('actions/invoke', "
                             "{'name': 'go', 'approved': True})", "child")):
        r = b.call_tool("mhp_run", {"script": script})
        assert not r["ok"] and reached in r["error"], (reached, r)
    assert moved == []                                      # 900 degC never reached the hook, 'go' never ran
    assert [e["attribute"] for e in b.log.recent if e["kind"] == "script/blocked"] == ["driver", "_raw_call", "child"]

    assert b.call_tool("mhp_run", {"script": "lab['thermo'].write('temp', 50)"})["ok"]      # the gated path still works
    r = b.call_tool("mhp_run", {"script": "with lab['thermo'] as d:\n    d.write('temp', 900)"})
    assert not r["ok"] and "above max 105" in json.dumps(r["error"])
    assert moved == [50]
    audited = [(e["kind"], e.get("name"), e.get("value")) for e in b.log.recent if e["kind"] in ("write", "refused")]
    assert ("write", "temp", 50) in audited and ("refused", "temp", 900) in audited
    assert all(e.get("run") for e in b.log.recent if e["kind"] in ("write", "refused"))     # audited to the run

    off = Bridge(home=HOME / "t31b", scripts=False)         # a host that executes no model-authored code at all
    assert [t["name"] for t in off.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]] \
        == [t["name"] for t in TOOLS if t["name"] != "mhp_run"]
    e = expect(Forbidden.code, lambda: off.call_tool("mhp_run", {"script": "print(1)"}))
    assert "no scripts" in e.message and "mhp_write" in e.message


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


def test_a_device_takes_approved_only_from_a_channel_it_can_place():
    """`approved: true` is the host's statement that a person confirmed this exact request (7.2), so a
    device may take it only from a caller its transport can place: the machine it runs on, or one
    holding its token. A stranger reaching an open port is neither, and the flag is dropped before the
    gates ever see it. An address another machine can reach is not served without a token unless the
    operator asks for that."""
    import socket

    from openmhp.transport import device_token, dispatch, is_loopback, serve_http
    opened = []

    def device():
        return drv(actions=[Action("open_lid", lambda j, p: opened.append(1), approval="confirm")], estop=lambda: None)

    def free_port():                      # a free port, not a fixed one: CI runners are shared
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    def post(port, params, token=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(f"http://127.0.0.1:{port}/rpc", headers=headers,
                                     data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "actions/invoke",
                                                      "params": params}).encode())
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())

    local, locked = free_port(), free_port()
    for port, token in ((local, None), (locked, "secret-device-token")):
        threading.Thread(target=serve_http, args=(device(),),
                         kwargs={"host": "127.0.0.1", "port": port, "token": token}, daemon=True).start()
    for port in (local, locked):
        for _ in range(200):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/mhp.json", timeout=2).read()
                break
            except OSError:
                time.sleep(0.02)
        else:
            raise AssertionError(f"the device on {port} never answered")

    assert "error" in post(local, {"name": "open_lid"})                        # loopback, unconfirmed: refused
    assert "result" in post(local, {"name": "open_lid", "approved": True})     # the person at this terminal
    assert len(opened) == 1

    for guess in (None, "guessed-token"):                                      # behind a token, the flag is
        try:                                                                   # worth no more than the token
            post(locked, {"name": "open_lid", "approved": True}, token=guess)
            raise AssertionError("an unauthenticated request was served")
        except urllib.error.HTTPError as e:
            assert e.code == 401 and b"Bearer" in e.read()
    assert "result" in post(locked, {"name": "open_lid", "approved": True}, token="secret-device-token")
    assert len(opened) == 2
    nameplate = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{locked}/mhp.json", timeout=5).read())
    assert nameplate["device"]["id"]                   # discovery stays open, so `mhp lab scan` still works

    r = dispatch(device(), {"jsonrpc": "2.0", "id": 1, "method": "actions/invoke",
                            "params": {"name": "open_lid", "approved": True}}, "10.0.0.9", trusted=False)
    assert r["error"]["code"] == ApprovalRequired.code and r["error"]["data"]["ignoredApproved"] is True
    assert "cannot assert it" in r["error"]["message"] and len(opened) == 2

    dev = C.connect(f"http://127.0.0.1:{locked}", token="secret-device-token")      # the SDK carries the token
    assert dev.call("actions/invoke", {"name": "open_lid", "approved": True}) is not None
    e = expect(Forbidden.code, lambda: C.connect(f"http://127.0.0.1:{locked}", token="").call(
        "actions/invoke", {"name": "open_lid"}))
    assert "OPENMHP_DEVICE_TOKEN" in e.message                                      # and says what is missing

    assert [is_loopback(a) for a in ("127.0.0.1", "::1", "localhost", "0.0.0.0", "10.0.0.9")] \
        == [True, True, True, False, False]
    assert device_token() is None                      # a client never invents a secret of its own


def test_a_port_in_use_is_refused_not_shared():
    """HTTPServer sets SO_REUSEADDR, which on Windows let a second server bind a port another one was listening
    on. Clients could then reach either server, so an agent could command a different device than the one it
    addressed. A second device server or MCP endpoint on a busy port must fail on every OS."""
    import socket
    from openmhp import discovery
    from openmhp.package import load_driver
    from openmhp.transport import serve_http
    b = Bridge(home=HOME / "t-port")
    first = make_mcp_http_server(b, port=0, token="t")
    try:
        make_mcp_http_server(b, port=first.server_address[1], token="t")
        raise AssertionError("a second MCP endpoint bound a port in use")
    except OSError:
        pass
    finally:
        first.server_close()

    real_advertise, discovery.advertise = discovery.advertise, lambda *a, **k: False     # no LAN announcements
    try:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        threading.Thread(target=serve_http, args=(load_driver("openmhp/devices/arm-01"), "127.0.0.1", port),
                         daemon=True).start()
        deadline = time.time() + 10
        while True:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/mhp.json", timeout=1).close()
                break
            except OSError:
                if time.time() > deadline:
                    raise
                time.sleep(0.05)
        refused = []

        def second():
            try:
                serve_http(load_driver("openmhp/devices/arm-01"), "127.0.0.1", port)
            except OSError as e:
                refused.append(e)
        t = threading.Thread(target=second, daemon=True)
        t.start()
        t.join(10)
        assert refused and not t.is_alive(), "a second device server bound a port in use"
    finally:
        discovery.advertise = real_advertise


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


def test_pid_probe_never_signals_the_process():
    """A restarting bridge asks whether the process behind each unfinished run is still alive. os.kill(pid, 0)
    only probes on POSIX; on Windows signal 0 is CTRL_C_EVENT and the call raised, so a bridge killed during a
    run could not start again."""
    import subprocess
    from openmhp.runs import _pid_alive
    quiet = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], **quiet)
    try:
        assert _pid_alive(child.pid) is True
    finally:
        child.kill()
        child.wait()
    assert _pid_alive(child.pid) is False                    # gone, and no exception
    assert _pid_alive(None) is False


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
    shutil.copytree("supported-devices/ika-c-mag-hs7", pkg)
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
    e = expect(ApprovalRequired.code, lambda: b.call_tool("mhp_lab", {"op": "reload", "id": did}))
    assert "mhp lab accept" in e.message                     # no elicitation: the owner has their own channel
    asked = []
    b.client_caps = {"elicitation": {}}
    b.send_request = lambda m, p: asked.append(p["message"]) or {"action": "accept", "content": {"confirm": True}}
    assert "reloaded" in b.call_tool("mhp_lab", {"op": "reload", "id": did})
    assert '"max": 300} -> {"min": 20, "max": 250}' in asked[0]
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


def test_an_agent_cannot_raise_the_limit_it_is_refused_by():
    """A device package IS what the runtime enforces, so an agent that could write one and put it into service
    would be setting its own limits. The configuration a person accepted is pinned, every route to changing it
    goes through them with the bound that would move, and the log says which one did."""
    from openmhp.fleet import Fleet
    home = HOME / "t30"
    (home / "devices").mkdir(parents=True)
    pkg = home / "devices" / "thermocycler-01"               # a package id under ~/.openmhp/devices, as op='write' addresses it
    shutil.copytree("openmhp/devices/thermocycler-01", pkg)
    desc = pkg / "descriptor.yaml"
    asked, answer = [], {"action": "decline"}
    b = Bridge(fleet=Fleet(home / "fleet.json"))
    b.client_caps = {"elicitation": {}}
    b.send_request = lambda m, p: asked.append(p["message"]) or answer
    did = b.call_tool("mhp_lab", {"op": "add", "target": str(pkg), "location": "bench 1"})["added"]["id"]
    hot = {"device": did, "name": "target_temperature", "value": 300}
    expect(LimitViolation.code, lambda: b.call_tool("mhp_write", hot))

    raised = desc.read_text(encoding="utf-8").replace("limits: {min: 4, max: 105}", "limits: {min: 4, max: 400}")
    r = b.call_tool("mhp_lab", {"op": "write", "id": "thermocycler-01", "files": {"descriptor.yaml": raised}})
    assert r["in_operation"] == did                          # writing files is allowed, and says what it does not do
    assert any("settings.target_temperature.limits" in c and "105} -> " in c for c in r["changes"])
    expect(LimitViolation.code, lambda: b.call_tool("mhp_write", hot))     # the device enforces what was accepted

    e = expect(ApprovalRequired.code, lambda: b.call_tool("mhp_lab", {"op": "reload", "id": did}))
    assert "not accepted" in e.message and "105} -> " in asked[-1]         # the person saw the bound, and said no
    expect(LimitViolation.code, lambda: b.call_tool("mhp_write", hot))

    b.client_caps = {}                                                     # no trusted channel: nothing moves at all
    e = expect(ApprovalRequired.code, lambda: b.call_tool("mhp_lab", {"op": "reload", "id": did}))
    assert "mhp lab accept thermocycler-01" in e.message
    expect(LimitViolation.code, lambda: b.call_tool("mhp_write", hot))

    answer, b.client_caps = {"action": "accept", "content": {"confirm": True}}, {"elicitation": {}}
    b.call_tool("mhp_lab", {"op": "reload", "id": did})                    # the owner accepts it, once, seeing the diff
    assert b.call_tool("mhp_write", hot)["ok"]
    assert b.call_tool("mhp_lab", {"op": "list"})["devices"][0]["location"] == "bench 1"   # the fleet record survives a reload

    desc.write_text(desc.read_text(encoding="utf-8").replace("max: 400", "max: 900"), encoding="utf-8")
    b2 = Bridge(fleet=Fleet(home / "fleet.json"))             # a restart used to load whatever was on disk by then
    try:
        b2.lab[did]
        raise AssertionError("a configuration nobody accepted was enforced")
    except Exception as e:                                    # noqa: BLE001
        assert "accepted it" in str(e)
    assert b2.call_tool("mhp_lab", {"op": "status"})["configuration_changed"] == [did]

    b2.call_tool("mhp_lab", {"op": "remove", "id": did})      # removing a device does not forget what it was accepted with
    e = expect(ApprovalRequired.code, lambda: b2.call_tool("mhp_lab", {"op": "add", "target": str(pkg)}))
    assert "900" in e.message
    assert b2.call_tool("mhp_lab", {"op": "list"})["devices"] == []        # a refused add leaves the lab as it was

    kinds = [ev["kind"] for ev in b.log.recent]
    assert "lab/write" in kinds and "lab/reload" in kinds
    assert [ev["answer"] for ev in b.log.recent if ev["kind"] == "confirm"] == ["decline", "accept"]
    assert all(ev.get("changes") for ev in b.log.recent if ev["kind"] in ("lab/write", "lab/reload", "confirm"))


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
    assert cli.main(["lab", "add", "supported-devices/ika-c-mag-hs7", "--sim"]) == 0
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


def test_the_cli_can_still_reach_a_device():
    """SPEC 10.2 is a control surface, not a convenience: `mhp <target> read|write|invoke|estop`
    is what a person at the bench and an agent in a Bash tool both use. A second,
    function-level `from .client import connect` inside main() made the name local to the whole
    function, so every client verb raised UnboundLocalError before it reached a device."""
    from openmhp import cli
    seen = []
    register("local:probe.cli", drv(signals=[Signal("t", lambda: 21.5)],
                                    settings=[Setting("sp", seen.append, limits={"min": 0, "max": 100})],
                                    estop=lambda: seen.append("stop")))
    printed, out = io.StringIO(), sys.stdout
    sys.stdout = printed
    try:
        for verb in (["read", "t"], ["write", "sp", "40"], ["limits"], ["describe", "card"], ["estop", "by hand"]):
            assert cli.main(["local:probe.cli", *verb]) == 0, verb
        assert cli.main(["conformance", "pkg:openmhp/devices/arm-01"]) == 0    # the verb that shadowed it
    finally:
        sys.stdout = out
    assert seen == [40, "stop"], seen
    assert "21.5" in printed.getvalue(), printed.getvalue()[:300]


ECHO_DEVICE = """\
import json, sys
for line in sys.stdin.buffer:                 # a stdio device that answers every request with its own params
    msg = json.loads(line)
    out = {"jsonrpc": "2.0", "id": msg["id"], "result": {"echo": msg.get("params")}}
    sys.stdout.buffer.write((json.dumps(out, ensure_ascii=False) + "\\n").encode("utf-8"))
    sys.stdout.buffer.flush()
"""


def test_stdio_commands_keep_windows_paths():
    """`stdio:` commands follow the OS's own rules: shlex on POSIX, CreateProcess on Windows. POSIX shlex turned
    C:\\...\\python.exe into C:...python.exe, so no stdio device could start from a Windows path."""
    from openmhp.client import StdioDevice
    folder = HOME / "stdio device"                       # a space in the path, and backslashes on Windows
    folder.mkdir(exist_ok=True)
    (folder / "echo.py").write_text(ECHO_DEVICE, encoding="utf-8")
    dev = StdioDevice(f'{sys.executable} "{folder / "echo.py"}"')
    try:
        assert dev.call("ping", {"n": 1})["echo"] == {"n": 1}
    finally:
        dev.proc.stdin.close()
        dev.proc.wait(10)


def test_stdio_transports_carry_utf8():
    """MHP and MCP over stdio are UTF-8 on every OS. A pipe otherwise uses the locale's encoding, which on Windows
    is the ANSI code page: the client read a device's 'α' as 'Î±', and the device server and the MCP bridge did
    the same to what their clients sent."""
    import subprocess
    from openmhp.client import StdioDevice
    text = "1 µL at 40 °C, α-pinene"
    echo = HOME / "stdio device" / "echo.py"
    echo.parent.mkdir(exist_ok=True)
    echo.write_text(ECHO_DEVICE, encoding="utf-8")
    dev = StdioDevice(f'{sys.executable} "{echo}"')
    try:
        assert dev.call("ping", {"note": text})["echo"] == {"note": text}       # the device answers in raw UTF-8
    finally:
        dev.proc.stdin.close()
        dev.proc.wait(10)

    def ask(args, request):
        """Send one request as raw UTF-8 to a stdio server and return its answer."""
        env = {**os.environ, "OPENMHP_HOME": str(HOME / "t-utf8")}
        p = subprocess.Popen([sys.executable, *args], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, env=env)
        killer = threading.Timer(60, p.kill)
        killer.start()
        try:
            p.stdin.write((json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8"))
            p.stdin.flush()
            for line in p.stdout:
                msg = json.loads(line)
                if msg.get("id") == request["id"]:
                    return msg
            raise AssertionError(f"{args}: no answer")
        finally:
            killer.cancel()
            p.stdin.close()                                   # end of input: both servers exit
            try:
                p.wait(20)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()

    unknown = ask(["-m", "openmhp.cli", "serve", "openmhp/devices/arm-01"],
                  {"jsonrpc": "2.0", "id": 1, "method": "signals/read", "params": {"names": [text]}})
    assert text in unknown["error"]["message"], unknown              # the device server echoes the name it got
    ran = ask(["-m", "openmhp.mcp_bridge"], {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                              "params": {"name": "mhp_run", "arguments": {"script": f"print({text!r})"}}})
    assert text in json.loads(ran["result"]["content"][0]["text"])["stdout"], ran


def test_nested_parameter_bounds_come_from_the_descriptor_not_the_driver():
    """A dangerous value inside a structured parameter (a 200 C step in an otherwise valid
    program) must be refused by the declared shape alone. Before shapes were declarable, the
    only way to catch this was hand-written validate_params in every driver, and `limits`
    could not express it because it keys on the top-level parameter name."""
    from openmhp.driver import Driver, InvalidValue, LimitViolation
    from openmhp.client import LocalDevice

    class Plain(Driver):
        """No validate_params, deliberately: the descriptor is doing all the work."""
        descriptor = {
            "device": {"id": "shape-01", "class": "generic"},
            "actions": [{
                "name": "run", "duration": "short",
                "params": {
                    "steps": {"type": "array", "items": {
                        "type": "object", "required": ["temp"],
                        "properties": {"temp": {"type": "number", "unit": "Cel",
                                                "limits": {"min": 4, "max": 105}},
                                       "hold_s": {"type": "number", "unit": "s"}}}},
                },
                "required": ["steps"],
            }],
        }
        def on_read(self, name): return 0
        def on_write(self, name, value): pass
        def on_invoke(self, job): return {"ok": True}

    d = LocalDevice(Plain())
    assert d.invoke("run", dry_run=True, steps=[{"temp": 95, "hold_s": 30}])["state"] == "dryRun"
    expect(LimitViolation.code, lambda: d.invoke("run", dry_run=True, steps=[{"temp": 95}, {"temp": 200}]))
    expect(InvalidValue.code,   lambda: d.invoke("run", dry_run=True, steps=[{"hold_s": 5}]))
    expect(InvalidValue.code,   lambda: d.invoke("run", dry_run=True, steps=[{"temp": 95, "oops": 1}]))
    expect(InvalidValue.code,   lambda: d.invoke("run", dry_run=True, steps=[{"temp": "hot"}]))


def test_a_result_too_big_for_the_log_can_still_be_fetched():
    """A bulky result is replaced in the log by a placeholder, and the placeholder said "read the
    job result" while the job record on disk said "see the run that produced it" -- which is not a
    place: a direct invoke has no run, and nothing kept the data. The placeholder now names the
    call that returns it, and the result lives in a file beside the record with the same lifetime,
    so it survives a restart and is deleted with it."""
    from openmhp.mcp_bridge import _cap

    trace = [[i * 0.01, i * 1.5] for i in range(6000)]              # a chromatogram, ~110 KB
    def gc(did="gc-9", **kw):
        return BoundDriver(device={"id": did, "class": "gc"}, safety={"estop": False, "watchdog_s": None},
                           actions=[Action("inject", lambda job, params: {"peaks": 3, "trace": trace}),
                                    Action("small", lambda job, params: {"peaks": 3})], **kw)

    def settled(did, jid):
        """jobs/status reports done as soon as the state changes; the record lands just after."""
        f = HOME / "jobs" / did / f"{jid}.json"
        for _ in range(200):
            try:
                rec = json.loads(f.read_text(encoding="utf-8"))
                if rec.get("state") in ("done", "failed", "cancelled"):
                    return rec
            except (OSError, ValueError):
                pass
            time.sleep(0.02)
        raise AssertionError(f"no settled record for {jid}")

    d = gc()
    dev = LocalDevice(d)
    job = dev.wait(dev.invoke("inject"))
    assert len(job["result"]["trace"]) == 6000                      # the device returns it whole

    logged = _cap(job["result"], job["id"])
    assert f"mhp_job op='status' id='{job['id']}'" in logged["trace"], logged
    assert logged["peaks"] == 3
    assert f"id='{job['id']}'" in _cap(trace, job["id"]), "a bare list used to become a truncated repr"

    rec = settled("gc-9", job["id"])
    assert rec["result"]["saved"] == f"results/{job['id']}.json" and rec["result"]["bytes"] > 100_000, rec
    again = LocalDevice(gc()).call("jobs/status", {"id": job["id"]})["job"]     # a fresh process
    assert len(again["result"]["trace"]) == 6000, "the placeholder did not resolve after a restart"

    gone = HOME / "jobs" / "gc-9" / rec["result"]["saved"]          # and when the file is not there
    gone.unlink()
    said = LocalDevice(gc()).call("jobs/status", {"id": job["id"]})["job"]["result"]
    assert said["saved"] is None and "is gone" in said["note"], said

    big = gc("gc-big")                                              # too big even for a file beside it
    big.RESULT_FILE_CAP = 1000
    j2 = LocalDevice(big).wait(LocalDevice(big).invoke("inject"))
    r2 = settled("gc-big", j2["id"])["result"]
    assert r2["saved"] is None and "run folder" in r2["note"] and r2["bytes"] > 100_000, r2
    assert not (HOME / "jobs" / "gc-big" / "results").exists()      # no pointer, so no orphan either

    small = gc("gc-small")                                          # a small result stays inline
    js = LocalDevice(small).wait(LocalDevice(small).invoke("small"))
    assert settled("gc-small", js["id"])["result"] == {"peaks": 3}

    ev = gc("gc-evict")                                             # and one lifetime, not two
    ev.JOB_HISTORY = 2
    c = LocalDevice(ev)
    ids = [settled("gc-evict", c.wait(c.invoke("inject"))["id"])["id"] for _ in range(4)]
    folder = HOME / "jobs" / "gc-evict"
    assert len(list(folder.glob("job_*.json"))) == 2
    assert sorted(p.stem for p in (folder / "results").iterdir()) == sorted(ids[-2:]), ids

    # the inconsistency: mhp_invoke with wait=true logged the result uncut
    b = Bridge(home=HOME / "t9b")
    register("local:probe.gc9", gc("gc-bridge"))
    b.lab.targets["gc"] = "local:probe.gc9"
    b.call_tool("mhp_invoke", {"device": "gc", "name": "inject", "wait": True})
    line = next(e for e in reversed(b.log.since(0, 200)) if e["kind"] == "job")
    assert "mhp_job op='status'" in line["result"]["trace"], line


def test_a_prose_parameter_shape_still_loads_and_is_simply_unchecked():
    """The legacy form stays valid so existing packages keep working; it just buys nothing."""
    from openmhp.driver import Driver
    from openmhp.client import LocalDevice

    class Prose(Driver):
        descriptor = {
            "device": {"id": "prose-01", "class": "generic"},
            "actions": [{"name": "run", "duration": "short",
                         "params": {"steps": "array of {temp: degC 4..105}"},
                         "required": ["steps"]}],
        }
        def on_read(self, name): return 0
        def on_write(self, name, value): pass
        def on_invoke(self, job): return {"ok": True}

    d = LocalDevice(Prose())
    # 200 C passes, because prose is documentation and not a contract
    assert d.invoke("run", dry_run=True, steps=[{"temp": 200}])["state"] == "dryRun"


def test_an_instrument_records_what_was_done_to_it_whoever_asked():
    """Only the MCP bridge kept a run log, and the client's audit hook does nothing without an
    observer, which only the bridge passes. So the same write left a full record through one
    control surface and no record at all through the other two, or through a plain HTTP
    request. The instrument now keeps its own, beside its job records."""
    import socket

    from openmhp.transport import serve_http

    def oven(did, **kw):
        return BoundDriver(device={"id": did, "class": "hotplate"},
                           signals=[Signal("temperature", lambda: 22.0)],
                           settings=[Setting("target", lambda v: None, limits={"min": 4, "max": 105})],
                           estop=lambda: None, **kw)

    def record(did):
        return RunLog(HOME, f"records/{did}").window(0, limit=50)["events"]

    # 1. the SDK, with no observer of any kind
    sdk = LocalDevice(oven("sdk-01"))
    sdk.read("temperature")                                    # reads stay out: they are the caller's
    sdk.write("target", 80)
    expect(LimitViolation.code, lambda: sdk.write("target", 300))
    sdk.estop("smoke")
    rows = record("sdk-01")
    assert [r["kind"] for r in rows] == ["write", "refused", "estop"], rows
    assert rows[0]["value"] == 80 and rows[0]["by"] == sdk.session and rows[0]["device"] == "sdk-01"
    assert rows[1]["op"] == "write" and rows[1]["code"] == LimitViolation.code
    assert rows[2]["reason"] == "smoke"
    assert not any(r["kind"] == "read" for r in rows)

    # 2. a plain HTTP request, no SDK at all
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    threading.Thread(target=lambda: serve_http(oven("http-01"), port=port), daemon=True).start()
    for _ in range(50):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/mhp.json", timeout=1).read()
            break
        except OSError:
            time.sleep(0.1)

    def post(method, params):
        req = urllib.request.Request(f"http://127.0.0.1:{port}/rpc", method="POST",
                                     data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                                                      "params": params}).encode(),
                                     headers={"Content-Type": "application/json", "X-MHP-Client": "curl"})
        return json.loads(urllib.request.urlopen(req, timeout=5).read())

    post("signals/read", {"names": ["temperature"]})
    post("settings/write", {"name": "target", "value": 60})
    assert "error" in post("settings/write", {"name": "target", "value": 500})
    rows = record("http-01")
    assert [(r["kind"], r["by"]) for r in rows] == [("write", "curl"), ("refused", "curl")], rows
    assert rows[0]["value"] == 60

    # 3. a watchdog trip and a latched fault: safety with no request behind it
    wd = oven("wd-01", safety={"estop": True, "watchdog_s": 0.1})
    wd.rpc("session/acquire", {"ttl": 60}, "controller")
    time.sleep(0.6)
    kinds = [(r["kind"], r.get("by")) for r in record("wd-01")]
    assert ("lease", "controller") in kinds and ("estop", "watchdog") in kinds, kinds
    wd.close()

    broken = BoundDriver(device={"id": "fault-01", "class": "generic"}, estop=lambda: None,
                         settings=[Setting("x", fails(OSError("bus error")), limits={"min": 0, "max": 9})])
    expect(DeviceFault.code, lambda: LocalDevice(broken).write("x", 1))
    rows = record("fault-01")
    assert [r["kind"] for r in rows] == ["fault", "refused"], rows      # the fault is latched first
    assert "bus error" in rows[0]["reason"]

    # 4. and the host can read an instrument's record without going near the files
    b = Bridge(home=HOME)
    b.lab.targets["oven"] = "local:probe.rec"
    register("local:probe.rec", oven("bridge-01"))
    b.call_tool("mhp_write", {"device": "oven", "name": "target", "value": 55})
    own = b.call_tool("mhp_data", {"op": "record", "device": "bridge-01"})
    assert [r["kind"] for r in own["events"]] == ["write"] and own["device"] == "bridge-01"
    assert b.call_tool("mhp_data", {"op": "record", "device": "nobody"})["note"].startswith("no record")


def test_every_error_carries_a_device_anchored_timestamp():
    """A client must be able to align a refusal with its own receipt time."""
    import time
    from openmhp.driver import Driver
    from openmhp.transport import dispatch

    class D(Driver):
        descriptor = {"device": {"id": "ts-01", "class": "generic"},
                      "settings": [{"name": "x", "type": "number", "limits": {"min": 0, "max": 1}}]}
        def on_read(self, name): return 0
        def on_write(self, name, value): pass
        def on_invoke(self, job): return {}

    before = time.time()
    r = dispatch(D(), {"jsonrpc": "2.0", "id": 1,
                       "method": "settings/write", "params": {"name": "x", "value": 99}}, "c")
    after = time.time()
    err = r["error"]
    assert err["code"] == -32010, err
    assert "data" in err and err["data"] == {"min": 0, "max": 1}      # structured context
    assert before <= err["ts"] <= after, err                          # device-anchored timing


def _shaped(**kw):
    """A driver whose action parameters are fully declared, so the descriptor does the work."""
    from openmhp.driver import Driver

    class Shaped(Driver):
        descriptor = {"device": {"id": "c2-01", "class": "generic"},
                      "settings": [{"name": "setpoint", "type": "number", "unit": "Cel",
                                    "limits": {"min": 0, "max": 100}, "resolution": 0.1},
                                   {"name": "tag", "type": "string", "nullable": True},
                                   {"name": "mode", "type": "string", "default": "idle"}],
                      "actions": [{"name": "run", "duration": "short", "required": ["steps"],
                                   "params": {"steps": {"type": "array", "items": {
                                       "type": "object", "required": ["temp"],
                                       "properties": {
                                           "temp":   {"type": "number", "unit": "Cel"},
                                           "hold_s": {"type": "number", "unit": "s", "default": 0},
                                           "label":  {"type": "string", "nullable": True}}}}}}]}
        def on_read(self, name): return 0
        def on_write(self, name, value): pass
        def on_invoke(self, job): return {"ok": True}
    return Shaped()


def test_a_reading_can_be_cited():
    """An action result is citable by its job id. A reading was citable by nothing: signals/read
    returned {values, ts}, pushed updates carried no id either, and the sequence number the log
    entry got was thrown away before the agent saw it. So "the block was at 72" had nothing
    behind it."""
    import re as _re

    temp = {"v": 22.0}
    d = drv(signals=[Signal("t", lambda: temp["v"])], settings=[Setting("sp", lambda v: None, limits={"min": 0, "max": 99})])
    dev = LocalDevice(d)

    first = dev.call("signals/read", {"names": ["t"]})
    second = dev.call("signals/read", {"names": ["t"]})
    assert _re.fullmatch(r"read_[0-9a-f]{8}", first["id"]), first
    assert first["id"] != second["id"] and first["values"] == {"t": 22.0}

    pushed = []
    d.subscribers.append(lambda m: pushed.append(m) if m["method"].endswith("signals/update") else None)
    temp["v"] = 72.0
    d.emit_signal("t", temp["v"])
    assert _re.fullmatch(r"read_[0-9a-f]{8}", pushed[0]["params"]["id"]), pushed

    # the host records the id beside the values, polled or pushed
    b = Bridge(home=HOME / "t10")
    register("local:probe.t10", d)
    b.lab.targets["tc"] = "local:probe.t10"
    r = b.call_tool("mhp_read", {"device": "tc", "names": ["t"]})
    line = next(e for e in reversed(b.log.since(0, 200)) if e["kind"] == "read")
    assert r["id"] and line["reading"] == r["id"] and line["values"] == {"t": 72.0}, (r, line)
    d.emit_signal("t", 73.0)
    update = next(u for u in reversed(b.updates("tc")["updates"]) if u.get("signal") == "t")
    assert update["reading"] == pushed[-1]["params"]["id"] and update["value"] == 73.0, update

    # and a run writes it next to every row, so a number in a notebook entry resolves to a record
    out = b.call_tool("mhp_run", {"recipe": "periodic-readings",
                                  "params": {"device": "tc", "signals": ["t"], "every_s": 0.05, "hours": 0.0001}})
    assert out["ok"], out
    rows = list(csv.reader(io.StringIO(b.call_tool("mhp_data", {"op": "read", "run": out["run"]["id"],
                                                                "path": "readings.csv"})["text"])))
    assert rows[0] == ["t_s", "t", "reading"], rows[0]
    assert rows[1:] and all(_re.fullmatch(r"read_[0-9a-f]{8}", row[2]) for row in rows[1:]), rows


def test_a_declared_resolution_refuses_rather_than_silently_rounds():
    from openmhp.driver import InvalidValue
    from openmhp.client import LocalDevice
    d = LocalDevice(_shaped())
    assert d.write("setpoint", 72.1)["value"] == 72.1
    expect(InvalidValue.code, lambda: d.write("setpoint", 72.03))
    try:
        d.write("setpoint", 72.03)
    except Exception as e:
        assert "nearest settable value" in str(e), e


def test_nullable_is_declared_not_assumed():
    from openmhp.driver import InvalidValue
    from openmhp.client import LocalDevice
    d = LocalDevice(_shaped())
    assert d.write("tag", None)["ok"] is True                 # declared nullable
    expect(InvalidValue.code, lambda: d.write("setpoint", None))   # not declared: refused


def test_an_applied_default_is_always_reported_back():
    """The criterion is that a default is never applied in silence. It must survive the
    retry an auto-acquired lease causes, and still be visible on the job afterwards."""
    from openmhp.client import LocalDevice
    d = LocalDevice(_shaped())

    sent = [{"temp": 95}, {"temp": 60, "hold_s": 5}]
    dry = d.invoke("run", dry_run=True, steps=sent)
    assert dry["defaulted"] == {"run.steps[0].hold_s": 0}, dry["defaulted"]
    assert sent == [{"temp": 95}, {"temp": 60, "hold_s": 5}], "the caller's own dict was mutated"

    job = d.invoke("run", steps=[{"temp": 95}])
    assert job["defaulted"] == {"run.steps[0].hold_s": 0}, job["defaulted"]
    assert d.call("jobs/status", {"id": job["id"]})["job"]["defaulted"] == {"run.steps[0].hold_s": 0}

    assert d.invoke("run", dry_run=True, steps=[{"temp": 95, "hold_s": 3}])["defaulted"] is None
    assert d.write("mode")["defaulted"] == {"mode": "idle"}   # a setting may default too


def test_a_declared_result_contract_is_reported_not_enforced():
    """`returns` is optional. When declared, a result that breaks it is reported on the job
    rather than raised: the physical work already happened, so failing the job would
    misreport what the instrument did."""
    from openmhp.driver import Driver
    from openmhp.client import LocalDevice

    class Honest(Driver):
        descriptor = {"device": {"id": "r-01", "class": "generic"},
                      "actions": [{"name": "good", "duration": "short",
                                   "returns": {"type": "object", "required": ["n"],
                                               "properties": {"n": {"type": "integer"}}}},
                                  {"name": "bad", "duration": "short",
                                   "returns": {"type": "object", "required": ["n"],
                                               "properties": {"n": {"type": "integer"}}}},
                                  {"name": "undeclared", "duration": "short"}]}
        def on_read(self, name): return 0
        def on_write(self, name, value): pass
        def on_invoke(self, job):
            return {"n": 1} if job.action == "good" else {"n": "not an integer"} if job.action == "bad" else {"anything": [1, 2]}

    d = LocalDevice(Honest())
    assert d.wait(d.invoke("good"))["resultMismatch"] is None
    bad = d.wait(d.invoke("bad"))
    assert bad["state"] == "done", "a contract mismatch must not fail the job"
    assert "expected integer" in (bad["resultMismatch"] or ""), bad["resultMismatch"]
    assert d.wait(d.invoke("undeclared"))["resultMismatch"] is None   # nothing declared, nothing checked


def test_a_twin_can_be_driven_into_failure_and_real_hardware_cannot():
    from openmhp.driver import NotSupported
    from openmhp.package import load_driver
    from openmhp.client import LocalDevice, RemoteError

    twin = LocalDevice(load_driver("openmhp/devices/thermocycler-01", sim=True))
    real = LocalDevice(load_driver("openmhp/devices/thermocycler-01"))

    expect(NotSupported.code, lambda: real.call("sim/fault", {"on": "invoke", "mode": "raise"}))

    # a refusal happens before any job exists
    twin.call("sim/fault", {"on": "invoke", "mode": "refuse"})
    try:
        twin.invoke("run_protocol", steps=[{"temp": 95, "hold_s": 0}], cycles=1)
        raise AssertionError("the injected refusal did not fire")
    except RemoteError as e:
        assert "injected refusal" in str(e), e
    assert twin.call("device/describe", {"detail": "card"})["state"] == "idle", "a refusal must not latch a fault"

    # a failure inside vendor code latches the device, with an unknown outcome
    twin.call("sim/fault", {"on": "invoke", "mode": "raise"})
    try:
        twin.wait(twin.invoke("run_protocol", steps=[{"temp": 95, "hold_s": 0}], cycles=1))
    except RemoteError:
        pass
    assert twin.call("device/describe", {"detail": "card"})["state"] == "fault"
    twin.call("sim/fault", {"mode": None})        # disarm


def test_every_refusal_declares_what_to_do_about_it():
    """C16: a caller branches on fields, never on wording."""
    from openmhp.client import LocalDevice, RemoteError
    from openmhp.devices.sim_thermocycler import SimThermocycler
    d = LocalDevice(SimThermocycler())
    try:
        d.write("target_temperature", 500)
        raise AssertionError("expected a limit violation")
    except RemoteError as e:
        assert e.transient is False and e.recovery == "abort" and e.effect == "none", e.__dict__
        assert e.device_state == "idle" and e.ts, e.__dict__
    try:
        d.invoke("open_lid")                       # approval: confirm, nobody confirmed
        raise AssertionError("expected an approval refusal")
    except RemoteError as e:
        assert e.transient is True and e.recovery == "operator", e.__dict__


def test_shutdown_is_orderly_and_escalates_when_it_cannot_settle():
    """C21: a stated window to park, then a real e-stop if it is missed."""
    import time
    from openmhp.driver import Driver
    from openmhp.client import LocalDevice

    class Stubborn(Driver):
        """A job that ignores cancellation, which is exactly what the deadline is for."""
        descriptor = {"device": {"id": "stubborn-01", "class": "generic"},
                      "actions": [{"name": "grind", "duration": "long"}],
                      "safety": {"estop": True}}
        def on_read(self, name): return 0
        def on_write(self, name, value): pass
        def on_invoke(self, job):
            time.sleep(1.5)
            return {"done": True}

    d = LocalDevice(Stubborn())
    d.invoke("grind")
    r = d.call("safety/shutdown", {"within_s": 0.3, "reason": "a sibling failed"})
    assert r["shutdown"]["cancelling"], r
    time.sleep(1.0)
    assert d.call("device/describe", {"detail": "card"})["state"] == "estop", "it should have escalated"


def test_a_hardware_stop_cannot_be_cleared_from_software():
    from openmhp.driver import NotSupported
    from openmhp.client import LocalDevice
    from openmhp.devices.sim_thermocycler import SimThermocycler
    t = SimThermocycler()
    d = LocalDevice(t)
    t.latch_external_stop("red button at the bench", clearance="twist the release, then press reset")
    assert d.call("device/describe", {"detail": "card"})["state"] == "estop"
    expect(NotSupported.code, lambda: d.call("safety/reset", {}))
    try:
        d.call("safety/reset", {})
    except Exception as e:
        assert "twist the release" in str(e), e


def test_a_forced_release_will_not_quietly_disarm_the_watchdog():
    """C9: forcing needs a person, and mid-job it is refused until the work is stopped."""
    import time
    from openmhp.driver import NotLeased, ApprovalRequired, DeviceBusy
    from openmhp.client import LocalDevice
    from openmhp.devices.sim_thermocycler import SimThermocycler

    t = SimThermocycler()
    a, b = LocalDevice(t, session="agent-a"), LocalDevice(t, session="agent-b")
    a.acquire(ttl=60)
    expect(NotLeased.code, lambda: b.call("session/release", {}))
    expect(ApprovalRequired.code, lambda: b.call("session/release", {"force": True}))

    a.invoke("run_protocol", steps=[{"temp": 95, "hold_s": 2}] * 3, cycles=3)
    expect(DeviceBusy.code, lambda: b.call("session/release", {"force": True, "approved": True}))
    try:
        b.call("session/release", {"force": True, "approved": True})
    except Exception as e:
        assert "watchdog" in str(e) and "stop: true" in str(e), e

    r = b.call("session/release", {"force": True, "stop": True, "within_s": 2, "approved": True})
    assert r["forcedFrom"] == "agent-a", r
    time.sleep(2.4)
    assert t.lease is None


def test_a_finished_job_survives_a_restart():
    """C11: the record of what ran is on disk, not only in memory."""
    from openmhp.client import LocalDevice
    from openmhp.devices.sim_thermocycler import SimThermocycler
    first = LocalDevice(SimThermocycler())
    job = first.wait(first.invoke("run_protocol", steps=[{"temp": 95, "hold_s": 0}], cycles=1))
    again = LocalDevice(SimThermocycler())         # a fresh process sees the same history
    rec = again.call("jobs/status", {"id": job["id"]})["job"]
    assert rec["state"] == "done" and rec["result"] == job["result"], rec


def test_the_record_cannot_be_edited_without_showing_it():
    """SPEC 3.5 calls the run log append-only and says the answer reports `complete: false` when
    history is missing, but nothing checked either: a changed reading and a deleted refusal still
    came back `complete: true`. Every record now carries the digest of the one before it, so a
    rewrite, a deletion and a reorder each break the chain where they happened."""
    home = HOME / "t7log"
    log = RunLog(home)
    log.write("read", device="tc-01", values={"block_temperature": 22.0})
    log.write("write", device="tc-01", name="target_temperature", value=95, ok=True)
    log.write("refused", op="write", device="tc-01", code=LimitViolation.code, message="300 is above max 105")
    again = RunLog(home)                                   # the chain continues across a restart
    again.write("job", device="tc-01", action="run_protocol", state="done")
    clean = again.audit()
    assert clean["ok"] and clean["records"] == 4 and clean["chained"] == 4, clean
    w = again.window(0, limit=10)                          # a cursor older than memory: read back
    assert w["complete"] and w["verified"]["ok"] and w["verified"]["of"] == "disk", w
    assert log.window(0, limit=10)["verified"] == {"ok": True, "records": 3, "chained": 3,
                                                   "broken": [], "of": "memory"}

    f = sorted((home / "log").glob("*.jsonl"))[-1]         # now edit the record the audit's way
    kept = []
    for line in f.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        if e["kind"] == "refused":
            continue                                       # delete the refusal
        if e["kind"] == "read":
            e["values"]["block_temperature"] = 72.0        # change the reading
        kept.append(json.dumps(e, default=str))
    io.open(f, "w", encoding="utf-8", newline="\n").write("\n".join(kept) + "\n")

    after = RunLog(home)
    after.recent.clear()                                   # a reader with nothing in memory
    w = after.window(0, limit=10)
    assert [e["seq"] for e in w["events"]] == [1, 2, 4], w["events"]
    assert w["complete"] is False, "a deleted record is missing history"
    assert w["verified"]["ok"] is False and w["verified"]["of"] == "disk"
    kinds = {(b["seq"], b["kind"]) for b in w["verified"]["broken"]}
    assert (1, "rewritten") in kinds, kinds                # the changed reading
    assert (4, "missing") in kinds and (4, "chain") in kinds, kinds        # the deleted refusal
    a = after.audit()
    assert a["ok"] is False and a["records"] == 3 and a["files"] == [f.name]
    assert "tamper-evident" in a["note"]

    broke = HOME / "t7err"                                 # a record that never reached disk
    (broke / "log").parent.mkdir(parents=True, exist_ok=True)
    (broke / "log").write_text("not a directory", encoding="utf-8")
    stderr, sys.stderr = sys.stderr, io.StringIO()         # the warning is the point, not the noise
    try:
        nowhere = RunLog(broke)
        nowhere.write("read", device="tc-01", values={"x": 1})
    finally:
        warned, sys.stderr = sys.stderr.getvalue(), stderr
    assert "history on disk is incomplete" in warned, warned
    assert nowhere.write_errors == 1 and nowhere.window(0)["complete"] is False

    # A job record is read back as the device's own history, so it carries its own digest too.
    from openmhp.devices.sim_thermocycler import SimThermocycler
    first = LocalDevice(SimThermocycler())
    job = first.wait(first.invoke("run_protocol", steps=[{"temp": 95, "hold_s": 0}], cycles=1))
    rec_file = HOME / "jobs" / "thermocycler-01" / f"{job['id']}.json"
    rec = json.loads(rec_file.read_text(encoding="utf-8"))
    assert rec["digest"] and rec["result"] == job["result"]
    rec["result"] = {"cycles_completed": 99}
    rec_file.write_text(json.dumps(rec), encoding="utf-8")
    restored = LocalDevice(SimThermocycler()).call("jobs/status", {"id": job["id"]})["job"]
    assert restored["result"] == {"cycles_completed": 99}   # still returned: dropping evidence is worse
    assert "does not match its own digest" in restored["unverified"], restored


def test_conformance_scores_a_device_behaviourally():
    """C17: the levels are a command anyone can run, not a claim in a document."""
    from openmhp.conformance import run, report
    from openmhp.client import connect
    r = run(connect("pkg:openmhp/devices/arm-01", "dut"))
    assert r["Core"]["ok"] and r["Actions"]["ok"] and r["Safe"]["ok"], r
    assert r["_device"]["mhp"], r["_device"]
    assert "Levels met: MHP Core, MHP Actions, MHP Safe" in report(r)


def test_a_failed_job_and_the_fault_are_published_together():
    """SPEC 5.5 requires the job's completion and the device state to be published together.

    Latching the fault after publishing the job leaves a window in which an observer sees a
    failed job on an idle device, and decides the instrument is free. The window is small,
    so this checks the state with no sleep, and repeatedly: a race that is usually lost is
    still a race.
    """
    from openmhp.driver import Driver
    from openmhp.client import LocalDevice, RemoteError

    class Boom(Driver):
        descriptor = {"device": {"id": "boom-01", "class": "generic"},
                      "actions": [{"name": "go", "duration": "short"}],
                      "safety": {"estop": True}}
        def on_read(self, name): return 0
        def on_write(self, name, value): pass
        def on_invoke(self, job): raise RuntimeError("vendor code exploded")

    for _ in range(20):
        d = LocalDevice(Boom())
        try:
            d.wait(d.invoke("go"))
        except RemoteError:
            pass
        # no sleep: the job has settled, so the device must already say so
        assert d.call("device/describe", {"detail": "card"})["state"] == "fault", \
            "a failed job was visible while the device still read idle"


def test_the_error_taxonomy_survives_the_client_boundary():
    """The fields are useless if the SDK drops them on the way through."""
    from openmhp.client import LocalDevice, RemoteError
    from openmhp.devices.sim_thermocycler import SimThermocycler
    d = LocalDevice(SimThermocycler())
    try:
        d.read("no_such_signal")
        raise AssertionError("expected a refusal")
    except RemoteError as e:
        for field in ("ts", "transient", "effect", "recovery", "device_state"):
            assert getattr(e, field, None) is not None, f"the client dropped {field}"
        assert e.recovery == "abort" and e.effect == "none", e.__dict__


def test_a_result_with_mixed_key_types_is_persisted():
    """csv.DictReader on a malformed CSV puts surplus fields under the key None. Digesting the job
    record sorted its keys, None against str raised inside the job thread, and everything after
    persistence was skipped: no record, no jobs/finished, no method-run record. Keys are now
    written as JSON would write them, and the completion steps run whatever persistence does."""
    rows = list(csv.DictReader(io.StringIO("a\n1,x\n")))
    assert None in rows[0], rows                                    # the shape that broke it
    d = BoundDriver(device={"id": "csv-1", "class": "generic"}, safety={"estop": False, "watchdog_s": None},
                    actions=[Action("parse", lambda job, params: {"rows": [{None: ["x"], "a": 1}]})])
    dev = LocalDevice(d)
    job = dev.wait(dev.invoke("parse"))
    assert job["state"] == "done", job
    got = dev.call("jobs/status", {"id": job["id"]})["job"]
    assert got["state"] == "done" and got["result"]["rows"][0]["a"] == 1, got

    f = HOME / "jobs" / "csv-1" / f"{job['id']}.json"
    for _ in range(200):                                            # the record lands just after done
        if f.exists():
            break
        time.sleep(0.02)
    rec = json.loads(f.read_text(encoding="utf-8"))
    assert rec["result"] == {"rows": [{"null": ["x"], "a": 1}]}, rec

    again = BoundDriver(device={"id": "csv-1", "class": "generic"}, safety={"estop": False, "watchdog_s": None},
                        actions=[Action("parse", lambda job, params: None)])
    restored = LocalDevice(again).call("jobs/status", {"id": job["id"]})["job"]
    assert restored["state"] == "done" and restored["result"]["rows"][0]["null"] == ["x"], restored
    assert again.jobs[job["id"]].unverified is None, "the restored record failed its own digest"

    # and a persistence failure of any kind still lets the job finish
    boom = BoundDriver(device={"id": "csv-2", "class": "generic"}, safety={"estop": False, "watchdog_s": None},
                       actions=[Action("parse", lambda job, params: {"ok": True})])
    queued_persist = boom._persist_job
    boom._persist_job = lambda job: (queued_persist(job) if job.state == "queued"
                                     else fails(RuntimeError("disk on fire"))())
    told = []
    real_notify = boom.notify
    boom.notify = lambda m, p: (told.append(m), real_notify(m, p))
    bdev = LocalDevice(boom)
    bj = bdev.wait(bdev.invoke("parse"))
    assert bj["state"] == "done" and bj["result"] == {"ok": True}, bj
    for _ in range(200):
        if "jobs/finished" in told:
            break
        time.sleep(0.02)
    assert "jobs/finished" in told, told


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
