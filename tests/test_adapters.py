"""Adapter tests with injected fakes: no vendor libraries, no hardware.

    PYTHONPATH=. python -m pytest tests -q      (or: python tests/test_adapters.py)
"""
import asyncio
import sys
import time
import types

sys.path.insert(0, ".")

from openmhp.adapters import Action, BoundDriver, Setting, Signal          # noqa: E402
from openmhp.adapters.madsci import madsci_node                            # noqa: E402
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


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok ", name)
