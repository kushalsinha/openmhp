"""The pharma small-molecule packages: OpenLab CDS and Chromeleon HPLCs, the EasyMax reactor, the KF Titrino,
the Rotavapor R-300, the Crystal16 and the Vapourtec R-Series. Twins only: the real drivers must load without
their vendor libraries and read `connected` False; the twins run through every gate."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["OPENMHP_HOME"] = tempfile.mkdtemp(prefix="openmhp-pharma-sm-")
os.environ["OPENMHP_SIM_TIME_SCALE"] = "0.0005"

from openmhp.client import LocalDevice, RemoteError            # noqa: E402
from openmhp.package import load_driver                        # noqa: E402
from openmhp.validate import validate_path                     # noqa: E402

REPO = Path(__file__).resolve().parents[1]
PACKAGES = ["agilent-openlab-hplc", "thermo-chromeleon-hplc", "mettler-easymax-reactor", "metrohm-titrino-kf",
            "buchi-rotavapor-r300", "crystal16-solubility", "vapourtec-rseries"]


def refused(code, fn):
    try:
        fn()
        raise AssertionError(f"expected refusal {code}")
    except RemoteError as e:
        assert e.code == code, (e.code, str(e))


def folder(name: str) -> str:
    return str(REPO / "supported-devices" / name)


def twin(name: str):
    drv = load_driver(folder(name), sim=True)
    # run the shipped methods from a scratch copy, so the run records land in the temp home, not in the repo
    scratch = Path(tempfile.mkdtemp(prefix=f"methods-{name}-")) / "methods"
    shutil.copytree(folder(name) + "/methods", scratch)
    drv.methods_dir = str(scratch)
    return drv, LocalDevice(drv)


def fake(drv):
    """The twin's fake instrument: the backend (or the fake serial port behind the link)."""
    hw = drv.hw
    return hw.port if hasattr(hw, "port") else hw


def offline(drv):
    """Make the twin's next backend refuse to open, so `connected` reads False and the interlock is open."""
    attr = "make_backend" if hasattr(drv, "make_backend") else "make_link"
    make = getattr(drv, attr)

    def factory():
        b = make()
        (b.port if hasattr(b, "port") else b).online = False
        return b
    setattr(drv, attr, factory)
    drv.hw = None
    if hasattr(drv, "proto"):
        drv.proto = None
    return lambda: (setattr(drv, attr, make), setattr(drv, "hw", None),
                    setattr(drv, "proto", None) if hasattr(drv, "proto") else None)


def common_checks(name: str, bounded_setting: str | None, interlocked_action: str, interlock_params: dict):
    """What every package must do: validate, load for real without the library, and run its gates on the twin."""
    v = validate_path(folder(name))
    assert v["ok"], (name, v["errors"])
    assert all("no location" in w for w in v["warnings"]), (name, v["warnings"])
    real = LocalDevice(load_driver(folder(name)))
    assert real.read("connected") is False, name
    real.close()

    drv, dev = twin(name)
    assert dev.read("state") == "idle" and dev.read("busy") is False and dev.read("connected") is True
    assert dev.read("calibration_status") == "unknown" and dev.read("qualification_status") == "unknown"
    full = dev.describe("full")
    for action in full["actions"]:
        if action.get("examples"):
            try:
                r = dev.invoke(action["name"], dry_run=True, approved=True, **action["examples"][0])
                assert r["state"] == "dryRun", (name, action["name"], r)
            except RemoteError as e:
                assert e.code == -32011, (name, action["name"], e)      # an open interlock (a stopped stirrer) is fine
    if bounded_setting:
        lim = next(s for s in full["settings"] if s["name"] == bounded_setting)["limits"]
        refused(-32010, lambda: dev.write(bounded_setting, lim["max"] + abs(lim["max"]) + 1))
    # an open interlock: the fake instrument goes away, `connected` reads False, the action is refused
    restore = offline(drv)
    assert dev.read("connected") is False
    refused(-32011, lambda: dev.invoke(interlocked_action, approved=True, **interlock_params))
    restore()
    assert dev.read("connected") is True
    # fault injection on the twin: the next read fails
    assert dev.call("sim/fault", {"mode": "raise", "on": "read"})["armed"]["mode"] == "raise"
    try:
        dev.read("connected")
        raise AssertionError("expected the injected read fault")
    except RemoteError:
        pass
    return drv, dev


def test_agilent_openlab_hplc():
    sample = {"name": "s1", "vial": "P1-A1", "injection_volume_ul": 5, "method": "Assay_C18"}
    drv, dev = common_checks("agilent-openlab-hplc", None, "run_samples", {"samples": [sample]})
    refused(-32010, lambda: dev.invoke("run_samples", samples=[{**sample, "injection_volume_ul": 500}]))
    refused(-32014, lambda: dev.invoke("run_samples", samples=[{**sample, "flow": 2}]))
    assert dev.read("robot_access_ready") is True
    r = dev.wait(dev.invoke("run_samples", samples=[sample, {**sample, "name": "s2", "injections": 2}]))["result"]
    assert r["injections"] == 3 and r["final_status"]["command"] == "accepted" and len(r["results"]) == 6
    assert {row["Vial"] for row in r["results"]} == {"P1-A1"} and Path(r["command_file"]).name.endswith(".xml")
    assert ("submit", r["sequence_name"], 2) in fake(drv).log
    # a rejected command (unknown method) fails the job with the scheduler's verdict
    try:
        dev.wait(dev.invoke("run_samples", samples=[{**sample, "method": "Nope"}]))
        raise AssertionError("expected the rejected command to fail the job")
    except RemoteError as e:
        assert "rejected" in str(e)
    dev.reset()
    assert dev.run_method("assay-c18")["state"] == "done"
    dev.estop()
    assert dev.read("state") == "estop"
    drv.close()


def test_thermo_chromeleon_hplc():
    sample = {"name": "s1", "vial": "RA1", "injection_volume_ul": 5, "method": "Assay_C18_15min"}
    drv, dev = common_checks("thermo-chromeleon-hplc", None, "run_samples", {"samples": [sample]})
    refused(-32010, lambda: dev.invoke("run_samples", samples=[{**sample, "injection_volume_ul": 500}]))
    refused(-32014, lambda: dev.invoke("run_samples", samples=[{**sample, "vial": "RA\\1"}]))
    m = dev.wait(dev.invoke("list_methods"))["result"]
    assert "Assay_C18_15min" in m["instrument_methods"]
    assert dev.read("robot_access_ready") is True
    job = dev.invoke("run_samples", samples=[sample, {**sample, "name": "s2", "injections": 2}])
    deadline = time.time() + 5
    while not dev.read("busy") and time.time() < deadline:
        time.sleep(0.01)
    assert dev.read("robot_access_ready") is False
    r = dev.wait(job)["result"]
    assert r["injections"] == 3 and len(r["results"]) == 3 and r["results"][0]["peaks"][1]["name"] == "Product"
    assert r["final_status"]["state"] == "Idle" and ("submit", r["sequence_url"]) in fake(drv).log
    assert dev.run_method("assay-c18")["state"] == "done"
    dev.estop()
    assert dev.read("state") == "estop"
    drv.close()


def test_mettler_easymax_reactor():
    drv, dev = common_checks("mettler-easymax-reactor", "tr_setpoint", "end_experiment", {})
    refused(-32014, lambda: dev.write("stirrer_setpoint", 300.5))                # off the 1 rpm grid
    refused(-32011, lambda: dev.invoke("dose", volume_ml=5, rate_ml_min=1))       # stirrer not running
    refused(-32014, lambda: dev.invoke("start_experiment", steps=[{"tr_c": 60, "tj_c": -20, "hold_min": 1}]))
    r = dev.wait(dev.invoke("start_experiment", steps=[{"tr_c": 60, "hold_min": 5, "ramp_k_min": 5, "stirrer_rpm": 400}],
                            end_tr_c=25, tolerance_k=1))["result"]
    assert r["steps"] == 1 and abs(r["final"]["tr"] - 25) <= 2 and r["final"]["stirrer_running"] is True
    assert ("write", "tr_setpoint", 60.0) in fake(drv).log
    d = dev.wait(dev.invoke("dose", volume_ml=5, rate_ml_min=1))["result"]
    assert d["dosing_total_ml"] == 5.0 and dev.read("dosing_total_ml") == 5.0
    assert dev.run_method("crystallisation-cool", timeout=60)["state"] == "done"
    dev.write("tr_setpoint", 30)
    dev.estop()
    assert dev.read("state") == "estop"
    log = fake(drv).log
    assert ("write", "stirrer_setpoint", 0.0) in log and ("call", "safe_state") in log and ("write", "thermostat_mode", 0) in log
    drv.close()


def test_metrohm_titrino_kf():
    drv, dev = common_checks("metrohm-titrino-kf", "sample_mass_g", "determine", {"method": "KF-STD", "sample_mass_g": 0.5})
    refused(-32014, lambda: dev.write("sample_mass_g", 0.50005))                  # off the 0.1 mg grid
    refused(-32014, lambda: dev.invoke("determine", method="KF-STD"))           # ppm needs a mass
    assert dev.read("water_content_ppm") is None and dev.read("titrator_status") in ("Busy", "Cond")
    c = dev.wait(dev.invoke("condition"))["result"]
    assert c["conditioned"] is True and dev.read("cell_conditioned") is True
    dev.write("sample_mass_g", 0.5)
    r = dev.wait(dev.invoke("determine", method="KF-STD"))["result"]
    assert 1100 < r["water_content_ppm"] < 1300 and r["sample_mass_g"] == 0.5 and r["titrant_ml"] > 0
    assert dev.read("water_content_ppm") == r["water_content_ppm"] and dev.read("sample_mass_g") is None
    port = fake(drv)
    assert "$L(KF-STD)" in port.log and "$G" in port.log and "$Q(R1)" in port.log
    try:
        dev.wait(dev.invoke("determine", method="NOPE", sample_mass_g=0.5))
        raise AssertionError("E1 should fail the job")
    except RemoteError as e:
        assert "E1" in str(e)
    dev.reset()
    assert dev.run_method("kf-std", timeout=60)["state"] == "done"
    job = dev.invoke("determine", method="KF-SOLID", sample_mass_g=0.2)
    deadline = time.time() + 5
    while dev.read("titrator_status") != "Busy" and time.time() < deadline:
        time.sleep(0.01)
    dev.estop()
    assert dev.read("state") == "estop" and "$S" in port.log
    try:
        dev.wait(job)
    except RemoteError:
        pass
    drv.close()


def test_buchi_rotavapor_r300():
    drv, dev = common_checks("buchi-rotavapor-r300", "bath_setpoint", "start", {})
    refused(-32012, lambda: dev.invoke("lift_down"))
    refused(-32014, lambda: dev.write("rotation_setpoint", 120.5))
    assert dev.read("lift_position") == "up" and dev.read("vacuum_mbar") > 1000 and dev.read("running") is False
    dev.write("rotation_setpoint", 120)
    dev.wait(dev.invoke("start"))
    deadline = time.time() + 5
    while dev.read("rotation_rpm") < 100 and time.time() < deadline:
        time.sleep(0.01)
    assert dev.read("running") is True and dev.read("rotation_rpm") >= 100
    dev.wait(dev.invoke("stop")); dev.wait(dev.invoke("vent"))
    r = dev.wait(dev.invoke("evaporate", bath_c=40, vacuum_mbar=450, duration_min=20))["result"]
    assert r["stopped_by"] == "time" and r["final"]["lift"] == "up" and r["final"]["running"] is False
    assert 440 <= r["final_vacuum_mbar"] <= 460
    assert dev.run_method("dcm-strip")["state"] == "done"
    dev.wait(dev.invoke("lift_down", approved=True))
    dev.estop()
    assert dev.read("state") == "estop"
    last = fake(drv).log[-1]
    assert last["globalStatus"] == {"running": False} and last["vacuum"] == {"aerateValveOpen": True} and last["lift"] == {"set": 0}
    drv.close()


def test_crystal16_solubility():
    prog = {"stirrer_rpm": 700, "cycles": 1, "steps": [{"action": "heat", "temperature_c": 60, "rate_k_min": 5},
                                                         {"action": "cool", "temperature_c": 5, "rate_k_min": 5}]}
    drv, dev = common_checks("crystal16-solubility", "stirrer_rpm", "run_program", {"program": prog, "blocks": ["A"]})
    refused(-32010, lambda: dev.invoke("run_program", program={**prog, "steps": [{"action": "heat", "temperature_c": 200, "rate_k_min": 5}]}, blocks=["A"]))
    refused(-32014, lambda: dev.invoke("run_program", program={**prog, "steps": [{"action": "heat", "temperature_c": 60}]}, blocks=["A"]))
    refused(-32010, lambda: dev.invoke("run_program", program=prog, blocks=["E"]))
    assert dev.read("block_a_temperature") is None and dev.read("stirrer_rpm") is None
    r = dev.wait(dev.invoke("run_program", program=prog, blocks=["A", "B"]))["result"]
    assert r["blocks"] == ["A", "B"] and len(r["reactors"]) == 8 and len(r["csv"]) == 2
    by = {x["reactor"]: x for x in r["reactors"]}
    assert by[4]["clear_point_c"] > by[3]["clear_point_c"] > by[2]["clear_point_c"]     # more concentrated clears hotter
    assert by[4]["cloud_point_c"] < by[4]["clear_point_c"] and by[4]["cycles"] == 1
    assert dev.read("block_a_temperature") is not None and dev.read("stirrer_rpm") == 700
    assert Path(r["program_file"]).read_text(encoding="utf-8").count("Heat to,60") == 2
    assert dev.run_method("mszw-screen", timeout=120)["state"] == "done"
    dev.estop()
    assert dev.read("state") == "estop"
    drv.close()


def test_vapourtec_rseries():
    exp = {"pump_a_ml_min": 0.5, "pump_b_ml_min": 0.5, "reactors": [{"channel": 2, "temperature_c": 120}],
           "residence_time_min": 10, "collect_ml": 15}
    drv, dev = common_checks("vapourtec-rseries", "pump_a_flow_setpoint", "stop", {})
    refused(-32012, lambda: dev.invoke("prime", pump="A"))
    refused(-32010, lambda: dev.invoke("run_experiment", **{**exp, "reactors": [{"channel": 5, "temperature_c": 50}]}))
    refused(-32014, lambda: dev.invoke("run_experiment", **{**exp, "reactors": [{"channel": 2, "temperature_c": 50}, {"channel": 2, "temperature_c": 60}]}))
    # the pressure interlock: a blocked line reads above max_pressure_bar
    fake(drv).v["system_pressure"] = 25.0
    assert dev.read("pressure_ok") is False
    refused(-32011, lambda: dev.invoke("run_experiment", **exp))
    fake(drv).v["system_pressure"] = 0.0
    r = dev.wait(dev.invoke("run_experiment", **exp))["result"]
    assert r["collected_ml"] == 15.0 and r["final"]["collection_valve"] == "waste" and abs(r["final"]["reactors"]["2"] - 120) < 3
    log = fake(drv).log
    assert ("write", "collection_valve_set", True) in log and ("write", "pump_a_flow_setpoint", 0.5) in log
    p = dev.wait(dev.invoke("prime", approved=True, pump="A"))["result"]
    assert p["volume_ml"] == 5.0
    assert dev.run_method("amide-coupling", timeout=60)["state"] == "done"
    dev.write("pump_a_flow_setpoint", 1.0)
    dev.estop()
    assert dev.read("state") == "estop"
    tail = fake(drv).log[-8:]
    assert ("write", "pump_a_flow_setpoint", 0.0) in tail and ("write", "pump_b_flow_setpoint", 0.0) in tail
    assert ("write", "collection_valve_set", False) in tail and ("call", "stop") in tail
    drv.close()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok ", name)
