"""Materials wave D: Neware BTS 8.0 cycler (XML over TCP), Arbin MITS Pro cycler (results-folder route, template),
Gamry potentiostat (GamryCOM through pywin32), Retsch planetary mill (serial template) and an AJA / Lesker /
Moorfield sputter tool (Modbus template). No vendor library is installed: the real drivers must load (or fail
cleanly at the port), and the twins run through the same gates as the real drivers.

    PYTHONPATH=. python tests/test_packages_materials_d.py      (or: python -m pytest tests/test_packages_materials_d.py -q)
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ["OPENMHP_HOME"] = tempfile.mkdtemp(prefix="openmhp-materials-d-")
os.environ["OPENMHP_SIM_TIME_SCALE"] = "0.0005"

from openmhp.client import LocalDevice, RemoteError      # noqa: E402
from openmhp.driver import DeviceFault                   # noqa: E402
from openmhp.package import load_driver, load_package    # noqa: E402
from openmhp.validate import validate_path               # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1] / "supported-devices"
BACKEND = ["neware-battery-cycler", "arbin-battery-cycler", "gamry-potentiostat"]
DECLARATIVE = ["retsch-planetary-mill", "aja-sputter-system"]
PACKAGES = BACKEND + DECLARATIVE
STEPS = [{"mode": "cc_charge", "current_a": 0.09, "voltage_v": 4.2, "time_limit_s": 600},
         {"mode": "cc_discharge", "current_a": 0.09, "voltage_v": 3.0, "time_limit_s": 600}]


def refused(code, fn):
    try:
        fn()
        raise AssertionError(f"expected a refusal with {code}")
    except RemoteError as e:
        assert e.code == code, (e.code, str(e))
        return e


class _Broken:
    """A backend whose open() fails: what the twin looks like when the instrument is gone."""
    def open(self):
        raise DeviceFault("link down (test)")


def wait_until(fn, timeout=5.0):
    deadline = time.time() + timeout
    while not fn() and time.time() < deadline:
        time.sleep(0.01)
    assert fn(), "condition not met in time"


def twin(name):
    drv = load_driver(ROOT / name, sim=True)
    dev = LocalDevice(drv)
    assert dev.read("state") == "idle" and dev.read("busy") is False and dev.read("connected") is True, name
    assert dev.read("calibration_status") == "unknown" and dev.read("qualification_status") == "unknown"   # no record: says so
    desc = load_package(ROOT / name).descriptor
    for a in desc["actions"]:
        ex = (a.get("examples") or [{}])[0]
        if a.get("params"):
            assert ex, (name, a["name"])
        if a.get("approval") == "confirm" and a.get("params"):
            refused(-32012, lambda: dev.invoke(a["name"], **ex))
        r = dev.invoke(a["name"], dry_run=True, approved=True, **ex)
        assert r["state"] == "dryRun", (name, a["name"], r)
    refused(-32040, lambda: dev.read("no_such_signal"))
    return drv, dev, desc


def fault_on_read(dev, sig):
    assert dev.call("sim/fault", {"mode": "raise", "on": "read"})["armed"]["mode"] == "raise"
    try:
        dev.read(sig)
        raise AssertionError("the injected read fault did not fire")
    except RemoteError as e:
        assert "injected fault" in str(e), e
    if dev.read("state") != "idle":
        dev.reset()
    assert dev.read("state") == "idle" and dev.read(sig) is not None


def test_packages_validate_and_real_drivers_load():
    for name in PACKAGES:
        v = validate_path(str(ROOT / name))
        assert v["ok"], (name, v["errors"])
        assert [w for w in v["warnings"] if "no location" not in w] == [], (name, v["warnings"])
        pkg = load_package(ROOT / name)
        assert pkg.meta["driver"] == "driver.py:Device" and pkg.meta["sim"] == "sim.py:Sim"
        for rel in ("references/setup.md", "config.example.json", "config.schema.json"):
            assert (pkg.dir / rel).is_file(), (name, rel)
        assert "## First hardware test" in (pkg.dir / "references" / "setup.md").read_text()
        if name in BACKEND:
            real = LocalDevice(load_driver(ROOT / name))                 # no SDK, no config.json
            assert real.read("connected") is False, name
            action = next(a for a in real.describe("full")["actions"] if "connected" in (a.get("interlocks") or []))
            refused(-32011, lambda: real.invoke(action["name"], approved=True, **action["examples"][0]))
        else:
            src = (pkg.dir / "driver.py").read_text()
            assert ("serial_ascii import SerialAsciiDriver as Device" in src) or ("modbus import ModbusDriver" in src), name
            try:                                                           # pyserial / pymodbus absent: fail cleanly, never half-load
                dev = LocalDevice(load_driver(ROOT / name))
                assert dev.read("connected") is False
            except (ImportError, RemoteError, RuntimeError):
                pass
    for name, ref in (("retsch-planetary-mill", "protocol.md"), ("aja-sputter-system", "registers.md"),
                      ("arbin-battery-cycler", "file_formats.md"), ("neware-battery-cycler", "bts_api.md"),
                      ("gamry-potentiostat", "gamrycom.md")):
        assert "unverified" in (ROOT / name / "references" / ref).read_text().lower(), name
    for name in ("retsch-planetary-mill", "aja-sputter-system", "arbin-battery-cycler"):
        assert "template" in load_package(ROOT / name).meta["description"].lower(), name


def _break_link(drv, dev, desc):
    """An open interlock: every action here needs `connected`; break the link and the gate refuses."""
    good_hw, drv.hw, drv.make_backend = drv.hw, None, lambda: _Broken()
    assert dev.read("connected") is False
    first = next(a for a in desc["actions"] if "connected" in (a.get("interlocks") or []))
    refused(-32011, lambda: dev.invoke(first["name"], approved=True, **(first.get("examples") or [{}])[0]))
    drv.hw = good_hw
    assert dev.read("connected") is True


def test_neware_battery_cycler_twin():
    drv, dev, desc = twin("neware-battery-cycler")
    assert dev.read("channels") == [f"1-1-{n}" for n in range(1, 9)] and dev.read("channel") == "1-1-1"
    assert dev.read("channel_state") == "stop" and 3.0 <= dev.read("voltage") <= 4.2 and dev.read("current") == 0.0
    assert set(dev.read("channel_states")) == set(dev.read("channels"))
    refused(-32014, lambda: dev.write("channel", "nine"))
    refused(-32014, lambda: dev.write("channel", "1-1-9"))                     # not a listed channel
    dev.write("channel", "1-1-2")
    base = dict(approved=True, channel="1-1-2", barcode="CC-1")
    refused(-32010, lambda: dev.invoke("start_protocol", **base, steps=STEPS, cycles=5000))
    refused(-32010, lambda: dev.invoke("start_protocol", **base, steps=[{**STEPS[0], "current_a": 3}]))
    refused(-32010, lambda: dev.invoke("start_protocol", **base, steps=[{**STEPS[0], "voltage_v": 4.4}]))    # voltage_max_v
    refused(-32014, lambda: dev.invoke("start_protocol", **base, steps=[{"mode": "rest"}]))                 # rest needs a time
    refused(-32014, lambda: dev.invoke("start_protocol", **base, steps=[{"mode": "cv_charge", "voltage_v": 4.2}]))
    refused(-32014, lambda: dev.invoke("start_protocol", **base, steps=[{"mode": "cc_charge", "current_a": 0.05}]))  # no end
    found = dev.method_find("coin cell", "demo")
    assert found["choice"] == "one" and found["method"]["name"] == "coin_cell_formation"
    j = dev.invoke("start_protocol", **base, steps=STEPS, cycles=2)
    wait_until(lambda: dev.read("channel_state") == "working")
    assert dev.read("busy") is True and dev.read("current") > 0
    r = dev.wait(j, poll=0.02)
    assert r["state"] == "done" and r["resultMismatch"] is None, r
    res = r["result"]
    assert res["cycles_completed"] == 2 and res["final_state"] == "finish" and 0.014 <= res["last_capacity_ah"] <= 0.0151
    assert 3.0 <= res["final_voltage_v"] <= 3.5 and pathlib.Path(res["step_file"]).read_text().count("<step ") == 2
    assert dev.read("last_result") == res and dev.read("cycle") == 2 and dev.read("channel_state") == "finish"
    real = sys.modules[type(drv).__module__].real
    steps, cycles = real.parse_step_file(pathlib.Path(res["step_file"]).read_text())
    assert cycles == 2 and steps[0]["mode"] == "cc_charge" and steps[1]["voltage_v"] == 3.0
    # a protocol that trips the cell's protection fails the job with the partial result attached
    try:
        dev.wait(dev.invoke("start_protocol", **base, steps=[{**STEPS[0], "voltage_v": 4.32}]), poll=0.02)
        raise AssertionError("expected the protected channel to fail the job")
    except RemoteError as e:
        assert "protect" in str(e) and dev.read("state") == "fault", e
    dev.reset()
    stop = dev.wait(dev.invoke("stop_channel", channel="1-1-2"), poll=0.02)["result"]
    assert stop["channel"] == "1-1-2" and stop["channel_state"] == "protect"      # a stop does not clear the alarm
    # cancelling a running protocol sends stop to that channel
    j = dev.invoke("start_protocol", **base, steps=[{"mode": "rest", "time_limit_s": 36000}])
    wait_until(lambda: dev.read("channel_state") == "working")
    dev.cancel(j)
    assert dev.wait(j, poll=0.02)["state"] == "cancelled" and dev.read("channel_state") == "stop"
    _break_link(drv, dev, desc)
    fault_on_read(dev, "channel_state")
    dev.invoke("start_protocol", **{**base, "channel": "1-1-3"}, steps=[{"mode": "rest", "time_limit_s": 36000}])
    wait_until(lambda: drv.hw.cells["1-1-3"].status == "working")
    before = len(drv.hw.log)
    dev.estop("test")
    assert dev.read("state") == "estop" and drv.hw.log[before:].count("stop") >= 8      # every channel opened (the cancelled job may add one)
    assert all(c.status != "working" for c in drv.hw.cells.values())


def test_arbin_battery_cycler_twin():
    drv, dev, desc = twin("arbin-battery-cycler")
    assert dev.read("queue_depth") == 0 and dev.read("channel") == "1" and dev.read("channel_state") == "unknown"
    refused(-32014, lambda: dev.write("channel", "3/4"))
    dev.write("channel", "3")
    base = dict(approved=True, channel="3", barcode="CC-1", schedule="Short.sdu")
    refused(-32010, lambda: dev.invoke("start_protocol", **base, steps=STEPS, cycles=5000))
    refused(-32010, lambda: dev.invoke("start_protocol", **base, steps=[{**STEPS[0], "voltage_v": 4.31}]))
    refused(-32014, lambda: dev.invoke("start_protocol", **{**base, "schedule": "Short.xlsx"}, steps=STEPS))
    refused(-32014, lambda: dev.invoke("start_protocol", **{**base, "barcode": "../x"}, steps=STEPS))
    refused(-32014, lambda: dev.invoke("start_protocol", **base, steps=[{"mode": "rest"}]))
    assert dev.method_find("lithium-ion", "demo")["method"]["name"] == "coin_cell_formation"
    j = dev.invoke("start_protocol", **base, steps=STEPS, cycles=2)
    wait_until(lambda: dev.read("channel_state") == "running")
    assert dev.read("queue_depth") == 1 and dev.read("busy") is True
    r = dev.wait(j, poll=0.02)
    assert r["state"] == "done" and r["resultMismatch"] is None, r
    res = r["result"]
    assert res["cycles_completed"] == 2 and res["points"] == 240 and 0.014 <= res["last_capacity_ah"] <= 0.0151
    assert res["test_time_s"] == 2400.0 and 3.0 <= res["final_voltage_v"] <= 3.5 and res["file"].endswith("CC-1_mhp_" + j["id"] + ".csv")
    head = pathlib.Path(res["file"]).read_text().splitlines()[0]
    assert head.startswith("Data_Point,Test_Time(s),Step_Time(s),Step_Index,Cycle_Index,Current(A),Voltage(V),Charge_Capacity(Ah),Discharge_Capacity(Ah)")
    assert dev.read("queue_depth") == 0 and dev.read("channel_state") == "unknown" and dev.read("last_result") == res
    real = sys.modules[type(drv).__module__].real
    parsed = real.parse_results("junk line\nTest_Time(s),Cycle_Index,Current(A),Voltage(V),Discharge_Capacity(Ah)\n10,1,-0.1,3.5,0.001\n20,1,-0.1,3.4,0.002\n")
    assert parsed == {"points": 2, "cycles_completed": 1, "last_capacity_ah": 0.002, "final_voltage_v": 3.4, "test_time_s": 20.0}
    # nobody at the console: the request waits, a cancel withdraws it
    drv.hw.hold = True
    j = dev.invoke("start_protocol", **base, steps=STEPS)
    wait_until(lambda: dev.read("queue_depth") == 1)
    dev.cancel(j)
    assert dev.wait(j, poll=0.02)["state"] == "cancelled" and dev.read("queue_depth") == 0
    # the share goes away: connected reads false and the interlock refuses
    drv.hw.folders_ok = False
    assert dev.read("connected") is False
    refused(-32011, lambda: dev.invoke("start_protocol", **base, steps=STEPS))
    drv.hw.folders_ok = True
    fault_on_read(dev, "queue_depth")
    # estop: false, so a stop request withdraws the waiting requests and latches without claiming a hardware stop
    j = dev.invoke("start_protocol", **base, steps=STEPS)
    wait_until(lambda: dev.read("queue_depth") == 1)
    r = dev.call("safety/estop", {})
    assert r["state"] == "estop"                          # estop: false here: the stop withdraws the queue, nothing reaches hardware
    assert dev.read("state") == "estop" and drv.hw.queue_depth() == 0 and drv.hw.log[-1].startswith("withdraw ['mhp_")
    try:
        assert dev.wait(j, poll=0.02)["state"] in ("cancelled", "failed")
    except RemoteError as e:
        assert "stopped" in str(e), e


def test_gamry_potentiostat_twin():
    drv, dev, desc = twin("gamry-potentiostat")
    assert dev.read("device") == "IFC1010-SIM01" and dev.read("cell_on") is False and dev.read("running") is False
    refused(-32010, lambda: dev.invoke("ca", e_V=3.0, duration_s=1))
    refused(-32010, lambda: dev.invoke("ca", e_V=0.5, duration_s=7200))
    refused(-32014, lambda: dev.invoke("cv", e_init_V=0.0, e_vertex1_V=0.5, e_vertex2_V=0.5))
    refused(-32010, lambda: dev.invoke("cv", e_init_V=0.0, e_vertex1_V=0.5, e_vertex2_V=-0.5, e_final_V=1.0))
    refused(-32014, lambda: dev.invoke("eis", f_start_Hz=1, f_end_Hz=1000))
    refused(-32010, lambda: dev.invoke("eis", f_start_Hz=1000000, f_end_Hz=0.01, points_per_decade=20))   # max_eis_points
    refused(-32012, lambda: dev.write("output_enabled", True))                                          # a person confirms
    ocp = dev.wait(dev.invoke("ocp", duration_s=10, sample_s=0.5), poll=0.02)
    assert ocp["state"] == "done" and ocp["resultMismatch"] is None
    assert ocp["result"]["points"] == 20 and ocp["result"]["i_final_A"] is None and abs(ocp["result"]["e_final_V"] - 0.012) < 0.002
    assert "cell on" not in drv.hw.log                                                                 # OCP leaves the cell off
    ca = dev.wait(dev.invoke("ca", e_V=0.5, duration_s=10, sample_s=0.1), poll=0.02)["result"]
    assert ca["points"] == 101 and abs(ca["i_final_A"] - (0.5 - 0.012) / 2200) < 2e-6 and ca["e_final_V"] == 0.5
    assert drv.hw.log[-3:] == ["cell on", "run chrono", "cell off"] and dev.read("cell_on") is False
    with open(ca["file"]) as f:
        assert f.readline().strip() == "t_s,e_V,i_A" and len(f.readlines()) == 101
    cv = dev.wait(dev.invoke("cv", e_init_V=0.0, e_vertex1_V=0.6, e_vertex2_V=-0.2, cycles=2), poll=0.02)["result"]
    assert cv["points"] == 1601 and cv["duration_s"] == 32.0 and abs(cv["e_final_V"]) < 1e-9
    eis = dev.wait(dev.invoke("eis", f_start_Hz=100000, f_end_Hz=1, points_per_decade=5), poll=0.02)["result"]
    assert eis["points"] == 26 and abs(eis["r_hf_ohm"] - 200) < 5 and abs(eis["z_mod_lf_ohm"] - 2140) < 40
    with open(eis["file"]) as f:
        assert f.readline().strip() == "f_Hz,z_real_ohm,z_imag_ohm,z_mod_ohm,z_phase_deg"
    assert dev.read("last_result") == eis
    # cancelling a running technique turns the cell off
    job = dev.invoke("ca", e_V=0.3, duration_s=3600)
    wait_until(lambda: dev.read("running"))
    dev.cancel(job)
    assert dev.wait(job, poll=0.02)["state"] == "cancelled" and dev.read("cell_on") is False and drv.hw.log[-1] == "cell off"
    _break_link(drv, dev, desc)
    fault_on_read(dev, "device")
    dev.call("settings/write", {"name": "output_enabled", "value": True, "approved": True})
    assert dev.read("cell_on") is True and drv.hw.log[-1] == "cell on"
    hw = drv.hw                                                 # the e-stop closes and drops the backend
    dev.estop("test")
    assert dev.read("state") == "estop" and dev.read("cell_on") is False and hw.log[-2:] == ["cell off", "close"]


def test_retsch_planetary_mill_twin():
    drv, dev, desc = twin("retsch-planetary-mill")
    assert dev.read("lid_closed") is True and dev.read("robot_access_ready") is False and dev.read("running") is False
    assert dev.read("speed") == 0 and dev.read("time_remaining") == 0
    refused(-32010, lambda: dev.write("speed_setpoint", 900))
    refused(-32014, lambda: dev.write("speed_setpoint", 300.5))
    refused(-32010, lambda: dev.invoke("run", approved=True, speed=50, duration_s=60))
    dev.write("speed_setpoint", 250)
    assert dev.read("speed_setpoint_actual") == 250 and drv.link.sent[-2:] == ["SPEED 250", "SPEEDSP?"]
    r = dev.wait(dev.invoke("run", approved=True, speed=400, duration_s=600), poll=0.02)
    assert r["state"] == "done" and r["resultMismatch"] is None and r["result"] == {"replies": ["OK", "OK", "OK"]}
    assert drv.link.sent[-3:] == ["SPEED 400", "TIME 600", "START"]
    wait_until(lambda: dev.read("speed") >= 399)
    assert dev.read("running") is True and 0 < dev.read("time_remaining") <= 600
    drv.link.lid_open = True                                   # the lock holds while the sun wheel turns
    assert dev.read("lid_closed") is True
    assert dev.wait(dev.invoke("stop"), poll=0.02)["result"] == {"replies": ["OK"]}
    wait_until(lambda: dev.read("speed") == 0)
    assert dev.read("running") is False
    drv.link.lid_open = True
    assert dev.read("lid_closed") is False and dev.read("robot_access_ready") is True
    refused(-32011, lambda: dev.invoke("run", approved=True, speed=400, duration_s=60))
    drv.link.lid_open = False
    fault_on_read(dev, "speed")
    dev.wait(dev.invoke("run", approved=True, speed=300, duration_s=600), poll=0.02)
    wait_until(lambda: dev.read("running"))
    dev.estop("test")
    assert dev.read("state") == "estop" and drv.link.sent[-1] == "STOP"
    wait_until(lambda: (drv.link._tick(), drv.link.speed == 0)[1])          # the drive brakes to standstill


def test_aja_sputter_system_twin():
    drv, dev, desc = twin("aja-sputter-system")
    plc = drv.link
    assert dev.read("base_pressure") < 5e-6 and dev.read("base_pressure_ok") is True and dev.read("door_closed") is True
    assert dev.read("water_flow_ok") is True and dev.read("plasma_on") is False and dev.read("shutter_open") is False
    refused(-32010, lambda: dev.call("settings/write", {"name": "power_setpoint", "value": 1000, "approved": True}))
    refused(-32012, lambda: dev.write("power_setpoint", 100))
    refused(-32014, lambda: dev.write("gas_flow_setpoint", 20.05))                     # off the 0.1 sccm grid
    refused(-32010, lambda: dev.invoke("deposit", approved=True, power_w=100, duration_s=600, rate_nm_per_min=8.5, gas_flow_ml_min=500))
    dev.write("gas_flow_setpoint", 20)
    assert dev.read("gas_flow_setpoint") == 20.0 and plc.log[-1][:2] == ("holding", 204)
    wait_until(lambda: dev.read("process_pressure") > 3e-3)
    dev.write("rotation_on", True)
    assert dev.read("rotation_on") is True and plc.log[-1] == ("coil", 12, [1])
    # the door opens: the interlock refuses a deposition
    plc.discrete[0] = 0
    assert dev.read("door_closed") is False
    refused(-32011, lambda: dev.invoke("deposit", approved=True, power_w=100, duration_s=600, rate_nm_per_min=8.5))
    plc.discrete[0] = 1
    j = dev.invoke("deposit", approved=True, gas_flow_ml_min=20, power_w=100, presputter_s=60, duration_s=600, rate_nm_per_min=8.5)
    wait_until(lambda: dev.read("plasma_on"))
    wait_until(lambda: dev.read("shutter_open"), timeout=10)
    assert dev.read("power") == 100.0 and dev.read("busy") is True
    r = dev.wait(j, poll=0.02)
    assert r["state"] == "done" and r["resultMismatch"] is None, r
    res = r["result"]
    assert res["steps"] == 7 and res["power_w"] == 100.0 and abs(res["thickness_estimate_nm"] - 85) < 4 and abs(res["shutter_open_s"] - 600) < 25
    assert 3e-3 < res["process_pressure_mbar"] < 1e-2 and abs(plc.thickness_nm - 85) < 5
    assert dev.read("shutter_open") is False and dev.read("plasma_on") is False and dev.read("power_setpoint") == 0.0
    # no gas: the plasma cannot strike and the job fails without opening the shutter
    dev.write("gas_flow_setpoint", 0)
    try:
        dev.wait(dev.invoke("deposit", approved=True, gas_flow_ml_min=1, power_w=100, duration_s=60, rate_nm_per_min=8.5, ignition_timeout_s=5), poll=0.02)
        raise AssertionError("expected the failed ignition to fail the job")
    except RemoteError as e:
        assert "did not strike" in str(e) and ("coil", 10, [1]) not in plc.log[-6:], e
    dev.reset()
    # cancelling mid-film closes the shutter and turns the supply off
    j = dev.invoke("deposit", approved=True, power_w=100, presputter_s=0, duration_s=7200, rate_nm_per_min=8.5)
    wait_until(lambda: dev.read("shutter_open"), timeout=10)
    dev.cancel(j)
    assert dev.wait(j, poll=0.02)["state"] == "cancelled" and dev.read("shutter_open") is False and dev.read("plasma_on") is False
    # venting raises the pressure and clears the base-pressure permissive
    dev.wait(dev.invoke("vent", approved=True), poll=0.02)
    wait_until(lambda: dev.read("base_pressure") > 1.0, timeout=10)
    assert dev.read("base_pressure_ok") is False
    refused(-32011, lambda: dev.invoke("deposit", approved=True, power_w=100, duration_s=60, rate_nm_per_min=8.5))
    assert dev.wait(dev.invoke("pump_down"), poll=0.02)["result"] == {"steps": 1} and dev.read("pumping") is True
    fault_on_read(dev, "base_pressure")
    dev.call("settings/write", {"name": "heater_on", "value": True, "approved": True})
    before = len(plc.log)
    dev.estop("test")
    assert dev.read("state") == "estop"
    assert [e[:2] for e in plc.log[before:]] == [("coil", 10), ("coil", 11), ("holding", 200), ("coil", 13)]
    assert dev.read("heater_on") is False and dev.read("power_setpoint") == 0.0


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
