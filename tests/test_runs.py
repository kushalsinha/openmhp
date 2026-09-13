"""Recipes, plan mode, background runs and data, events, pause/resume, elicitation,
safety card, registry, simulated twins. No hardware, no network.

    PYTHONPATH=. python tests/test_runs.py
"""
import io
import json
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, ".")
os.environ["OPENMHP_HOME"] = tempfile.mkdtemp()

from openmhp.client import RemoteError                                      # noqa: E402
from openmhp.fleet import Fleet                                            # noqa: E402
from openmhp.mcp_bridge import Bridge, StdioLoop, TOOLS                    # noqa: E402

HOME = os.environ["OPENMHP_HOME"]


def fresh_bridge():
    from openmhp import client as C
    for target in list(C._inprocess):                 # fresh drivers: earlier bridges may still hold leases
        C.drop_inprocess(target)
    f = Fleet(os.path.join(HOME, "fleet.json"))
    b = Bridge(fleet=f)
    for name in ("thermocycler-01", "arm-01"):
        b.call_tool("mhp_lab", {"op": "add", "target": f"openmhp/devices/{name}"})
    return b


def test_recipes_plan_and_run():
    b = fresh_bridge()
    rs = b.call_tool("mhp_lab", {"op": "recipes", "query": "pcr plate transfer"})["recipes"]
    assert rs[0]["name"] == "pcr-with-plate-transfer" and "robot_arm" in rs[0]["needs"]
    # plan: nothing moves, gates evaluated, long steps flagged
    plan = b.call_tool("mhp_run", {"recipe": "pcr-with-plate-transfer", "params": {"cycles": 2}, "plan": True})["plan"]
    kinds = [s["kind"] for s in plan["steps"]]
    assert "invoke" in kinds and "write" in kinds and plan["refused"] == [] and "ok" in plan["verdict"]
    assert any(s.get("long_running") for s in plan["steps"])
    assert len(plan["asks_human"]) == 2                                      # both lid openings need a person
    assert b.lab["arm-01"].read("homed") is False                            # plan did not home the arm
    # plan catches a refusal before anything runs
    bad = b.call_tool("mhp_run", {"script": "lab['thermocycler-01'].write('target_temperature', 500)", "plan": True})["plan"]
    assert bad["refused"] and "refused at step 1" in bad["verdict"]
    # real run: a person confirms both lid openings
    b.client_caps, b.send_request = {"elicitation": {}}, lambda m, p: {"action": "accept", "content": {"confirm": True}}
    r = b.call_tool("mhp_run", {"recipe": "pcr-with-plate-transfer", "params": {"cycles": 2, "steps": [{"temp": 95, "hold_s": 0}, {"temp": 60, "hold_s": 0}]}, "name": "pcr test"})
    assert r["ok"] and "pcr done" in r["stdout"], r
    assert b.lab["arm-01"].read("homed") is True


def test_background_run_and_data():
    b = fresh_bridge()
    r = b.call_tool("mhp_run", {"recipe": "setpoint-sweep", "background": True,
                                "params": {"device": "thermocycler-01", "values": [30, 40], "settle_s": 0.3, "samples": 2, "restore": 22}})
    rid = r["run"]["id"]
    assert r["run"]["state"] == "running"
    for _ in range(200):
        runs = b.call_tool("mhp_data", {"op": "runs"})["runs"]
        mine = next(r for r in runs if r["id"] == rid)
        if mine["state"] != "running":
            break
        time.sleep(0.1)
    assert mine["state"] == "done", mine
    files = b.call_tool("mhp_data", {"op": "list", "run": "latest"})["files"]
    assert "sweep.csv" in files
    csv = b.call_tool("mhp_data", {"op": "read", "run": rid, "path": "sweep.csv"})["text"]
    assert csv.startswith("setpoint,measured_mean") and "40," in csv
    out = b.call_tool("mhp_data", {"op": "read", "run": "latest", "path": "stdout.txt"})["text"]
    assert "measured" in out
    log = b.call_tool("mhp_data", {"op": "log", "since": 0})["events"]
    assert any(e["kind"] == "run/finish" and e["run"] == rid for e in log)
    try:
        b.call_tool("mhp_data", {"op": "read", "run": rid, "path": "../../fleet.json"}); assert False
    except PermissionError:
        pass


def test_pause_resume_and_events():
    b = fresh_bridge()
    job = b.call_tool("mhp_invoke", {"device": "thermocycler-01", "name": "run_protocol",
                                     "params": {"steps": [{"temp": 95, "hold_s": 0.2}, {"temp": 60, "hold_s": 0.2}], "cycles": 30}})
    time.sleep(0.3)
    p = b.call_tool("mhp_job", {"device": "thermocycler-01", "id": job["id"], "op": "pause"})
    assert p["paused"] is True
    time.sleep(0.4)                                                            # the step in flight reaches its checkpoint
    prog = b.call_tool("mhp_job", {"device": "thermocycler-01", "id": job["id"]})["progress"]
    time.sleep(0.6)
    assert b.call_tool("mhp_job", {"device": "thermocycler-01", "id": job["id"]})["progress"] == prog   # frozen while paused
    b.call_tool("mhp_job", {"device": "thermocycler-01", "id": job["id"], "op": "resume"})
    time.sleep(0.5)
    assert b.call_tool("mhp_job", {"device": "thermocycler-01", "id": job["id"]})["progress"] > prog
    c = b.call_tool("mhp_job", {"device": "thermocycler-01", "id": job["id"], "op": "cancel"})
    time.sleep(0.5)
    assert b.call_tool("mhp_job", {"device": "thermocycler-01", "id": job["id"]})["state"] == "cancelled"
    ev = b.call_tool("mhp_lab", {"op": "events", "since": 0})["events"]
    kinds = {e["kind"] for e in ev}
    assert "job/pause" in kinds and "job/cancel" in kinds and "device/jobs/finished" in kinds
    try:
        b.call_tool("mhp_write", {"device": "thermocycler-01", "name": "target_temperature", "value": 900}); assert False
    except RemoteError:
        pass
    assert any(e["kind"] == "refused" and e["code"] == -32010 for e in b.log.recent)


def test_elicitation_confirms_gated_action():
    """Drive the bridge through StdioLoop with a fake client that answers elicitation requests."""
    b = fresh_bridge()
    b.client_caps = {"elicitation": {}}
    answers, sent = {"accept": True}, []

    class FakeStdout:
        def write(self, s):
            msg = json.loads(s)
            sent.append(msg)
            if msg.get("method") == "elicitation/create":       # the "harness" asks the person, who says yes or no
                with loop._cv:
                    loop._pending[str(msg["id"])] = {"jsonrpc": "2.0", "id": msg["id"], "result": {
                        "action": "accept" if answers["accept"] else "decline", "content": {"confirm": True}}}
                    loop._cv.notify_all()
        def flush(self): pass

    loop = StdioLoop(b, out=FakeStdout())
    j = b.call_tool("mhp_invoke", {"device": "thermocycler-01", "name": "open_lid", "wait": True})
    assert j["state"] == "done"
    assert any(m.get("method") == "elicitation/create" and "open_lid" in m["params"]["message"] for m in sent)
    answers["accept"] = False
    b.lab["thermocycler-01"].driver.lid_closed = True
    try:
        b.call_tool("mhp_invoke", {"device": "thermocycler-01", "name": "open_lid", "approved": True}); assert False
    except RemoteError as e:
        assert "declined" in e.message
    b.call_tool("mhp_estop", {"device": "thermocycler-01", "reason": "test"})
    assert any(m.get("method") == "notifications/message" and "E-STOP" in m["params"]["data"] for m in sent)
    b.lab["thermocycler-01"].reset()


def test_safety_card_registry_and_sim_twin():
    b = fresh_bridge()
    card = b.call_tool("mhp_lab", {"op": "safety_card", "id": "thermocycler-01"})
    assert card["ok"] and "SAFETY CARD" in card["text"] and "refused" in card["text"]
    assert any(p["name"] == "open_lid" and "once a person confirms" in p["result"] for p in card["probes"])
    reg = b.call_tool("mhp_lab", {"op": "registry", "query": "ika hotplate serial"})["packages"]
    assert reg[0]["name"] == "ika-c-mag-hs7"
    # community package's simulated twin, added from the local checkout (github: would clone)
    added = b.call_tool("mhp_lab", {"op": "add", "target": "packages/ika-c-mag-hs7", "sim": True})["added"]
    assert added["id"] == "ika-c-mag-hs7-01-sim" and "simulated" in added["tags"]
    dev = "ika-c-mag-hs7-01-sim"
    assert b.call_tool("mhp_read", {"device": dev, "names": ["plate_temperature"]})["values"]["plate_temperature"] > 0
    b.call_tool("mhp_write", {"device": dev, "name": "target_temperature", "value": 60})
    b.call_tool("mhp_invoke", {"device": dev, "name": "start_heating", "wait": True})
    time.sleep(0.3)
    assert b.call_tool("mhp_read", {"device": dev, "names": ["plate_temperature"]})["values"]["plate_temperature"] > 22
    try:
        b.call_tool("mhp_write", {"device": dev, "name": "target_temperature", "value": 400}); assert False
    except RemoteError as e:
        assert e.code == -32010
    c2 = b.call_tool("mhp_lab", {"op": "add", "target": "packages/manual-benchtop-centrifuge", "sim": True})["added"]
    assert c2["class"] == "centrifuge"
    hits = b.call_tool("mhp_find", {"query": "spin tubes centrifuge"})
    assert hits[0]["id"] == "centrifuge-01-sim"
    card2 = b.call_tool("mhp_lab", {"op": "safety_card", "id": "centrifuge-01-sim"})
    assert "requires balanced" in card2["text"]
    assert len(TOOLS) == 11


def test_mcp_surface():
    b = fresh_bridge()
    init = b.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"capabilities": {"elicitation": {}}}})["result"]
    assert "logging" in init["capabilities"] and "plan=true" in init["instructions"] and b.can_elicit() is False  # no send_request yet
    prompts = [p["name"] for p in b.handle({"jsonrpc": "2.0", "id": 2, "method": "prompts/list"})["result"]["prompts"]]
    assert prompts == ["setup-my-lab", "add-instrument", "run-experiment", "lab-status"]
    b.call_tool("mhp_run", {"script": "print('hello run')"})
    res = b.handle({"jsonrpc": "2.0", "id": 3, "method": "resources/read", "params": {"uri": "mhp://runs/latest/stdout.txt"}})["result"]
    assert "hello run" in res["contents"][0]["text"]
    log = b.handle({"jsonrpc": "2.0", "id": 4, "method": "resources/read", "params": {"uri": "mhp://log/today"}})["result"]
    assert "run/finish" in log["contents"][0]["text"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok ", name)
