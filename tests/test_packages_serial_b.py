"""The second wave of declarative serial packages: Pfeiffer TPG gauge, SRS RGA, Alicat MFC, Innova shaker,
Sigma centrifuge and the 708-DS template. Each twin runs through the gates with no vendor library.

    PYTHONPATH=. python tests/test_packages_serial_b.py      (or: python -m pytest tests/test_packages_serial_b.py -q)
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["OPENMHP_HOME"] = tempfile.mkdtemp(prefix="openmhp-serial-b-")   # job records are durable (C11); keep this run's own
os.environ["OPENMHP_SIM_TIME_SCALE"] = "0.001"

from openmhp.client import LocalDevice, RemoteError            # noqa: E402
from openmhp.package import load_driver                        # noqa: E402
from openmhp.validate import validate_path                     # noqa: E402

REPO = Path(__file__).resolve().parents[1]
PACKAGES = ["pfeiffer-tpg-gauge", "srs-rga", "alicat-flow-controller", "eppendorf-innova-shaker",
            "sigma-4-16ks-centrifuge", "agilent-dissolution-708ds"]


def _folder(name: str) -> str:
    return str(REPO / "supported-devices" / name)


def refused(code: int, fn):
    try:
        fn(); raise AssertionError(f"expected refusal {code}")
    except RemoteError as e:
        assert e.code == code, e


def _twin(name: str):
    drv = load_driver(_folder(name), sim=True)
    return drv, LocalDevice(drv)


def _settle(seconds: float = 0.02):
    time.sleep(seconds)


# ------------------------------------------------------------------ every package, the same way ---- #

def test_packages_validate_and_real_drivers_load_without_pyserial():
    for name in PACKAGES:
        v = validate_path(_folder(name))
        assert v["ok"], (name, v["errors"])
        assert all("no location" in w for w in v["warnings"]), (name, v["warnings"])
        # the real driver opens the port in setup(): with no pyserial installed that is a clean failure, and
        # with pyserial installed but no port it is False or a clean failure; never a twin by accident
        try:
            dev = LocalDevice(load_driver(_folder(name)))
            assert dev.read("connected") is False
        except (ImportError, OSError, RemoteError, RuntimeError):
            pass
        drv, dev = _twin(name)
        assert dev.read("state") == "idle" and dev.read("busy") is False and dev.read("connected") is True
        assert dev.read("calibration_status") == "unknown"                 # no record yet: says so, never guesses
        full = dev.call("device/describe", {"detail": "full"})
        for action in full["actions"]:
            ex = (action.get("examples") or [{}])[0]
            if action.get("params"):
                assert action.get("examples"), (name, action["name"], "params but no examples")
            try:
                dev.invoke(action["name"], dry_run=True, approved=True, **ex)
            except RemoteError as e:
                assert e.code == -32011, (name, action["name"], e)                # only an open interlock may refuse a dry run
        bounded = [s for s in full["settings"] if isinstance(s.get("limits"), dict) and "max" in s["limits"]]
        for s in bounded:
            refused(-32010, lambda s=s: dev.write(s["name"], s["limits"]["max"] + abs(s["limits"]["max"]) + 1, approved=True))
        # fault injection: a twin answers it, and the next read fails
        assert dev.call("sim/fault", {"mode": "raise", "on": "read"})["armed"]["mode"] == "raise"
        readable = next(s["name"] for s in full["signals"] if s.get("source") not in ("runtime", "record"))
        try:
            dev.read(readable); raise AssertionError("expected the injected fault")
        except RemoteError:
            pass
        dev.call("sim/fault", {"mode": None})
        drv.close()


# -------------------------------------------------------------------------------- per package ---- #

def test_pfeiffer_tpg_gauge():
    drv, dev = _twin("pfeiffer-tpg-gauge")
    assert dev.read("status_1") == 0 and 5e-4 < dev.read("pressure_1") <= 1e-2
    assert dev.read("status_2") == 4 and dev.read("gauge_types") == "TPR/PCR,IKR"
    assert dev.read("unit_code") == 0 and dev.read("sensor_states") == "2,1"
    assert drv.link.sent[-1] == "SEN" and dev.read("error_word") == "0000"
    refused(-32012, lambda: dev.write("sensor_2_on", True))                  # a person confirms a gauge switch-on
    dev.write("sensor_2_on", True, approved=True)
    assert drv.link.sent[-1] == "SEN,0,2" and dev.read("sensor_states") == "2,2"   # true -> 2, never 1
    assert dev.read("status_2") in (0, 2)
    dev.write("sensor_1_on", False, approved=True)
    assert drv.link.sent[-1] == "SEN,1,0"
    r = dev.wait(dev.invoke("read_all"))
    assert r["state"] == "done" and r["result"]["replies"][0].count(",") == 3
    r = dev.wait(dev.invoke("sensors_off"))
    assert r["state"] == "done" and dev.read("sensor_states") == "1,1"
    refused(-32012, lambda: dev.invoke("degas_1"))
    dev.estop()
    assert drv.link.sent[-1] == "SEN,1,1" and dev.read("state") == "estop"
    refused(-32022, lambda: dev.invoke("read_all"))                          # e-stop latched until safety/reset
    drv.close()


def test_srs_rga():
    drv, dev = _twin("srs-rga")
    assert dev.read("identity").startswith("SRSRGA200") and dev.read("cdem_installed") is True
    assert dev.read("status_byte") == 0 and dev.read("filament_ok") is True and dev.read("emission_current") == 0.0
    assert dev.read("electron_energy") == 70 and dev.read("ion_energy_code") == 1 and dev.read("focus_voltage") == 90
    refused(-32012, lambda: dev.write("emission_setpoint", 1.0))             # filament on needs a person
    refused(-32014, lambda: dev.write("emission_setpoint", 1.005, approved=True))   # off the 0.01 grid
    dev.write("emission_setpoint", 1.0, approved=True)
    assert drv.link.sent[-1] == "FL1.0" and dev.read("emission_current") == 1.0 and dev.read("filament_ok") is True
    dev.write("electron_energy_setpoint", 100)
    assert dev.read("electron_energy") == 100
    refused(-32010, lambda: dev.write("cdem_setpoint", 2490, approved=True))        # capped below the head's range
    dev.write("cdem_setpoint", 1400, approved=True)
    assert dev.read("cdem_voltage") == 1400
    # the head's own filament protection: pressure too high -> filament off, FIL_ERR bit 6, STATUS bit 1
    drv.link.pressure_torr = 1e-3
    assert dev.read("emission_current") == 0.0 and dev.read("filament_ok") is False
    assert dev.read("filament_error") == 64 and dev.read("status_byte") == 2 and dev.read("cdem_voltage") == 0
    drv.link.pressure_torr = 1e-6
    refused(-32012, lambda: dev.invoke("calibrate_all"))
    r = dev.wait(dev.invoke("calibrate_all", approved=True))
    assert r["state"] == "done" and r["result"] == {"replies": ["2"]}                # STATUS byte comes back
    r = dev.wait(dev.invoke("initialize"))
    assert r["state"] == "done" and drv.link.sent[-1] == "IN0"
    dev.write("emission_setpoint", 1.0, approved=True)
    assert dev.read("filament_ok") is True                                          # a successful switch-on clears FIL_ERR
    dev.estop()
    assert drv.link.sent[-2:] == ["FL0", "HV0"] and dev.read("state") == "estop"
    assert drv.link.fl_set == 0 and drv.link.hv == 0
    drv.close()


def test_alicat_flow_controller():
    drv, dev = _twin("alicat-flow-controller")
    assert dev.read("pressure") == 14.7 and dev.read("temperature") == 25.0 and dev.read("mass_flow") == 0.0
    assert dev.read("frame").split()[-1] == "N2" and dev.read("firmware").startswith("A   10v20")
    refused(-32014, lambda: dev.write("setpoint", 2.505))                    # resolution 0.01
    dev.write("setpoint", 2.5)
    assert drv.link.sent[-1] == "AS2.5"
    _settle()
    assert abs(dev.read("mass_flow") - 2.5) < 0.01 and dev.read("setpoint_actual") == 2.5
    assert dev.read("volumetric_flow") == dev.read("mass_flow")
    refused(-32012, lambda: dev.invoke("hold_closed"))
    r = dev.wait(dev.invoke("hold_closed", approved=True))
    assert r["state"] == "done" and r["result"]["replies"][0].endswith("HLD")
    _settle()
    assert dev.read("mass_flow") < 0.01 and dev.read("setpoint_actual") == 2.5
    assert dev.wait(dev.invoke("cancel_hold"))["state"] == "done" and "HLD" not in dev.read("frame")
    r = dev.wait(dev.invoke("stop"))
    assert r["state"] == "done" and drv.link.setpoint == 0.0
    # the unit id comes from config.json: the twin has none, so A; a configured one replaces the letter
    drv._config_cache = {"unit_id": "c"}
    drv.link.unit = "C"
    assert dev.read("setpoint_actual") == 0.0 and drv.link.sent[-1] == "C"
    drv._config_cache = {}
    drv.link.unit = "A"
    dev.write("setpoint", 1.0)
    dev.estop()
    assert drv.link.sent[-1] == "AS0" and drv.link.setpoint == 0.0 and dev.read("state") == "estop"
    drv.close()


def test_eppendorf_innova_shaker():
    drv, dev = _twin("eppendorf-innova-shaker")
    assert dev.read("speed") == 0.0 and dev.read("temperature") == 22.0 and dev.read("humidity") == 0.0
    assert dev.read("profile_running") is False and dev.read("speed_setpoint") == 0.0
    assert drv.link.sent[-1] == "RS"
    refused(-32010, lambda: dev.write("target_speed", 401))
    refused(-32014, lambda: dev.write("target_speed", 150.5))
    refused(-32010, lambda: dev.write("target_temperature", 61))
    dev.write("target_speed", 200)
    dev.write("target_temperature", 37.5)
    assert drv.link.sent[-2:] == ["CS 200", "CT 37.5"]
    _settle()
    assert dev.read("speed") == 200.0 and dev.read("speed_setpoint") == 200.0 and dev.read("temperature_setpoint") == 37.5
    assert dev.read("temperature") > 22.0                                        # the chamber is warming
    r = dev.wait(dev.invoke("start_profile", profile=2))
    assert r["state"] == "done" and r["defaulted"] == {"start_profile.step": 1} and drv.link.sent[-1] == "PS 2 1"
    assert dev.read("profile_running") is True
    assert dev.wait(dev.invoke("stop_profile"))["state"] == "done" and dev.read("profile_running") is False
    assert dev.wait(dev.invoke("stop_shaking"))["state"] == "done" and dev.read("speed_setpoint") == 0.0
    dev.write("target_speed", 250)
    dev.estop()
    assert drv.link.sent[-2:] == ["CS 0", "CT 20.0"] and dev.read("state") == "estop"
    assert drv.link.speed_sp == 0.0 and drv.link.temp_sp == 20.0
    drv.close()


def test_sigma_centrifuge():
    drv, dev = _twin("sigma-4-16ks-centrifuge")
    assert dev.read("status_code") == 1 and dev.read("lid_closed") is True and dev.read("standstill") is True
    assert dev.read("robot_access_ready") is False and dev.read("speed") == 0.0 and dev.read("error_code") == 0
    assert dev.read("status_flags") == "0006"
    refused(-32010, lambda: dev.invoke("start", speed=9000, time_s=60))
    refused(-32014, lambda: dev.invoke("start", speed=1500, time_s=60, rcf=1000))   # undeclared parameter
    r = dev.wait(dev.invoke("start", speed=1500, time_s=60))
    assert r["state"] == "done" and r["defaulted"] == {"start.temperature": 20}
    assert drv.link.sent[-4:] == ["setspeed 1500", "settemp 20", "settime 60", "start"]
    _settle()
    assert dev.read("speed") == 1500.0 and dev.read("status_code") == 0 and dev.read("standstill") is False
    assert 0 < dev.read("time_remaining") < 60 and dev.read("speed_setpoint") == 1500.0
    refused(-32012, lambda: dev.invoke("open_lid"))
    refused(-32011, lambda: dev.invoke("open_lid", approved=True))               # rotor turning: interlock open
    refused(-32050, lambda: dev.call("jobs/cancel", {"id": r["id"]}))             # declared not cancellable
    assert dev.wait(dev.invoke("stop"))["state"] == "done"
    _settle()
    assert dev.read("speed") == 0.0 and dev.read("standstill") is True
    assert dev.wait(dev.invoke("open_lid", approved=True))["state"] == "done"
    assert dev.read("status_code") == 2 and dev.read("lid_closed") is False and dev.read("robot_access_ready") is True
    refused(-32011, lambda: dev.invoke("start", speed=1500, time_s=60))         # lid open
    drv.link.lid_open = False
    drv.link.error = 42
    assert dev.read("status_code") == 3
    refused(-32011, lambda: dev.invoke("start", speed=1500, time_s=60))         # error state: lid_closed unreadable counts as open
    assert dev.wait(dev.invoke("reset_error"))["state"] == "done" and dev.read("error_code") == 0
    dev.wait(dev.invoke("start", speed=1000, time_s=60))
    _settle()
    dev.estop()
    assert drv.link.sent[-1] == "fstop" and dev.read("state") == "estop"
    _settle()
    assert dev.read("speed") == 0.0 and drv.link.running is False               # reads still answer after an e-stop
    drv.close()


def test_agilent_708ds_template():
    drv, dev = _twin("agilent-dissolution-708ds")
    assert dev.read("bath_temperature") == 22.0 and dev.read("paddle_speed") == 0.0 and dev.read("run_state") == 0
    assert dev.read("heater_on") is True and dev.read("identity") == "5293DLO0710C000"
    refused(-32012, lambda: dev.write("temperature_setpoint", 37.0))         # everything confirmed: the frames are placeholders
    refused(-32010, lambda: dev.write("temperature_setpoint", 50, approved=True))
    refused(-32014, lambda: dev.write("temperature_setpoint", 37.05, approved=True))
    dev.write("temperature_setpoint", 37.0, approved=True)
    dev.write("paddle_speed_setpoint", 75, approved=True)
    dev.write("run_time", 30, approved=True)
    assert drv.link.sent[-3:] == ["01WBAT37.0", "01WRPM75", "01WTIM30"]
    refused(-32012, lambda: dev.invoke("start_run"))
    r = dev.wait(dev.invoke("start_run", approved=True))
    assert r["state"] == "done" and r["result"] == {"replies": ["01WRUN0001"]}
    _settle()
    assert dev.read("run_state") == 1 and dev.read("paddle_speed") == 75.0 and 0 < dev.read("time_remaining") <= 30
    assert dev.read("bath_temperature") > 22.0
    assert dev.wait(dev.invoke("stop_run"))["state"] == "done" and dev.read("run_state") == 0
    dev.estop()
    assert drv.link.sent[-2:] == ["01WRUN0000", "01WHTR0000"] and dev.read("state") == "estop"
    assert drv.link.heater is False
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
