"""The materials-synthesis wave A packages: Eurotherm 2400-series and Nabertherm furnaces (Modbus, from the
vendors' communications handbooks), MBRAUN glovebox (Modbus template), Mettler Quantos/XPR powder dosing
(MT-SICS, dosing commands as placeholders), Laurell and Ossila spin coaters (serial templates). For each:
the package validates with only the location warning, the real driver cannot open its link without pymodbus
or pyserial and the twin loads regardless, and the twin runs through the gates: reserved signals, every
action's first example as a dry run, one real job, an out-of-range write, an open interlock, an injected
fault, and an e-stop that reaches the fake link. Then each twin's own physics."""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["OPENMHP_HOME"] = tempfile.mkdtemp(prefix="openmhp-materials-a-")   # job records are durable (C11)
os.environ["OPENMHP_SIM_TIME_SCALE"] = "0.0005"                                # twins run their physics fast

from openmhp.client import LocalDevice, RemoteError            # noqa: E402
from openmhp.package import load_driver, load_package          # noqa: E402
from openmhp.validate import validate_path                     # noqa: E402

REPO = Path(__file__).resolve().parents[1]

# name -> (kind, a job to run, its params, the stop the e-stop must reach on the fake link)
PACKAGES = {
    "eurotherm-tube-furnace": ("modbus", "reset_program", {}, ("holding", 23, [1])),
    "nabertherm-furnace":     ("modbus", "stop_external_setpoint", {}, ("holding", 148, [2])),
    "mbraun-glovebox":        ("modbus", "antechamber_cycle", {"purges": 2}, ("coil", 1, [1])),
    "mettler-quantos-dosing": ("serial", "tare", {}, "@"),
    "laurell-spin-coater":    ("serial", "vacuum_on", {}, "STOP"),
    "ossila-spin-coater":     ("serial", "chuck_still_check", {}, "STOP"),
}
TEMPLATES = {"mbraun-glovebox", "mettler-quantos-dosing", "laurell-spin-coater", "ossila-spin-coater"}


def _folder(name: str) -> str:
    return str(REPO / "supported-devices" / name)


def _refused(code, fn):
    try:
        fn(); raise AssertionError(f"expected a refusal with {code}")
    except RemoteError as e:
        assert e.code == code, (e.code, str(e))
        return e


def _wait_until(fn, timeout=5.0):
    deadline = time.time() + timeout
    while not fn() and time.time() < deadline:
        time.sleep(0.01)
    assert fn(), "condition not met in time"


def _sent(link) -> list[str]:
    return [s.decode(errors="replace") if isinstance(s, bytes) else s for s in link.sent]


def _twin(name):
    drv = load_driver(_folder(name), sim=True)
    return drv, LocalDevice(drv)


def test_packages_validate_and_real_drivers_need_the_vendor_library():
    for name, (kind, *_rest) in PACKAGES.items():
        v = validate_path(_folder(name))
        assert v["ok"], (name, v["errors"])
        assert [w for w in v["warnings"] if "no location" not in w] == [], (name, v["warnings"])
        pkg = load_package(_folder(name))
        assert pkg.meta["driver"] == "driver.py:Device" and pkg.meta["sim"] == "sim.py:Sim"
        assert pkg.meta["class"] in ("furnace", "glovebox", "dispenser", "spin_coater"), name
        proto = "registers.md" if kind == "modbus" else ("mt-sics.md" if "quantos" in name else "serial.md")
        for rel in ("references/setup.md", f"references/{proto}", "config.example.json", "config.schema.json"):
            assert (pkg.dir / rel).is_file(), (name, rel)
        setup = (pkg.dir / "references" / "setup.md").read_text()
        assert "## First hardware test" in setup and "## Status" in setup, name
        if name in TEMPLATES:
            assert "template" in setup.lower() and "template" in pkg.meta["description"].lower(), name
            assert "unverified" in (pkg.dir / "references" / proto).read_text().lower(), name
        # the real driver opens its link in setup(); without pymodbus / pyserial the import is the first thing
        # to fail, before anything is sent anywhere, and the twin must load regardless
        try:
            drv = load_driver(_folder(name))
        except ImportError as e:
            assert ("modbus" if kind == "modbus" else "serial") in str(e), (name, e)
        except Exception as e:                                   # noqa: BLE001  library present, no such port/host
            assert type(e).__name__ in ("SerialException", "FileNotFoundError", "OSError", "RuntimeError", "ConnectionException"), (name, e)
        else:
            assert LocalDevice(drv).read("connected") is False, name
            drv.close()
        drv, dev = _twin(name)
        assert dev.read("connected") is True, name
        drv.close()


def test_twins_answer_reserved_signals_and_dry_run_every_example():
    for name in PACKAGES:
        drv, dev = _twin(name)
        assert dev.read("state") == "idle" and dev.read("busy") is False and dev.read("connected") is True, name
        assert dev.read("calibration_status") == "unknown", name            # no record yet: says so, never guesses
        assert dev.read("qualification_status") == "unknown", name
        if name == "laurell-spin-coater":                                    # the chuck vacuum gates a recipe, as on the controller
            dev.wait(dev.invoke("vacuum_on")); _wait_until(lambda: dev.read("vacuum_ok") is True)
        for a in load_package(_folder(name)).descriptor["actions"]:
            example = (a.get("examples") or [{}])[0]
            if a.get("params"):
                assert example, (name, a["name"])
            try:
                r = dev.invoke(a["name"], approved=True, dry_run=True, **example)
            except RemoteError as e:
                # an action gated on a run in progress (hold, pause, jump) is rightly refused on an idle twin
                assert e.code == -32011 and "program_running" in a.get("interlocks", []), (name, a["name"], e)
                continue
            assert r["state"] == "dryRun", (name, a["name"], r)
        _refused(-32040, lambda: dev.read("no_such_signal"))
        drv.close()


def test_twins_refuse_out_of_range_writes_and_open_interlocks():
    for name, (kind, action, params, _stop) in PACKAGES.items():
        drv, dev = _twin(name)
        desc = load_package(_folder(name)).descriptor
        s = next(s for s in desc["settings"] if isinstance(s.get("limits"), dict) and "max" in s["limits"])
        _refused(-32010, lambda: dev.call("settings/write", {"name": s["name"], "value": s["limits"]["max"] * 2 + 1, "approved": True}))
        drv.link.is_open = False                                  # the fake link reports closed: `connected` is false
        assert dev.read("connected") is False, name
        _refused(-32011, lambda: dev.invoke(action, approved=True, **params))
        drv.link.is_open = True
        drv.close()


def test_twins_run_a_job_then_fail_on_an_injected_fault():
    for name, (kind, action, params, _stop) in PACKAGES.items():
        drv, dev = _twin(name)
        r = dev.wait(dev.invoke(action, approved=True, **params), timeout=30)
        assert r["state"] == "done", (name, r)
        assert r.get("resultMismatch") is None, (name, r)
        if kind == "modbus":
            assert isinstance(r["result"]["steps"], int), (name, r["result"])
        else:
            assert isinstance(r["result"]["replies"], list), (name, r["result"])
        assert dev.read("usage_count") >= 1, name                            # counted from the device's own jobs
        assert dev.call("sim/fault", {"mode": "raise", "on": "read"})["armed"]["mode"] == "raise"
        try:
            dev.read("connected"); raise AssertionError(f"{name}: expected the injected fault")
        except RemoteError:
            pass
        dev.call("sim/fault", {"mode": None})
        drv.close()


def test_twins_estop_reaches_the_fake_link():
    for name, (kind, _action, _params, stop) in PACKAGES.items():
        drv, dev = _twin(name)
        r = dev.estop("test")
        assert dev.read("state") == "estop", name
        assert r["stopped"] is True, (name, r)
        if kind == "modbus":
            assert stop in drv.link.log, (name, drv.link.log[-3:])
        else:
            assert stop in _sent(drv.link), (name, _sent(drv.link)[-3:])
        drv.close()


def test_eurotherm_furnace_runs_a_stored_and_a_typed_program():
    drv, dev = _twin("eurotherm-tube-furnace")
    assert dev.read("temperature") == 25 and dev.read("program_status_code") == 1 and dev.read("program_running") is False
    _refused(-32012, lambda: dev.write("target_setpoint", 300))               # heats: a person confirms
    _refused(-32014, lambda: dev.call("settings/write", {"name": "target_setpoint", "value": 300.5, "approved": True}))
    dev.call("settings/write", {"name": "target_setpoint", "value": 300, "approved": True})
    assert dev.read("target_setpoint_actual") == 300 and ("holding", 2, [300]) in drv.link.log
    _wait_until(lambda: dev.read("temperature") > 100, timeout=20)             # the loop follows SP1 in Reset
    _wait_until(lambda: dev.read("temperature_setpoint") == 300)
    dev.call("settings/write", {"name": "target_setpoint", "value": 25, "approved": True})
    _refused(-32011, lambda: dev.invoke("hold_program"))                       # nothing runs yet
    _refused(-32012, lambda: dev.invoke("run_program", program=1))
    r = dev.wait(dev.invoke("run_program", approved=True, program=1))
    assert r["result"] == {"steps": 2} and drv.link.log[-2:] == [("holding", 22, [1]), ("holding", 23, [2])]
    assert dev.read("program_running") is True and dev.read("segment") == 1 and dev.read("segment_type_code") == 1
    _wait_until(lambda: dev.read("segment") == 2, timeout=20)                  # ramp done, dwell at 500
    assert dev.read("segment_target") == 500 and dev.read("segment_type_code") == 3
    dev.wait(dev.invoke("hold_program"))
    assert dev.read("program_status_code") == 4 and dev.read("program_running") is False
    dev.wait(dev.invoke("reset_program", approved=True))
    assert dev.read("program_status_code") == 1
    # a typed program is written into slot 2's blocks, then selected and run
    segs = [{"target_c": 600, "ramp_c_per_min": 10, "dwell_min": 30}, {"target_c": 30, "ramp_c_per_min": 10, "dwell_min": 0}]
    r = dev.wait(dev.invoke("run_program", approved=True, program=2, segments=segs))
    assert r["result"] == {"steps": 5 + 3 + 3 + 3 + 1 + 2, "segments_written": 4}, r["result"]   # general block, ramp, dwell, ramp, end, select, run
    base = 8328 + 136
    assert ("holding", base + 2, [1]) in drv.link.log and ("holding", base + 8, [1]) in drv.link.log
    assert ("holding", base + 9, [600]) in drv.link.log and ("holding", base + 16, [3]) in drv.link.log
    assert ("holding", base + 32, [0]) in drv.link.log and drv.link.log[-1] == ("holding", 23, [2])
    assert dev.read("program_number") == 2 and dev.read("program_running") is True
    _refused(-32014, lambda: dev.invoke("run_program", approved=True, program=3, segments=segs * 6))   # 18 rows + End > 16 segments
    # segment blocks cannot be written while a program runs: the twin refuses like the controller
    try:
        dev.wait(dev.invoke("run_program", approved=True, program=2, segments=segs)); raise AssertionError("expected a failed job")
    except RemoteError as e:
        assert "while the program runs" in str(e)
    dev.estop()
    assert drv.link.log[-3:] == [("holding", 23, [1]), ("holding", 273, [1]), ("holding", 3, [0])]
    assert dev.read("program_running") is False and dev.read("manual_mode") is True
    drv.close()


def test_nabertherm_furnace_transfers_a_program_and_runs_external_setpoint():
    drv, dev = _twin("nabertherm-furnace")
    assert dev.read("temperature") == 25.0 and dev.read("status_code") == 0 and dev.read("controller_type_code") == 4
    assert dev.read("serial_number") == "N22080075L1" and dev.read("max_temperature") == 1300.0
    assert dev.read("temperature_unit_code") == 0 and dev.read("program_transferred") is False
    _refused(-32011, lambda: dev.invoke("pause_program"))                     # nothing runs
    _refused(-32014, lambda: dev.invoke("run_program", approved=True))        # neither program nor segments
    _refused(-32014, lambda: dev.invoke("run_program", approved=True, program=2, segments=[{"target_c": 100, "ramp_c_per_min": 5, "dwell_min": 1}]))
    r = dev.wait(dev.invoke("run_program", approved=True, program=2))
    assert r["result"] == {"steps": 3} and drv.link.log[-3:] == [("holding", 149, [2]), ("holding", 148, [1]), ("holding", 148, [0])]
    assert dev.read("program_running") is True and dev.read("program_number") == 2 and dev.read("segment") == 1
    _wait_until(lambda: dev.read("temperature") > 100, timeout=20)
    assert dev.read("output_power") > 0 and dev.read("temperature_setpoint") > 100
    dev.wait(dev.invoke("pause_program"))
    assert dev.read("status_code") == 3
    _refused(-32012, lambda: dev.invoke("stop_program"))
    dev.wait(dev.invoke("stop_program", approved=True))
    assert dev.read("status_code") == 0 and dev.read("program_running") is False
    # a typed program: unrolled into ramp + dwell rows, released, acknowledged, started as program 51
    segs = [{"target_c": 650, "ramp_c_per_min": 5, "dwell_min": 60}, {"target_c": 300, "ramp_c_per_min": 0, "dwell_min": 0}]
    r = dev.wait(dev.invoke("run_program", approved=True, segments=segs))
    assert r["result"]["segments_written"] == 3 and r["result"]["steps"] == 3 + 12 + 1 + 3, r["result"]
    log = drv.link.log
    assert ("holding", 402, [3]) in log and ("holding", 200, [650]) in log and ("holding", 240, [300]) in log
    assert ("holding", 360, [2]) in log and ("holding", 241, [60]) in log and ("holding", 361, [0]) in log
    assert ("holding", 202, [300]) in log and ("holding", 242, [0]) in log and ("holding", 403, [1]) in log
    assert log[-3:] == [("holding", 403, [0]), ("holding", 148, [1]), ("holding", 148, [0])]
    assert dev.read("program_number") == 51 and dev.read("program_transferred") is True and dev.read("program_running") is True
    dev.wait(dev.invoke("segment_jump", approved=True, offset=1))
    assert ("holding", 150, [1]) in log and log[-1] == ("holding", 150, [0])
    dev.wait(dev.invoke("stop_program", approved=True))
    # external setpoint control: confirmed writes, status 7, the furnace follows register 406
    _refused(-32012, lambda: dev.write("external_setpoint", 400))
    _refused(-32010, lambda: dev.call("settings/write", {"name": "external_setpoint", "value": 1400, "approved": True}))
    dev.call("settings/write", {"name": "external_setpoint", "value": 400, "approved": True})
    dev.wait(dev.invoke("start_external_setpoint", approved=True))
    assert dev.read("status_code") == 7
    _wait_until(lambda: dev.read("temperature_setpoint") == 400.0)
    dev.estop()
    assert log[-2:] == [("holding", 148, [2]), ("holding", 405, [0])] and dev.read("status_code") == 0
    drv.close()


def test_mbraun_glovebox_cycles_the_antechamber_and_interlocks_the_doors():
    drv, dev = _twin("mbraun-glovebox")
    assert dev.read("o2_ppm") < 1 and dev.read("h2o_ppm") < 1 and abs(dev.read("box_pressure") - 2.0) < 1.5
    assert dev.read("blower_on") is True and dev.read("antechamber_state") == "idle" and dev.read("purge_state") == "off"
    assert dev.read("inner_door_closed") is True and dev.read("robot_access_ready") is False
    _refused(-32010, lambda: dev.write("box_pressure_setpoint", 20))
    _refused(-32014, lambda: dev.write("box_pressure_setpoint", 3.3))        # off the 0.5 grid
    dev.write("box_pressure_setpoint", 4.0)
    _wait_until(lambda: abs(dev.read("box_pressure") - 4.0) < 1.5)
    r = dev.wait(dev.invoke("antechamber_cycle", purges=2))
    assert r["result"] == {"steps": 2} and ("holding", 22, [2]) in drv.link.log and ("coil", 0, [1]) in drv.link.log
    assert dev.read("antechamber_state") == "evacuating" and dev.read("antechamber_cycle_active") is True
    assert dev.read("antechamber_idle") is False
    _refused(-32011, lambda: dev.invoke("release_inner_door"))                 # a cycle runs
    _refused(-32011, lambda: dev.invoke("antechamber_cycle", purges=1))
    _wait_until(lambda: dev.read("antechamber_pressure") < 5, timeout=20)
    _wait_until(lambda: dev.read("antechamber_state") == "refilling", timeout=20)
    _wait_until(lambda: dev.read("antechamber_state") == "idle", timeout=40)
    assert dev.read("antechamber_pressure") > 990
    # doors: each release is interlocked on the other door
    drv.link.discrete[2] = 0                                                   # outer door opened by a person
    assert dev.read("outer_door_closed") is False
    _refused(-32011, lambda: dev.invoke("release_inner_door"))
    _refused(-32011, lambda: dev.invoke("antechamber_cycle", purges=1))
    drv.link.discrete[2] = 1
    dev.wait(dev.invoke("release_inner_door"))
    assert ("coil", 4, [1]) in drv.link.log
    drv.link.discrete[1] = 0                                                   # inner door opened
    assert dev.read("robot_access_ready") is True
    _refused(-32011, lambda: dev.invoke("release_outer_door"))
    _wait_until(lambda: dev.read("o2_ppm") > 0.5, timeout=20)                 # the box breathes through the open door
    drv.link.discrete[1] = 1
    assert dev.read("robot_access_ready") is False
    _refused(-32012, lambda: dev.invoke("start_regeneration"))
    dev.wait(dev.invoke("start_regeneration", approved=True))
    assert dev.read("regenerating") is True and dev.read("purge_state") == "regenerating"
    dev.wait(dev.invoke("antechamber_cycle", purges=1))
    dev.estop()
    assert drv.link.log[-3:] == [("coil", 1, [1]), ("coil", 2, [0]), ("coil", 3, [0])]
    assert dev.read("regenerating") is False and dev.read("blower_on") is True   # the blower is left running on purpose
    drv.close()


def test_quantos_doses_to_target_and_reports_the_dispensed_mass():
    drv, dev = _twin("mettler-quantos-dosing")
    time.sleep(0.01)                                                           # the pan settles (2 simulated seconds)
    assert dev.read("head_present") is True and dev.read("head_info").startswith("QDH A 1")
    assert dev.read("mass_stable") == 5.2 and dev.read("balance_data") == 'I2 A "XPR205 220.00900 g"'
    dev.wait(dev.invoke("tare"))
    assert dev.read("mass_stable") == 0.0 and dev.read("tare_value") == 5.2
    _refused(-32014, lambda: dev.write("target_mass", 25.001))                 # off the 0.01 grid
    dev.write("target_mass", 25.0)
    assert "A10 0 25.0 mg" in _sent(drv.link)
    r = dev.wait(dev.invoke("dose", target_mg=25, tolerance_pct=2), timeout=30)
    assert r["state"] == "done" and r.get("resultMismatch") is None, r
    assert r["result"]["replies"][:4] == ["A10 A", "A10 A", "A10 A", "QDS B"]
    assert r["result"]["replies"][-1].startswith("QDR A") and 24.0 <= r["result"]["dispensed_mg"] <= 25.6
    assert ["A10 0 25 mg", "A10 1 2 %", "A10 2 2 %", "QDS", "QDR"] == _sent(drv.link)[-5:]
    time.sleep(0.01)
    assert abs(dev.read("mass_stable") * 1000 - r["result"]["dispensed_mg"]) < 0.06      # the pan reads to 0.1 mg
    assert dev.read("last_dose_result").endswith("OK")
    drv.link.head = False                                                      # head taken off: no dose
    assert dev.read("head_present") is False
    _refused(-32011, lambda: dev.invoke("dose", target_mg=5, tolerance_pct=2))
    drv.link.head = True
    _refused(-32012, lambda: dev.invoke("internal_adjustment"))
    r = dev.wait(dev.invoke("internal_adjustment", approved=True))
    assert r["result"]["replies"] == ["C3 B"]
    drv.close()


def test_laurell_spin_coater_runs_a_recipe_under_its_interlocks():
    drv, dev = _twin("laurell-spin-coater")
    assert dev.read("lid_closed") is True and dev.read("vacuum_ok") is False and dev.read("chuck_still") is True
    assert dev.read("robot_access_ready") is False                             # lid closed
    recipe = [{"speed_rpm": 500, "acceleration_rpm_s": 500, "duration_s": 5},
              {"speed_rpm": 3000, "acceleration_rpm_s": 1500, "duration_s": 30},
              {"speed_rpm": 0, "acceleration_rpm_s": 1500, "duration_s": 5}]
    _refused(-32011, lambda: dev.invoke("run_recipe", steps=recipe, slot=20))  # no vacuum
    dev.wait(dev.invoke("vacuum_on"))
    _wait_until(lambda: dev.read("vacuum_ok") is True)
    assert dev.read("vacuum_inhg") >= 15
    _refused(-32014, lambda: dev.invoke("run_recipe", steps=[], slot=20))
    _refused(-32010, lambda: dev.invoke("run_recipe", steps=[{"speed_rpm": 20000, "acceleration_rpm_s": 500, "duration_s": 5}], slot=20))
    r = dev.wait(dev.invoke("run_recipe", steps=recipe, slot=20))
    assert r["result"]["replies"] == ["OK"] * 5 and r.get("resultMismatch") is None
    assert _sent(drv.link)[-5:] == ["STEP 20 1 500 500 5", "STEP 20 2 3000 1500 30", "STEP 20 3 0 1500 5", "PRG 20", "RUN"]
    assert dev.read("running") is True and dev.read("program") == 20 and dev.read("step") >= 1
    _wait_until(lambda: dev.read("speed_rpm") >= 500, timeout=10)
    _refused(-32011, lambda: dev.invoke("vacuum_off"))                         # the chuck turns
    _wait_until(lambda: dev.read("running") is False, timeout=30)
    assert dev.read("speed_rpm") == 0 and dev.read("chuck_still") is True
    dev.wait(dev.invoke("vacuum_off"))
    drv.link.lid = False
    assert dev.read("lid_closed") is False and dev.read("robot_access_ready") is True
    _refused(-32011, lambda: dev.invoke("start_program"))
    drv.link.lid = True
    dev.wait(dev.invoke("vacuum_on")); _wait_until(lambda: dev.read("vacuum_ok") is True)
    dev.wait(dev.invoke("start_program"))
    drv.link.lid = False                                                       # the controller's own interlock halts the run
    _wait_until(lambda: dev.read("running") is False)
    drv.close()


def test_ossila_spin_coater_runs_a_recipe_and_refuses_below_120_rpm():
    drv, dev = _twin("ossila-spin-coater")
    assert dev.read("lid_closed") is True and dev.read("robot_access_ready") is False and dev.read("step") == 0
    recipe = [{"speed_rpm": 1000, "acceleration_rpm_s": 500, "duration_s": 10},
              {"speed_rpm": 4000, "acceleration_rpm_s": 1000, "duration_s": 30},
              {"speed_rpm": 0, "acceleration_rpm_s": 1000, "duration_s": 3}]
    _refused(-32014, lambda: dev.invoke("run_recipe", steps=[{"speed_rpm": 50, "acceleration_rpm_s": 500, "duration_s": 10}], slot=10))
    _refused(-32010, lambda: dev.invoke("run_recipe", steps=recipe, slot=12))
    r = dev.wait(dev.invoke("run_recipe", steps=recipe, slot=10))
    assert r["result"]["replies"] == ["OK"] * 5 and r.get("resultMismatch") is None
    assert _sent(drv.link)[-2:] == ["PRG 10", "RUN"] and "STEP 10 2 4000 1000 30" in _sent(drv.link)
    assert dev.read("running") is True and dev.read("time_remaining") > 0
    _wait_until(lambda: dev.read("speed_rpm") >= 1000, timeout=10)
    _wait_until(lambda: dev.read("step") == 2, timeout=20)
    dev.wait(dev.invoke("stop"))
    _wait_until(lambda: dev.read("speed_rpm") == 0)
    assert dev.read("running") is False and dev.read("step") == 0
    drv.link.lid = False
    assert dev.read("robot_access_ready") is True
    _refused(-32011, lambda: dev.invoke("run_recipe", steps=recipe, slot=10))
    drv.close()


if __name__ == "__main__":
    import traceback
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print("ok ", name)
            except Exception:                                          # noqa: BLE001
                failed += 1; print("FAIL", name); traceback.print_exc()
    print(f"{failed} failed")
    sys.exit(1 if failed else 0)
