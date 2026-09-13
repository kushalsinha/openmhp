"""Methods (SPEC 4.5, M1..M10) and pushed events reaching the agent. No hardware, no network beyond localhost.

    PYTHONPATH=. python tests/test_methods.py
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time

sys.path.insert(0, ".")
os.environ["OPENMHP_HOME"] = tempfile.mkdtemp()
os.environ["OPENMHP_SIM_TIME_SCALE"] = "0.001"

from openmhp.client import LocalDevice, RemoteError, connect                    # noqa: E402
from openmhp.driver import MethodRequired, NotSupported, InvalidValue, LimitViolation, UnknownName   # noqa: E402
from openmhp.fleet import Fleet                                                # noqa: E402
from openmhp.mcp_bridge import Bridge                                          # noqa: E402
from openmhp.methods import MethodStore, check_record                          # noqa: E402
from openmhp.validate import validate_path                                     # noqa: E402

HOME = os.environ["OPENMHP_HOME"]
PROG = [{"temp": 60, "hold_s": 60}, {"temp": 200, "ramp_c_min": 20, "hold_s": 30}]


def package_copy(name: str) -> str:
    """A private copy of a bundled package, so tests never write into the repository's methods/ folder."""
    dst = os.path.join(tempfile.mkdtemp(), name)
    shutil.copytree(os.path.join("openmhp", "devices", name), dst)
    return dst


def gc(target_kind="sim"):
    return connect(f"{target_kind}:{package_copy('gc-01')}", "gc-01")


def raises(code_cls, fn):
    try:
        fn()
    except RemoteError as e:
        assert e.code == code_cls.code, f"expected {code_cls.__name__}, got {e.code}: {e.message}"
        return e
    raise AssertionError(f"expected {code_cls.__name__}")


def test_m1_capability_follows_the_declaration():
    """Every device answers methods/*; only a device with a method-driven action keeps any."""
    d = gc()
    assert d.info["capabilities"]["methods"] is True
    assert d.describe("summary")["methods"]["method_driven"] == ["run_method"]
    from openmhp.devices.sim_arm import SimArm
    arm = LocalDevice(SimArm(), "arm-01")
    assert arm.info["capabilities"]["methods"] is False and arm.describe("summary")["methods"] is None
    assert arm.methods()["methods"] == [] and arm.method_find("anything")["choice"] == "none"
    raises(NotSupported, lambda: arm.method_save({"name": "x", "action": "home", "params": {}, "compounds": ["c"]}))
    d.close(); arm.close()


def test_m2_m3_folder_and_record_rules():
    pkg = package_copy("gc-01")
    v = validate_path(pkg)
    assert v["ok"], v["errors"]
    assert any("never validated" in w for w in v["warnings"])          # the bundled _shared file is hand-written
    # a stray file, a bad project id, a record whose name disagrees with its path, an unknown key
    os.makedirs(os.path.join(pkg, "methods", "Bad Project"))
    open(os.path.join(pkg, "methods", "notes.txt"), "w").write("x")
    store = MethodStore(os.path.join(pkg, "methods"), method_driven=lambda: ["run_method"])
    good = store.get("_shared/solvent-screen")
    import yaml
    os.makedirs(os.path.join(pkg, "methods", "p1"))
    open(os.path.join(pkg, "methods", "p1", "wrong-name.yaml"), "w").write(yaml.safe_dump({**good, "extra": 1}))
    probs = MethodStore(os.path.join(pkg, "methods"), method_driven=lambda: ["run_method"]).problems()
    assert any("Bad Project" in p for p in probs) and any("notes.txt" in p for p in probs)
    assert any("does not match the file name" in p for p in probs) and any("unknown keys" in p for p in probs)
    assert not validate_path(pkg)["ok"]
    # a package with a methods/ folder but no method-driven action is invalid
    arm = package_copy("arm-01")
    os.makedirs(os.path.join(arm, "methods", "_shared"))
    assert any("M1" in e for e in validate_path(arm)["errors"])
    # ids
    assert check_record({**good, "hash": "000000000000"}) and not check_record(good)
    for bad in ("Bad/x", "a b", "../x", "_shared/../x"):
        try:
            store.get(bad); assert False, bad
        except Exception:
            pass


def test_m4_m5_save_validates_and_versions():
    d = gc()
    m = {"name": "ethanol-ipa", "project": "solvent-screen", "action": "run_method", "compounds": ["Ethanol", "isopropanol"],
         "params": {"oven_program": PROG, "injection_volume_ul": 1, "carrier_flow_ml_min": 1.5, "sample": "ethanol isopropanol"},
         "source": {"kind": "person", "ref": "method sheet"}}
    # the device's own gate runs first: nothing is written when it refuses
    raises(LimitViolation, lambda: d.method_save({**m, "params": {**m["params"], "oven_program": [{"temp": 400}]}}))
    raises(InvalidValue, lambda: d.method_save({**m, "params": {**m["params"], "bogus": 1}}))
    raises(InvalidValue, lambda: d.method_save({**m, "action": "bakeout"}))          # not method-driven
    raises(InvalidValue, lambda: d.method_save({**m, "version": 7}))               # the device assigns versions
    assert d.method_find("ethanol", "solvent-screen")["choice"] == "one"            # only _shared so far, newProject
    r = d.method_save(m, note="from the method sheet")
    assert r["validated"] and r["saved"]["version"] == 1 and r["saved"]["compounds"] == ["ethanol", "isopropanol"]
    rec = d.method("solvent-screen/ethanol-ipa")
    assert rec["validated"]["hash"] == rec["hash"] and rec["status"] == "active" and rec["author"]
    # metadata-only change keeps the version; a parameter change bumps it and keeps history
    assert d.method_save({**m, "notes": "renamed"})["saved"]["version"] == 1
    r2 = d.method_save({**m, "params": {**m["params"], "carrier_flow_ml_min": 1.0}})
    assert r2["saved"]["version"] == 2
    v1 = d.method("ethanol-ipa", "solvent-screen", version=1)
    assert v1["params"]["carrier_flow_ml_min"] == 1.5 and v1["version"] == 1
    diff = d.method_diff("solvent-screen/ethanol-ipa", a_version=1)
    assert diff["params"] == {"carrier_flow_ml_min": {"from": 1.5, "to": 1.0}} and not diff["same"]
    # retire keeps the file, hides it from find, and a new save reactivates as version 3
    d.method_retire("solvent-screen/ethanol-ipa")
    assert d.method_find("ethanol", "solvent-screen")["method"]["project"] == "_shared"
    assert d.methods(retired=True)["methods"][0]["status"] == "retired" and d.methods()["methods"][0]["project"] == "_shared"
    raises(InvalidValue, lambda: d.run_method("solvent-screen/ethanol-ipa"))
    assert d.method_save(m)["saved"]["version"] == 3
    d.close()


def test_m6_m7_m8_running_and_asking():
    d = gc()
    base = {"oven_program": PROG, "injection_volume_ul": 1, "carrier_flow_ml_min": 1.5, "sample": "ethanol isopropanol"}
    # M7: a method-driven action with neither method nor params is refused, and says what to ask
    e = raises(MethodRequired, lambda: d.invoke("run_method"))
    assert e.data["choice"] == "several" and "Which method" in e.data["ask"]
    e = raises(MethodRequired, lambda: d.call("actions/invoke", {"name": "run_method", "compound": "hexane", "project": "p9"}))
    assert e.data["choice"] == "none" and "hexane" in e.data["ask"] and e.data["newProject"] == "p9"
    # explicit params under a new project are accepted, with a hint to save them
    r = d.call("actions/invoke", {"name": "run_method", "params": base, "project": "p9", "compound": "ethanol", "dryRun": True})
    assert "methodHint" in r and r["job"]["project"] == "p9"
    # M8 precedence: project, then _shared, then other projects
    d.method_save({"name": "a", "project": "p1", "action": "run_method", "compounds": ["ethanol"], "params": base})
    d.method_save({"name": "b", "project": "p2", "action": "run_method", "compounds": ["ethanol"], "params": base})
    assert d.method_find("ethanol", "p1")["method"]["name"] == "a"
    f = d.method_find("ethanol", "p3")
    assert f["choice"] == "one" and f["method"]["project"] == "_shared" and f["newProject"] == "p3"
    d.method_retire("_shared/solvent-screen")
    f = d.method_find("ethanol", "p3")
    assert f["choice"] == "several" and {c["project"] for c in f["candidates"]} == {"p1", "p2"} and "p3" in f["ask"]
    assert d.method_find("toluene")["choice"] == "none"
    # M6: run by name; job carries provenance; overrides apply for this run only; the runs file grows
    with d:
        job = d.run_method("p1/a", {"carrier_flow_ml_min": 1.0}, run_project="p3", compound="ethanol")
    assert job["state"] == "done" and job["method"]["name"] == "a" and job["method"]["project"] == "p1"
    assert job["method"]["version"] == 1 and job["method"]["overrides"] == {"carrier_flow_ml_min": 1.0} and job["project"] == "p3"
    assert job["result"]["carrier_flow_ml_min"] == 1.0 and d.method("p1/a")["params"]["carrier_flow_ml_min"] == 1.5
    runs = open(os.path.join(d.driver.methods.root, "p1", "a.runs.jsonl")).read().splitlines()
    rec = json.loads(runs[-1])
    assert rec["job"] == job["id"] and rec["state"] == "done" and rec["project"] == "p3" and rec["result_digest"]
    raises(UnknownName, lambda: d.run_method("p1/missing"))
    raises(InvalidValue, lambda: d.call("actions/invoke", {"name": "bakeout", "method": {"name": "a", "project": "p1"}}))
    d.close()


def test_methods_are_generic_a_pcr_program_is_one():
    d = connect(f"sim:{package_copy('thermocycler-01')}", "thermocycler-01")
    assert d.method_find("generic-dna")["method"]["name"] == "standard-three-step"
    d.method_save({"name": "plasmid-x", "project": "cloning-2026", "action": "run_protocol", "compounds": ["plasmid-x"],
                   "params": {"steps": [{"temp": 98, "hold_s": 10}, {"temp": 65, "hold_s": 15}], "cycles": 2},
                   "derived_from": {"project": "_shared", "name": "standard-three-step", "version": 1}})
    raises(LimitViolation, lambda: d.method_save({"name": "hot", "project": "cloning-2026", "action": "run_protocol",
                                                  "compounds": ["x"], "params": {"steps": [{"temp": 120, "hold_s": 1}], "cycles": 1}}))
    with d:
        job = d.run_method("cloning-2026/plasmid-x")
    assert job["result"]["cycles_completed"] == 2 and job["method"]["project"] == "cloning-2026"
    d.close()


def fresh_bridge():
    from openmhp import client as C
    for t in list(C._inprocess):
        C.drop_inprocess(t)
    f = Fleet(os.path.join(tempfile.mkdtemp(), "fleet.json"))
    b = Bridge(fleet=f)
    b.call_tool("mhp_lab", {"op": "add", "target": package_copy("gc-01"), "sim": True, "location": "bay 2"})
    return b


def test_bridge_tool_routes_to_the_device_and_logs_provenance():
    b = fresh_bridge()
    dev = "gc-01-sim"
    f = b.call_tool("mhp_method", {"op": "find", "device": dev, "compound": "acetone", "project": "solvent-screen"})
    assert f["choice"] == "one" and f["method"]["project"] == "_shared"
    saved = b.call_tool("mhp_method", {"op": "save", "device": dev, "method": {
        "name": "acetone-fast", "project": "solvent-screen", "action": "run_method", "compounds": ["acetone"],
        "params": {"oven_program": PROG, "injection_volume_ul": 1, "carrier_flow_ml_min": 2.0, "sample": "acetone"}}})
    assert saved["saved"]["version"] == 1
    r = b.call_tool("mhp_method", {"op": "run", "device": dev, "name": "solvent-screen/acetone-fast", "overrides": {"carrier_flow_ml_min": 1.5}})
    assert r["job"]["state"] == "done" and r["job"]["method"]["hash"] == saved["saved"]["hash"]
    log = b.log.window(0, 200)["events"]
    inv = [e for e in log if e["kind"] == "invoke" and e.get("method")]
    assert inv and inv[-1]["method"]["name"] == "acetone-fast" and inv[-1]["method"]["overrides"] == {"carrier_flow_ml_min": 1.5}
    assert any(e["kind"] == "method/save" for e in log) and any(e["kind"] == "device/methods/saved" for e in log)
    # mhp_invoke with method= is the same path
    j = b.call_tool("mhp_invoke", {"device": dev, "name": "run_method", "method": {"name": "acetone-fast", "project": "solvent-screen"},
                                   "project": "solvent-screen", "wait": True})
    assert j["method"]["version"] == 1 and j["project"] == "solvent-screen"
    # the tool-level refusal carries the ask
    try:
        b.call_tool("mhp_invoke", {"device": dev, "name": "run_method", "compound": "hexane"})
        assert False
    except RemoteError as e:
        assert e.code == MethodRequired.code and e.data["choice"] == "none"


def test_results_are_pushed_to_the_agent_without_polling():
    b = fresh_bridge()
    dev = "gc-01-sim"
    b.call_tool("mhp_method", {"op": "run", "device": dev, "name": "_shared/solvent-screen"})
    u = b.call_tool("mhp_data", {"op": "updates", "device": dev, "signal": "last_result"})
    assert u["updates"] and u["updates"][-1]["value"]["resolution_min"] is not None
    fin = b.call_tool("mhp_data", {"op": "updates", "device": dev})["updates"]
    done = [x for x in fin if x["event"] == "jobs/finished"]
    assert done and done[-1]["method"]["name"] == "solvent-screen" and "chromatogram" in done[-1]["result"]
    from openmhp.mcp_bridge import _cap                                      # bulky results are capped in buffers and logs
    big = _cap({"peaks": [1, 2], "trace": [[i, i * 0.5] for i in range(5000)]})
    assert big["peaks"] == [1, 2] and isinstance(big["trace"], str) and "5000 items" in big["trace"]
    # a run that uses the device gets events.jsonl next to its files
    script = ("d = lab['gc-01-sim']\nwith d:\n    j = d.run_method('_shared/solvent-screen', {'carrier_flow_ml_min': 1.0})\n"
              "print(j['result']['resolution_min'], j['method']['version'])")
    res = b.call_tool("mhp_run", {"script": script, "name": "one injection"})
    assert res["ok"], res
    ev = b.call_tool("mhp_data", {"op": "read", "run": res["run"]["id"], "path": "events.jsonl"})["text"].splitlines()
    kinds = [json.loads(l)["event"] for l in ev]
    assert "jobs/finished" in kinds and "signals/update" in kinds and all(json.loads(l)["run"] == res["run"]["id"] for l in ev)
    # a plan shows the method next to the step and executes nothing
    plan = b.call_tool("mhp_run", {"script": script, "plan": True})["plan"]
    step = [s for s in plan["steps"] if s["kind"] == "invoke"][0]
    assert step["method"]["name"] == "solvent-screen" and step["gate"] == "ok" and step.get("long_running")
    assert b.call_tool("mhp_read", {"device": dev, "names": ["injections_today"]})["values"]["injections_today"] == 2


def test_http_devices_push_too():
    from openmhp.devices.sim_gc import SimGC
    from openmhp.transport import serve_http
    drv = SimGC()
    drv.methods_dir = os.path.join(tempfile.mkdtemp(), "methods")
    shutil.copytree(os.path.join("openmhp", "devices", "gc-01", "methods"), drv.methods_dir)
    threading.Thread(target=serve_http, args=(drv,), kwargs={"port": 18947}, daemon=True).start()
    time.sleep(0.4)
    b = fresh_bridge()
    b.call_tool("mhp_lab", {"op": "add", "target": "http://127.0.0.1:18947", "location": "bay 5"})
    got = []
    d = b.lab["gc-01"]
    d.subscribe(lambda m: got.append(m["method"]))
    r = b.call_tool("mhp_method", {"op": "run", "device": "gc-01", "name": "_shared/solvent-screen"})
    assert r["job"]["state"] == "done" and r["job"]["method"]["project"] == "_shared"
    deadline = time.time() + 3
    while time.time() < deadline and "notifications/jobs/finished" not in got:
        time.sleep(0.05)
    assert "notifications/jobs/finished" in got and "notifications/signals/update" in got
    u = b.call_tool("mhp_data", {"op": "updates", "device": "gc-01", "signal": "last_result"})
    assert u["updates"] and u["updates"][-1]["value"]["injection"] == 1
    d.close()


def test_recipe_closes_the_loop():
    b = fresh_bridge()
    dev = "gc-01-sim"
    plan = b.call_tool("mhp_run", {"recipe": "optimize-separation", "params": {"device": dev, "compound": "ethanol", "project": "_shared"}, "plan": True})
    assert plan["ok"], plan
    res = b.call_tool("mhp_run", {"recipe": "optimize-separation", "params": {"device": dev, "compound": "ethanol", "project": "_shared"}})
    assert res["ok"], res
    assert "target 1.5 reached" in res["stdout"] and "saved _shared/solvent-screen v2" in res["stdout"]
    m = b.call_tool("mhp_method", {"op": "get", "device": dev, "name": "_shared/solvent-screen"})
    assert m["version"] == 2 and m["params"]["carrier_flow_ml_min"] < 1.5 and m["derived_from"]["version"] == 1
    assert m["source"]["kind"] == "agent"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok ", name)
