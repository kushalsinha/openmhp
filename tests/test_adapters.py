"""Adapter tests with injected fakes: no vendor libraries, no hardware.

    PYTHONPATH=. python -m pytest tests -q      (or: python tests/test_adapters.py)
"""
import asyncio
import json
import sys
import time
import types

sys.path.insert(0, ".")

from openmhp.adapters import Action, BoundDriver, Setting, Signal          # noqa: E402
from openmhp.adapters.madsci import madsci_node                            # noqa: E402
from openmhp.adapters.mqtt import mqtt_device                              # noqa: E402
from openmhp.adapters.opcua import opcua_device                            # noqa: E402
from openmhp.adapters.pylabrobot import plr_device                         # noqa: E402
from openmhp.adapters.sila2 import sila_device                             # noqa: E402
from openmhp.client import LocalDevice, RemoteError                        # noqa: E402
from openmhp.directory import Directory                                    # noqa: E402


# ---------------------------------------------------------------- base ---- #
def test_bound_driver_gates_and_jobs():
    plc = {"pv": 25.0, "sp": 25.0, "running": False}
    drv = BoundDriver(
        device={"id": "hp-01", "class": "hotplate", "notes": "Fume hood 2."},
        signals=[Signal("plate_temperature", read=lambda: plc["pv"], unit="degC")],
        settings=[Setting("target_temperature", write=lambda v: plc.__setitem__("sp", v),
                          limits={"min": 20, "max": 300}, unit="degC")],
        actions=[Action("shutdown", run=lambda job, p: plc.__setitem__("running", False), approval="confirm")],
        estop=lambda: plc.__setitem__("running", False),
    )
    d = LocalDevice(drv)
    assert d.read("plate_temperature") == 25.0
    d.write("target_temperature", 150); assert plc["sp"] == 150
    try:
        d.write("target_temperature", 500); assert False
    except RemoteError as e:
        assert e.code == -32010
    try:
        d.invoke("shutdown"); assert False
    except RemoteError as e:
        assert e.code == -32012
    assert d.wait(d.invoke("shutdown", approved=True))["state"] == "done"
    assert drv.descriptor["safety"]["estop"] is True
    assert d.call("device/describe", {"detail": "card"})["settings"] == ["target_temperature"]


# --------------------------------------------------------------- opcua ---- #
class _FakeNode:
    store = {}
    calls = []
    def __init__(self, nid): self.nid = nid
    def get_value(self): return _FakeNode.store.get(self.nid, 0)
    def set_value(self, v): _FakeNode.store[self.nid] = v
    def call_method(self, m, *a): _FakeNode.calls.append((self.nid, m, a)); return "ok"


class _FakeOpc:
    def get_node(self, nid): return _FakeNode(nid)


def test_opcua_adapter():
    _FakeNode.store.update({"ns=2;s=PV": 812.5, "ns=2;s=Door": True})
    drv = opcua_device(device={"id": "furnace-02", "class": "oven"}, client=_FakeOpc(),
                       signals={"zone1_temperature": ("ns=2;s=PV", "degC"), "door_closed": ("ns=2;s=Door", "boolean")},
                       settings={"zone1_setpoint": ("ns=2;s=SP", {"min": 20, "max": 1400}, "degC")},
                       actions={"start": ("ns=2;s=F", "ns=2;s=F.Start", {"interlocks": ["door_closed"], "params": {"program": "int"}})},
                       estop=("ns=2;s=F", "ns=2;s=F.Abort"))
    d = LocalDevice(drv)
    assert d.read("zone1_temperature") == 812.5
    d.write("zone1_setpoint", 900); assert _FakeNode.store["ns=2;s=SP"] == 900
    assert d.wait(d.invoke("start", program=3))["result"] == "ok"
    assert _FakeNode.calls[-1] == ("ns=2;s=F", "ns=2;s=F.Start", (3,))
    _FakeNode.store["ns=2;s=Door"] = False
    try:
        d.invoke("start", program=3); assert False
    except RemoteError as e:
        assert e.code == -32011
    d.estop(); assert _FakeNode.calls[-1][1] == "ns=2;s=F.Abort"


# --------------------------------------------------------------- sila2 ---- #
class _ObsCmd:
    def __init__(self): self.t0 = time.time()
    @property
    def done(self): return time.time() - self.t0 > 0.15
    @property
    def progress(self): return min(1.0, (time.time() - self.t0) / 0.15)
    def get_responses(self): return types.SimpleNamespace(Position=[1, 2, 3])


class _FakeSila:
    class RobotController:
        class Position:
            @staticmethod
            def get(): return [0, 0, 0]
        @staticmethod
        def SetSpeed(Speed): _FakeSila.speed = Speed
        @staticmethod
        def MoveTo(X, Y, Z): return _ObsCmd()
        @staticmethod
        def EmergencyStop(): _FakeSila.stopped = True


def test_sila2_adapter():
    drv = sila_device(device={"id": "arm-01", "class": "robot_arm"}, client=_FakeSila(),
                      signals={"position": "RobotController.Position"},
                      settings={"speed": ("RobotController.SetSpeed.Speed", {"min": 1, "max": 100})},
                      actions={"move_to": ("RobotController.MoveTo", {"observable": True})},
                      estop="RobotController.EmergencyStop")
    d = LocalDevice(drv)
    assert d.read("position") == [0, 0, 0]
    d.write("speed", 40); assert _FakeSila.speed == 40
    j = d.wait(d.invoke("move_to", X=1, Y=2, Z=3))
    assert j["result"] == {"Position": [1, 2, 3]} and j["progress"] == 1.0
    d.estop(); assert _FakeSila.stopped


# -------------------------------------------------------------- madsci ---- #
class _FakeMadsci:
    def __init__(self):
        self.polls = 0; self.admin = []
    def get(self, path):
        if path == "/info":
            return {"node_id": "n1", "node_type": "pf400", "actions": {
                "transfer": {"description": "Move a plate", "args": {"source": {"type": "str"}, "target": {"type": "str"}}}}}
        if path == "/state":  return {"gripper": "open", "location": "home"}
        if path == "/status": return {"busy": False, "errored": False}
        if path.startswith("/action/"):
            self.polls += 1
            return {"action_id": "a1", "status": "succeeded" if self.polls > 1 else "running", "data": {"ok": 1}}
    def post(self, path, body=None):
        if path == "/action": return {"action_id": "a1", "status": "running"}
        self.admin.append(path); return {}


def test_madsci_adapter():
    http = _FakeMadsci()
    drv = madsci_node("http://fake", device={"id": "pf400-01", "class": "robot_arm"}, http=http, poll_s=0.01)
    d = LocalDevice(drv)
    assert d.read("gripper") == "open"
    spec = d.call("device/describe", {"select": {"actions": ["transfer"]}})["actions"][0]
    assert spec["params"] == {"source": "str", "target": "str"} and spec["notes"] == "Move a plate"
    assert d.wait(d.invoke("transfer", source="a", target="b"))["result"]["status"] == "succeeded"
    d.estop(); assert http.admin == ["/admin/safety_stop"]


# ---------------------------------------------------------- pylabrobot ---- #
class _FakeLH:
    setup_finished = False
    def __init__(self): self.log = []
    async def setup(self): self.setup_finished = True
    async def stop(self): self.log.append("stop")
    async def aspirate(self, resources: list, vols: list, flow_rates=None):
        """Aspirate liquid from the specified wells."""
        await asyncio.sleep(0.01); self.log.append(("asp", vols)); return None
    async def dispense(self, resources: list, vols: list): self.log.append(("disp", vols))
    def not_a_coroutine(self): pass


def test_pylabrobot_adapter():
    lh = _FakeLH()
    drv = plr_device(lh, device={"id": "star-01", "class": "liquid_handler"}, approval={"dispense": "confirm"})
    d = LocalDevice(drv)
    assert d.read("setup_finished") is True
    names = d.call("device/describe", {"detail": "card"})["actions"]
    assert names == ["aspirate", "dispense"]
    spec = d.call("device/describe", {"select": {"actions": ["aspirate"]}})["actions"][0]
    assert spec["params"]["vols"] == "list" and spec["notes"].startswith("Aspirate")
    assert d.wait(d.invoke("aspirate", resources=["A1"], vols=[50]))["state"] == "done"
    try:
        d.invoke("dispense", resources=["A1"], vols=[50]); assert False
    except RemoteError as e:
        assert e.code == -32012
    d.estop(); assert lh.log[-1] == "stop"


# ------------------------------------------------------ directory: live ---- #
def test_directory_live_state():
    from openmhp.devices.sim_thermocycler import SimThermocycler
    a, b = SimThermocycler(), SimThermocycler()
    b.descriptor = {**b.descriptor, "device": {**b.descriptor["device"], "id": "thermocycler-02"}}
    b._index = a._index
    d = Directory(state_ttl=0)
    d.add_driver(a, "local:a"); d.add_driver(b, "local:b")
    assert {r["id"] for r in d.search("pcr", state="idle")} == {"thermocycler-01", "thermocycler-02"}
    b.state = "busy"                                   # changes after indexing
    assert [r["id"] for r in d.search("pcr", state="idle")] == ["thermocycler-01"]
    assert d.rpc("directory/get", {"id": "thermocycler-02"})["state"] == "busy"
    d.add({"id": "ghost-01", "class": "oven", "notes": "pcr oven"}, "http://127.0.0.1:1")   # nobody listening
    ghost = [r for r in d.search("pcr oven") if r["id"] == "ghost-01"][0]
    assert ghost["state"] == "unreachable"


# ------------------------------------------------------- device packages ---- #
def test_device_package_three_levels():
    import pathlib
    from openmhp.package import load_package
    from openmhp.client import connect
    pkg_dir = pathlib.Path("openmhp/devices/thermocycler-01")
    pkg = load_package(pkg_dir)
    assert pkg.meta["id"] == "thermocycler-01" and "PCR" in pkg.meta["description"]
    assert pkg.instructions.startswith("# Thermocycler-01")
    assert "references/protocols.md" in pkg.resources and "scripts/pcr.py" in pkg.resources
    d = connect(f"pkg:{pkg_dir}")
    card = d.call("device/describe", {"detail": "card"})          # level 1
    assert card["description"] == pkg.meta["description"] and "notes" not in card
    summ = d.call("device/describe", {"detail": "summary"})       # level 2
    assert "Operating procedure" in summ["instructions"] and summ["resources"] == pkg.resources
    full = d.call("device/describe", {"select": {"actions": ["run_protocol"]}})   # level 3, spec
    assert full["actions"][0]["examples"][0]["cycles"] == 30
    assert "Taq" in d.resource("references/protocols.md")           # level 3, reference
    assert d.info["capabilities"]["resources"] is True
    try:
        d.resource("../../driver.py"); assert False
    except RemoteError as e:
        assert e.code == -32040                                     # no escaping the package
    assert d.wait(d.invoke("run_protocol", steps=[{"temp": 95, "hold_s": 0}], cycles=1))["state"] == "done"


# ------------------------------------------------ fleet, scan, mhp_lab ---- #
def test_fleet_scan_and_lab_tool(tmp_home=None):
    import os, pathlib, tempfile, threading, json
    tmp_home = tmp_home or tempfile.mkdtemp()
    os.environ["OPENMHP_HOME"] = tmp_home
    import importlib
    import openmhp.fleet as fleet_mod
    importlib.reload(fleet_mod)
    from openmhp.fleet import Fleet
    from openmhp.mcp_bridge import Bridge
    from openmhp.transport import serve_http
    from openmhp.devices.sim_thermocycler import SimThermocycler
    # a device somewhere "on the network"
    threading.Thread(target=serve_http, args=(SimThermocycler(),), kwargs={"port": 18933}, daemon=True).start()
    time.sleep(0.5)
    fleet = Fleet()
    assert fleet.list() == []
    found = fleet.scan(ports=[18933])
    assert [f["id"] for f in found] == ["thermocycler-01"] and found[0]["target"] == "http://127.0.0.1:18933"
    bridge = Bridge(fleet=fleet)
    added = bridge.call_tool("mhp_lab", {"op": "add", "target": found[0]["target"]})["added"]
    assert added["id"] == "thermocycler-01"
    assert bridge.call_tool("mhp_find", {"query": "pcr"})[0]["id"] == "thermocycler-01"
    assert fleet.scan(ports=[18933]) == []                              # already in the lab
    assert Fleet().list()[0]["target"] == "http://127.0.0.1:18933"      # persisted
    # onboard a new instrument entirely through the tool
    r = bridge.call_tool("mhp_lab", {"op": "new", "id": "hotplate-01", "class": "hotplate", "description": "IKA hotplate in hood 2"})
    assert "created" in r
    v = bridge.call_tool("mhp_lab", {"op": "validate", "id": "hotplate-01"})
    assert not v["ok"]                                                  # template still has placeholders
    bridge.call_tool("mhp_lab", {"op": "write", "id": "hotplate-01", "files": {
        "DEVICE.md": "---\nid: hotplate-01\nclass: hotplate\nlocation: fume hood 2\ntags: [heating]\n"
                     "description: IKA C-MAG stirrer hotplate in fume hood 2. Use for heating capped flasks; not for open solvents.\n---\n"
                     "# Hotplate-01\n\nIn hood 2.\n\n## Operating procedure\n1. Check `sash_closed`.\n2. Write `target_temperature`.\n3. Invoke `shutdown` when done.\n\n"
                     "## What to watch\n- `plate_temperature`.\n" + "x" * 100,
        "descriptor.yaml": "signals:\n  - {name: plate_temperature, type: number, unit: degC}\n  - {name: sash_closed, type: boolean}\n"
                           "settings:\n  - {name: target_temperature, type: number, unit: degC, limits: {min: 20, max: 300}, interlocks: [sash_closed]}\n"
                           "actions:\n  - {name: shutdown, duration: short, approval: confirm}\nsafety: {estop: true, watchdog_s: 10}\n",
        "driver.py": "from openmhp.adapters import BoundDriver, Signal, Setting, Action\nstate={'t':25.0,'sash':True}\n"
                     "DEVICE = BoundDriver(device={}, signals=[Signal('plate_temperature', read=lambda: state['t'], unit='degC'),"
                     "Signal('sash_closed', read=lambda: state['sash'], type='boolean')],"
                     "settings=[Setting('target_temperature', write=lambda v: state.__setitem__('t', v), limits={'min':20,'max':300}, interlocks=['sash_closed'])],"
                     "actions=[Action('shutdown', run=lambda job,p: 'off', approval='confirm')], estop=lambda: None)\n"}})
    assert bridge.call_tool("mhp_lab", {"op": "validate", "id": "hotplate-01"})["ok"]
    added = bridge.call_tool("mhp_lab", {"op": "add", "target": "hotplate-01"})["added"]
    assert added["class"] == "hotplate" and added["location"] == "fume hood 2"
    assert bridge.call_tool("mhp_write", {"device": "hotplate-01", "name": "target_temperature", "value": 150})["ok"]
    try:
        bridge.call_tool("mhp_write", {"device": "hotplate-01", "name": "target_temperature", "value": 500}); assert False
    except RemoteError as e:
        assert e.code == -32010
    assert {d["id"] for d in bridge.call_tool("mhp_lab", {"op": "list"})["devices"]} == {"thermocycler-01", "hotplate-01"}
    assert len(bridge.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]) == 11


# --------------------------------------------- guided onboarding, no code ---- #
def test_onboarding_interview_writes_package():
    import os, tempfile, importlib
    os.environ["OPENMHP_HOME"] = tempfile.mkdtemp()
    import openmhp.fleet as fleet_mod; importlib.reload(fleet_mod)
    from openmhp.fleet import Fleet
    from openmhp.mcp_bridge import Bridge
    b = Bridge(fleet=Fleet())
    st = b.call_tool("mhp_lab", {"op": "status"})
    assert st["devices"] == 0 and "onboard" in st["next"]
    r = b.call_tool("mhp_lab", {"op": "onboard"})
    assert r["ask"][0]["key"] == "name" and "shape" in r["ask"][0]
    did = r["id"]
    turns = [
        {"make": "IKA", "model": "C-MAG HS 7", "nickname": "hood hotplate"},
        {"kind": "manual"},
        {"description": "Magnetic stirrer hotplate in fume hood 2. Use for heating and stirring capped flasks; not for open solvents above 60 degC."},
        {"location": "fume hood 2", "tags": ["heating", "stirring"], "class": "hotplate"},
        {"signals": [{"name": "plate temperature", "type": "number", "unit": "degC"}, {"name": "sash closed", "type": "boolean"}]},
        {"settings": [{"name": "target temperature", "unit": "degC", "min": 20, "max": 300, "approval": "auto", "notes": "above 300 the seal fails"}]},
        {"actions": [{"name": "shutdown", "duration": "short", "approval": "confirm", "interlocks": [], "notes": "plate stays hot"}]},
        {"steps": ["Check the sash is closed.", "Set the stir speed, then the temperature.", "Watch the plate temperature."], "watch": ["stir bar rattles above 800 rpm"]},
        {"estop": "press the red power switch", "watchdog_s": 30},
    ]
    for ans in turns:
        r = b.call_tool("mhp_lab", {"op": "onboard", "id": did, "answers": ans})
    assert r["progress"] == "all required answered" and r["ask"][0]["key"] in ("physical", "docs")
    r = b.call_tool("mhp_lab", {"op": "onboard", "id": did, "answers": {"skip": True}})
    assert r["validation"]["ok"], r["validation"]
    assert set(r["files"]) == {"DEVICE.md", "descriptor.yaml", "driver.py"}
    added = b.call_tool("mhp_lab", {"op": "add", "target": did})["added"]
    assert added["class"] == "hotplate" and "record" in added["actions"]
    summ = b.call_tool("mhp_describe", {"device": did})
    assert "## Operating procedure" in summ["instructions"] and "sash" in summ["instructions"]
    # manual driver: gates apply, writes become operator instructions, readings get recorded
    try:
        b.call_tool("mhp_write", {"device": did, "name": "target_temperature", "value": 500}); assert False
    except RemoteError as e:
        assert e.code == -32010
    assert b.call_tool("mhp_write", {"device": did, "name": "target_temperature", "value": 80})["ok"]
    try:                                   # no trusted confirmation channel: confirm-gated steps are unavailable
        b.call_tool("mhp_invoke", {"device": did, "name": "shutdown"}); assert False
    except RemoteError as e:
        assert e.code == -32012 and "no trusted confirmation channel" in e.message
    b.client_caps, b.send_request = {"elicitation": {}}, lambda m, p: {"action": "accept", "content": {"confirm": True}}
    j = b.call_tool("mhp_invoke", {"device": did, "name": "record", "params": {"signal": "plate_temperature", "value": 79.5}, "wait": True})
    assert j["result"]["recorded"] == {"plate_temperature": 79.5}
    assert b.call_tool("mhp_read", {"device": did, "names": ["plate_temperature"]})["values"]["plate_temperature"] == 79.5
    init = b.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})["result"]
    assert "mhp_lab op='status'" in init["instructions"] and "prompts" in init["capabilities"]
    assert [x["name"] for x in b.handle({"jsonrpc": "2.0", "id": 2, "method": "prompts/list"})["result"]["prompts"]] == ["setup-my-lab", "add-instrument", "run-experiment", "lab-status"]


def test_serial_ascii_driver():
    from openmhp.drivers.serial_ascii import SerialAsciiDriver
    from openmhp.onboarding import build_package
    from openmhp.package import parse_frontmatter
    import yaml
    files = build_package("hp-serial-01", {
        "make": "IKA", "model": "C-MAG", "kind": "serial", "port": "/dev/ttyUSB9", "baud": 9600,
        "description": "Serial hotplate used for testing the declarative driver with fake link objects only.",
        "location": "hood 2", "tags": ["heating"], "class": "hotplate",
        "signals": [{"name": "plate_temperature", "unit": "degC", "serial_read": "IN_PV_1"}, {"name": "heater_on", "type": "boolean", "serial_read": "STATUS_1"}],
        "settings": [{"name": "target_temperature", "unit": "degC", "min": 20, "max": 300, "serial_write": "OUT_SP_1 {value}"}],
        "actions": [{"name": "start", "serial_commands": ["START_1"], "interlocks": []}, {"name": "hold", "params": {"minutes": "int"}, "example": {"minutes": 5}, "serial_commands": ["HOLD {minutes}"]}],
        "steps": ["start it"], "estop": "STOP", "estop_serial": "STOP_1", "watchdog_s": 10})
    meta, _ = parse_frontmatter(files["DEVICE.md"])
    desc = yaml.safe_load(files["descriptor.yaml"]); desc["device"] = {**desc.get("device", {}), **{k: meta[k] for k in ("id", "class", "make", "model", "location", "tags", "description")}}
    assert desc["serial"]["write"] == {"target_temperature": "OUT_SP_1 {value}"} and "driver.py" in files

    class FakeLink:
        def __init__(self): self.sent = []; self.reply = b"25.4 C\r\n"
        def write(self, b): self.sent.append(b.decode().strip()); self.reply = b"ON\r\n" if "STATUS" in self.sent[-1] else b"25.4 C\r\n"
        def readline(self): return self.reply
    link = FakeLink()
    drv = type("D", (SerialAsciiDriver,), {"descriptor": desc, "link": link})()
    d = LocalDevice(drv)
    assert d.read("plate_temperature") == 25.4 and d.read("heater_on") is True
    d.write("target_temperature", 150); assert link.sent[-1] == "OUT_SP_1 150"
    assert d.wait(d.invoke("hold", minutes=5))["result"]["replies"] and link.sent[-1] == "HOLD 5"
    d.estop(); assert link.sent[-1] == "STOP_1"


def test_location_is_recorded_when_a_device_is_installed():
    """A shared package cannot know where it will stand, so the lab records that, not the package."""
    import os, tempfile, importlib
    os.environ["OPENMHP_HOME"] = tempfile.mkdtemp()
    import openmhp.fleet as fleet_mod
    importlib.reload(fleet_mod)
    from openmhp.fleet import Fleet
    from openmhp.mcp_bridge import Bridge
    from openmhp.validate import validate_path
    hotplate, centrifuge = "packages/ika-c-mag-hs7", "packages/manual-benchtop-centrifuge"

    # a distributable package is valid; its empty location is a warning, not an error
    v = validate_path(hotplate)
    assert v["ok"], v["errors"]
    assert any("no location" in w for w in v["warnings"])
    # and the warning is gone once the caller knows where the device stands
    assert not any("no location" in w for w in validate_path(hotplate, location="fume hood 2")["warnings"])

    fleet = Fleet()
    assert fleet.add(centrifuge, location="  bench 4  ")["location"] == "bench 4"    # given at install time
    assert fleet.unlocated() == []
    assert Fleet().devices["centrifuge-01"]["card"]["location"] == "bench 4"         # persisted
    assert fleet.add(hotplate, sim=True)["location"] == "simulated"                  # a twin stands nowhere
    fleet.devices.clear()

    # added without one: the lab knows it is missing and says how to fix it
    bridge = Bridge(fleet=fleet)
    added = bridge.call_tool("mhp_lab", {"op": "add", "target": centrifuge})
    assert added["added"]["location"] == "" and "op='location'" in added["note"]
    assert bridge.call_tool("mhp_lab", {"op": "status"})["without_a_location"] == ["centrifuge-01"]
    # the safety card reports the missing location as a finding, not a configuration error
    card = bridge.call_tool("mhp_lab", {"op": "safety_card", "id": "centrifuge-01"})
    assert card["ok"] and any("no location" in f["text"] for f in card["findings"])
    # recording it clears the finding, heads the card and reaches search
    assert bridge.call_tool("mhp_lab", {"op": "location", "id": "centrifuge-01", "location": "bay 3"})["location"] == "bay 3"
    card = bridge.call_tool("mhp_lab", {"op": "safety_card", "id": "centrifuge-01"})
    assert card["ok"] and not any("no location" in f["text"] for f in card["findings"])
    assert "bay 3" in card["text"].splitlines()[0]
    assert bridge.call_tool("mhp_find", {"query": "centrifuge", "location": "bay 3"})[0]["id"] == "centrifuge-01"
    for bad in ("", "   "):
        try:
            fleet.set_location("centrifuge-01", bad); assert False, "empty location accepted"
        except ValueError:
            pass


# --------------------------------------------------------------- mqtt ---- #
class _FakeMqttClient:
    """Enough of paho.mqtt.client.Client's surface for mqtt_device: subscribe/publish record what
    happened, and .deliver(topic, obj) simulates a broker message arriving on on_message."""
    def __init__(self):
        self.published: list[tuple[str, bytes, int]] = []
        self.subscriptions: list[str] = []
        self.on_message = None
        self.on_connect = None

    def subscribe(self, topic, qos=0):
        self.subscriptions.append(topic)

    def publish(self, topic, payload, qos=0, retain=False):
        self.published.append((topic, payload, qos))
        return types.SimpleNamespace()                     # no wait_for_publish: adapter skips it via hasattr

    def deliver(self, topic, obj):
        raw = obj if isinstance(obj, (bytes, str)) else json.dumps(obj)
        msg = types.SimpleNamespace(topic=topic, payload=raw.encode() if isinstance(raw, str) else raw)
        if self.on_message:
            self.on_message(self, None, msg)


def test_mqtt_adapter():
    fake = _FakeMqttClient()
    drv = mqtt_device(device={"id": "incubator-07", "class": "incubator"}, client=fake,
                      signals={"temperature": ("lab/incubator/temperature", "degC", 5),
                               "door_closed": ("lab/incubator/door", "boolean")},
                      settings={"setpoint": ("lab/incubator/cmd/setpoint", {"min": 4, "max": 55}, "degC")},
                      actions={"purge": ("lab/incubator/cmd/purge", "lab/incubator/evt/purge", {"approval": "auto"}),
                               "vent": ("lab/incubator/cmd/vent", None, {"approval": "auto"})},
                      estop=("lab/incubator/cmd/stop", None))
    d = LocalDevice(drv)
    assert "lab/incubator/temperature" in fake.subscriptions and "lab/incubator/evt/purge" in fake.subscriptions

    # a signal reads None until a message has actually arrived (never a stale guess)
    assert d.read("temperature") is None
    fake.deliver("lab/incubator/temperature", 37.2)
    assert d.read("temperature") == 37.2
    fake.deliver("lab/incubator/door", True)
    assert d.read("door_closed") is True

    # a setting publishes the value, JSON-encoded
    d.write("setpoint", 40)
    topic, payload, qos = fake.published[-1]
    assert topic == "lab/incubator/cmd/setpoint" and json.loads(payload) == 40 and qos == 1

    # an action with a reply topic: publishes, blocks on the correlated reply, then returns it
    job = d.invoke("purge")
    deadline = time.time() + 2
    corr = None
    while time.time() < deadline and corr is None:
        hits = [p for p in fake.published if p[0] == "lab/incubator/cmd/purge"]
        if hits:
            corr = json.loads(hits[-1][1])["job"]
        else:
            time.sleep(0.02)
    assert corr and d.status(job)["state"] == "running"       # still waiting: no reply yet
    fake.deliver("lab/incubator/evt/purge", {"job": corr, "status": "done", "cleared": True})
    assert d.wait(job)["result"] == {"job": corr, "status": "done", "cleared": True}

    # a failed/cancelled status on the reply maps to the matching MHP outcome
    job2 = d.invoke("purge")
    deadline = time.time() + 2
    corr2 = None
    while time.time() < deadline and corr2 is None:
        hits = [p for p in fake.published if p[0] == "lab/incubator/cmd/purge"]
        if len(hits) > 1:
            corr2 = json.loads(hits[-1][1])["job"]
        else:
            time.sleep(0.02)
    fake.deliver("lab/incubator/evt/purge", {"job": corr2, "status": "failed", "error": "valve stuck"})
    try:
        d.wait(job2); assert False
    except RemoteError as e:
        assert "valve stuck" in e.message

    d.reset()                                                  # the failed purge latched fault; verify recovery first
    # no reply_topic: fire-and-forget, returns once the broker publish is done
    j3 = d.wait(d.invoke("vent"))
    assert j3["state"] == "done" and j3["result"]["published"] is True

    # estop publishes at QoS 2
    d.estop()
    assert fake.published[-1][0] == "lab/incubator/cmd/stop" and fake.published[-1][2] == 2


# ---------------------------------------------------------------- service ---- #
def test_service_install_uninstall_status_never_touch_the_real_machine():
    """openmhp.service's install/uninstall/status, with target_path() and subprocess redirected to a
    scratch area -- this must never write to the developer's or CI machine's actual service manager."""
    import subprocess
    import tempfile
    from pathlib import Path
    from openmhp import service as svc

    scratch = Path(tempfile.mkdtemp())
    fake_target = scratch / "openmhp-node.service"
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        import types as _types
        return _types.SimpleNamespace(returncode=0, stdout="active\n", stderr="")

    orig_target, orig_run, orig_system = svc.target_path, subprocess.run, svc.platform.system
    svc.target_path = lambda: fake_target
    subprocess.run = fake_run
    svc.platform.system = lambda: "Linux"
    try:
        assert svc.status()["installed"] is False

        r = svc.install("openmhp/devices", 18990, dry_run=True)
        assert r["dry_run"] and not fake_target.exists() and "ExecStart=" in r["content"]

        r = svc.install("openmhp/devices", 18990)
        assert r["ok"] and fake_target.is_file()
        assert "18990" in fake_target.read_text() and str(Path("openmhp/devices").resolve()) in fake_target.read_text()
        assert any("daemon-reload" in " ".join(c) for c in calls) and any("enable" in " ".join(c) for c in calls)

        st = svc.status()
        assert st["installed"] and st["running"] is True

        r = svc.uninstall()
        assert r["ok"] and not fake_target.exists()
        assert svc.status()["installed"] is False
    finally:
        svc.target_path, subprocess.run, svc.platform.system = orig_target, orig_run, orig_system
        import shutil
        shutil.rmtree(scratch, ignore_errors=True)


def test_service_content_is_pure_and_platform_specific():
    """The three content generators take no OS action; each names the right entry point for its
    platform and carries the exact node command that will run at login/boot."""
    from pathlib import Path
    from openmhp import service as svc

    unit = svc.systemd_unit("/srv/instruments", 18900)
    assert "[Unit]" in unit and "ExecStart=" in unit and "openmhp.cli node" in unit and "18900" in unit

    plist = svc.launchd_plist("/srv/instruments", 18900, Path("/tmp/node.log"))
    assert "<key>Label</key><string>com.openmhp.node</string>" in plist and "RunAtLoad" in plist

    bat = svc.windows_startup_script("C:\\instruments", 18900)
    assert bat.startswith("@echo off") and "/min" in bat and "18900" in bat


def test_cli_node_serves_every_package_in_a_directory():
    """`mhp node <dir>` is the lightweight per-machine host: every package folder under `dir`,
    each on its own port from a base, one process, auto-advertised. A broken package is skipped,
    not fatal to the others."""
    import json
    import os
    import shutil
    import subprocess
    import sys
    import tempfile
    import time
    import urllib.error
    import urllib.request

    root = tempfile.mkdtemp()
    shutil.copytree("openmhp/devices/arm-01", os.path.join(root, "arm-01"))
    os.makedirs(os.path.join(root, "broken"))
    with open(os.path.join(root, "broken", "DEVICE.md"), "w") as f:
        f.write("not: [valid")

    port = 18980
    proc = subprocess.Popen([sys.executable, "-m", "openmhp.cli", "node", root, "--http", str(port)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=".")
    try:
        deadline = time.time() + 5
        last_err = None
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/mhp.json", timeout=1) as r:
                    doc = json.loads(r.read())
                assert doc["device"]["id"] == "arm-01"
                break
            except (urllib.error.URLError, ConnectionError) as e:
                last_err = e
                time.sleep(0.2)
        else:
            raise AssertionError(f"node never came up: {last_err}")
    finally:
        proc.terminate()
        _, err = proc.communicate(timeout=5)
    assert "broken" in err and "SKIPPED" in err                    # the bad package didn't take the process down
    assert f"arm-01" in err and f"http://0.0.0.0:{port}" in err
    shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok ", name)
