"""An instrument's states, said plainly: every answer that reports a device's state (ping, describe, every refusal,
through the client and through the MCP bridge) carries the facts behind it and the next steps from it, so neither a
person nor an agent has to infer what to do from a state's name.

    PYTHONPATH=. python tests/test_device_states.py
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.environ.setdefault("OPENMHP_HOME", tempfile.mkdtemp(prefix="openmhp-device-states-"))
os.environ["OPENMHP_NO_UPDATE_CHECK"] = "1"

from openmhp import driver as D, states as ST                                     # noqa: E402
from openmhp.client import Lab, LocalDevice, RemoteError                          # noqa: E402
from openmhp.devices.sim_thermocycler import SimThermocycler                      # noqa: E402
from openmhp.mcp_bridge import TOOLS, Bridge                                      # noqa: E402

TC = "local:openmhp.devices.sim_thermocycler:SimThermocycler"


def test_the_device_machine_is_declared_once_and_its_steps_are_real():
    """Every state has next steps, and every step names a tool the bridge offers and a method the device answers."""
    tools = {t["name"] for t in TOOLS} | {"mhp_method"}
    assert set(ST.DEVICE_STATES) == {"idle", "busy", "fault", "estop"} and "unreachable" in ST.DEVICE_LISTED_STATES
    for state, to in ST.DEVICE_TRANSITIONS.items():
        assert to <= set(ST.DEVICE_STATES), (state, to)
    cases = [dict(state=s) for s in ST.DEVICE_LISTED_STATES] + [
        dict(state="busy", active_jobs=["job_1"]), dict(state="fault", fault_reason="x", active_jobs=["job_1"]),
        dict(state="estop", stop={"source": "hardware", "clearable": False, "clearance": "twist it"}),
        dict(state="idle", shutting_down=True)]
    for c in cases:
        state = c.pop("state")
        steps = ST.device_next(state, **c)
        assert steps and all(s["does"] for s in steps), (state, c)
        for s in steps:
            assert s.get("tool") is None or s["tool"] in tools, s
            m = s.get("method")
            assert m is None or m.startswith("directory/") or hasattr(D.Driver, "rpc_" + m.replace("/", "_")), s
    for code, steps in ST.ERROR_NEXT.items():
        for s in steps:
            assert s.get("tool") is None or s["tool"] in tools, (code, s)
            m = s.get("method")
            assert m is None or hasattr(D.Driver, "rpc_" + m.replace("/", "_")), (code, s)
    # every error class the device raises has its next steps, or is one where the state's own steps say it all
    raised = {c.code for c in vars(D).values() if isinstance(c, type) and issubclass(c, D.MHPError) and c is not D.MHPError}
    assert raised - set(ST.ERROR_NEXT) <= {D.MethodNotFound.code, D.DeviceFault.code, D.EStopActive.code,
                                           D.NotSupported.code}, raised - set(ST.ERROR_NEXT)


def test_ping_says_what_it_is_doing_and_what_comes_next():
    t = SimThermocycler()
    d = LocalDevice(t)
    p = d.call("ping")
    assert p["state"] == "idle" and p["active_jobs"] == [] and p["next"][0]["tool"] == "mhp_describe", p
    job = d.call("actions/invoke", {"name": "run_protocol", "params": {"steps": [{"temp": 40, "hold_s": 5}], "cycles": 1}})["job"]
    p = d.call("ping")
    assert p["state"] == "busy" and p["active_jobs"] == [job["id"]], p
    assert p["next"][0]["method"] == "jobs/status" and job["id"] in p["next"][0]["does"], p["next"]
    d.call("safety/shutdown", {"within_s": 5})
    p = d.call("ping")
    assert "shutting_down" in p and "parking" in p["next"][0]["does"], p
    for _ in range(100):
        if "shutting_down" not in d.call("ping"):
            break
        time.sleep(0.1)
    # describe carries the same facts (summary and full); the card stays small for directory listings
    assert "next" in d.call("device/describe", {"detail": "summary"})
    assert "next" in d.call("device/describe", {"detail": "full"})
    assert "next" not in d.call("device/describe", {"detail": "card"})


def test_every_refusal_says_what_to_do_about_it():
    d = LocalDevice(SimThermocycler())
    try:
        d.call("settings/write", {"name": "target_temperature", "value": 500}); assert False
    except RemoteError as e:
        assert e.code == D.LimitViolation.code and e.next[0]["method"] == "safety/limits", e.next
    d.estop("smoke")
    try:
        d.call("settings/write", {"name": "target_temperature", "value": 50}); assert False
    except RemoteError as e:
        assert e.code == D.EStopActive.code and e.device_state == "estop" and e.recovery == "operator"
        assert any(s.get("tool") == "mhp_reset" for s in e.next), e.next
        assert any("on request" in s["does"] for s in e.next), e.next          # who stopped it, in words


def test_a_job_that_fails_with_a_typed_error_keeps_it():
    t = SimThermocycler()
    d = LocalDevice(t)
    real = t.on_invoke
    def lid_opens(job):
        raise D.InterlockOpen("interlock 'lid_closed' opened mid-run", {"interlock": "lid_closed"})
    t.on_invoke = lid_opens
    job = d.call("actions/invoke", {"name": "run_protocol", "params": {"steps": [{"temp": 40, "hold_s": 1}], "cycles": 1}})["job"]
    try:
        d.wait(job, timeout=10); assert False
    except RemoteError as e:
        assert e.device_state == "fault" and any(s.get("tool") == "mhp_reset" for s in e.next), (e.device_state, e.next)
    t.on_invoke = real
    snap = d.status(job)
    assert snap["errorDetail"]["code"] == D.InterlockOpen.code and snap["errorDetail"]["data"] == {"interlock": "lid_closed"}
    assert snap["errorDetail"]["recovery"] == "operator" and snap["error"].startswith("InterlockOpen:"), snap


def test_the_bridge_hands_the_agent_the_whole_refusal():
    b = Bridge(targets={"thermocycler-01": TC})
    r = b.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
        "name": "mhp_write", "arguments": {"device": "thermocycler-01", "name": "target_temperature", "value": 500}}})
    assert r["result"]["isError"]
    err = json.loads(r["result"]["content"][0]["text"])["mhpError"]
    assert err["code"] == D.LimitViolation.code and err["transient"] is False and err["recovery"] == "abort", err
    assert err["effect"] == "none" and err["state"] == "idle" and err["next"][0]["method"] == "safety/limits", err
    find = next(t for t in TOOLS if t["name"] == "mhp_find")
    assert "unreachable" in find["inputSchema"]["properties"]["state"]["enum"]


def test_a_small_lab_finds_with_its_filters_and_lists_a_silent_device_last():
    lab = Lab({"thermocycler-01": TC, "gone-01": "http://127.0.0.1:9"})
    every = lab.find("", limit=10)
    assert [c["id"] for c in every] == ["thermocycler-01", "gone-01"], every
    gone = every[1]
    assert gone["state"] == "unreachable" and gone["next"] and "mhp node" in gone["next"][0]["does"], gone
    assert [c["id"] for c in lab.find("", limit=10, cls="thermal_cycler")] == ["thermocycler-01", "gone-01"]
    assert [c["id"] for c in lab.find("", limit=10, cls="microscope")] == ["gone-01"]
    assert [c["id"] for c in lab.find("", limit=10, state="idle")] == ["thermocycler-01"]
    assert [c["id"] for c in lab.find("", limit=10, state="unreachable")] == ["gone-01"]
    assert lab.find("", limit=10, state="fault") == []



def test_the_command_line_says_the_next_steps_as_commands():
    import subprocess
    env = {**os.environ, "PYTHONPATH": str(REPO)}
    cli = [sys.executable, "-m", "openmhp.cli", TC]
    r = subprocess.run([*cli, "ping"], capture_output=True, text=True, env=env, timeout=120)
    assert r.returncode == 0 and json.loads(r.stdout)["state"] == "idle", r.stderr
    assert f"next: mhp {TC} describe summary" in r.stderr, r.stderr
    r = subprocess.run([*cli, "write", "target_temperature", "500"], capture_output=True, text=True, env=env, timeout=120)
    err = json.loads(r.stdout)["error"]
    assert r.returncode == 1 and err["code"] == D.LimitViolation.code and err["effect"] == "none", r.stdout
    assert f"next: mhp {TC} limits" in r.stderr, r.stderr

if __name__ == "__main__":
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn(); print("ok  ", name, flush=True)
            except Exception as e:                               # noqa: BLE001
                failed += 1
                import traceback; traceback.print_exc()
                print("FAIL", name, e, flush=True)
    print(f"{failed} failed")
    sys.exit(1 if failed else 0)
