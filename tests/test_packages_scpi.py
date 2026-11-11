"""The six declarative SCPI packages (Keithley 2400, Lake Shore 335/336/350, SRS SR830, Thorlabs PM100D,
Rigol DP832, Rigol DS1000Z): each validates, its real driver loads without pyvisa (or fails only on
that import), and its twin runs through the gates: reserved signals, dry-run examples, a job, an
out-of-range write, an open interlock, injected faults and the e-stop commands on the fake link."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["OPENMHP_HOME"] = tempfile.mkdtemp(prefix="openmhp-scpi-")      # job records are durable; keep this run's own
os.environ["OPENMHP_SIM_TIME_SCALE"] = "0.001"

from openmhp.client import LocalDevice, RemoteError            # noqa: E402
from openmhp.package import load_driver, load_package          # noqa: E402
from openmhp.validate import validate_path                     # noqa: E402

REPO = Path(__file__).resolve().parents[1]

# name -> (an out-of-range write, a job to run and wait for, the e-stop commands expected on the link)
PACKAGES = {
    "keithley-smu": {
        "cls": "source_meter", "write": ("voltage_setpoint", 1.5), "bad": ("voltage_setpoint", 500),
        "job": ("source_voltage", {"voltage": 1.0, "compliance_current": 0.01}),
        "estop": [":OUTP OFF", ":ABOR"], "confirm": None,
    },
    "lakeshore-temperature": {
        "cls": "temperature_controller", "write": ("setpoint_1", 77.0), "bad": ("setpoint_1", 1000),
        "job": ("go_to_temperature", {"setpoint": 77.0, "heater_range": 1}),
        "estop": ["RANGE 1,0", "RANGE 2,0"], "confirm": None,
    },
    "srs-lockin": {
        "cls": "lock_in_amplifier", "write": ("sine_amplitude", 0.5), "bad": ("sine_amplitude", 6),
        "job": ("snapshot", {}),
        "estop": ["SLVL 0.004", "AUXV 1,0", "AUXV 2,0", "AUXV 3,0", "AUXV 4,0"], "confirm": None,
    },
    "thorlabs-power-meter": {
        "cls": "sensor", "write": ("wavelength", 532), "bad": ("wavelength", 5000),
        "job": ("measure", {}),
        "estop": None, "confirm": "reset",
    },
    "bench-power-supply": {
        "cls": "power_supply", "write": ("voltage_setpoint_ch1", 3.3), "bad": ("voltage_setpoint_ch3", 12),
        "job": ("configure_ch1", {"voltage": 3.3, "current_limit": 0.5}),
        "estop": [":OUTP CH1,OFF", ":OUTP CH2,OFF", ":OUTP CH3,OFF"], "confirm": "enable_ch1",
    },
    "rigol-oscilloscope": {
        "cls": "oscilloscope", "write": ("timebase_s", 0.001), "bad": ("timebase_s", 100),
        "job": ("measure", {"item": "VPP", "channel": "CHAN1"}),
        "estop": None, "confirm": "autoset",
    },
}


def _refused(code, fn):
    try:
        fn()
        raise AssertionError(f"expected a refusal with {code}")
    except RemoteError as e:
        assert e.code == code, (e.code, str(e))
        return e


def _twin(name: str):
    drv = load_driver(REPO / "supported-devices" / name, sim=True)
    drv.link.is_open = True                     # a previous test may have closed it
    return drv, LocalDevice(drv)


def test_packages_validate_and_the_real_driver_needs_only_pyvisa():
    for name, spec in PACKAGES.items():
        folder = REPO / "supported-devices" / name
        v = validate_path(str(folder))
        assert v["ok"], (name, v["errors"])
        assert [w for w in v["warnings"] if "no location" not in w] == [], (name, v["warnings"])
        pkg = load_package(folder)
        assert pkg.meta["class"] == spec["cls"] and pkg.meta["id"] == f"{name}-01"
        assert (folder / "driver.py").read_text(encoding="utf-8").count("import") == 1
        # the real driver opens the VISA resource in setup(); with pyvisa absent that is the one thing that fails
        try:
            dev = LocalDevice(load_driver(folder))
            assert dev.read("connected") is False
        except ModuleNotFoundError as e:
            assert e.name == "pyvisa", e
        drv, dev = _twin(name)
        assert dev.read("connected") is True
        drv.close()


def test_twins_answer_reserved_signals_and_dry_run_every_example():
    for name in PACKAGES:
        drv, dev = _twin(name)
        assert dev.read("state") == "idle" and dev.read("busy") is False and dev.read("connected") is True
        assert dev.read("calibration_status") == "unknown"                 # no record: says so, never guesses
        assert dev.read("qualification_status") == "unknown" and dev.read("calibration_due") is None
        assert isinstance(dev.read("usage_count"), int)
        for a in drv.descriptor["actions"]:
            if a.get("params"):
                assert a.get("examples"), (name, a["name"])
                for ex in a["examples"]:
                    r = dev.invoke(a["name"], dry_run=True, approved=True, **ex)
                    assert r["state"] == "dryRun", (name, a["name"], r)
        drv.close()


def test_twins_run_a_job_refuse_out_of_range_and_open_interlocks():
    for name, spec in PACKAGES.items():
        drv, dev = _twin(name)
        setting, value = spec["write"]
        dev.write(setting, value)
        bad_setting, bad_value = spec["bad"]
        _refused(-32010, lambda: dev.write(bad_setting, bad_value))
        action, params = spec["job"]
        r = dev.wait(dev.invoke(action, **params))
        assert r["state"] == "done", (name, r)
        assert isinstance(r["result"]["replies"], list) and r["result"]["replies"], (name, r["result"])
        if spec["confirm"]:
            _refused(-32012, lambda: dev.invoke(spec["confirm"]))
        # every action is interlocked on `connected`: a closed link refuses with InterlockOpen
        drv.link.is_open = False
        try:
            _refused(-32011, lambda: dev.invoke(action, **params))
        finally:
            drv.link.is_open = True
        drv.close()


def test_keithley_measure_is_interlocked_on_the_output_and_reads_the_comma_list():
    drv, dev = _twin("keithley-smu")
    assert dev.read("output_on") is False
    _refused(-32011, lambda: dev.invoke("measure"))
    dev.wait(dev.invoke("source_voltage", voltage=2.0, compliance_current=0.001))
    dev.write("output_on", True)
    assert dev.read("output_on") is True and ":OUTP 1" in drv.link.sent
    r = dev.wait(dev.invoke("measure"))
    assert r["result"]["replies"][0].count(",") == 4
    assert abs(dev.read("voltage") - 2.0) < 1e-6                       # :FETC? hands back that reading
    assert abs(dev.read("current") - 0.001) < 1e-9                     # 2 V into 1 kOhm, clamped at compliance
    assert drv.link.sent[-1] == ":FETC?" and ":MEAS:VOLT?" not in drv.link.sent
    assert dev.read("last_error") == '0,"No error"'
    _refused(-32014, lambda: dev.write("voltage_setpoint", 1.0005))      # off the 1 mV grid
    dev.write("output_on", False)
    drv.close()


def test_lakeshore_twin_warms_toward_the_setpoint_and_parses_ramp_fields():
    import time
    drv, dev = _twin("lakeshore-temperature")
    drv.link.__init__()                                                    # fresh cryostat
    assert dev.read("temperature_a") < 5 and dev.read("heater_range_1") == 0
    dev.write("ramp_rate_1", 5.0)
    assert dev.read("ramp_enabled_1") is True and dev.read("ramp_rate_1_actual") == 5.0
    dev.wait(dev.invoke("set_ramp_1", enabled=0, rate=1.0))
    assert dev.read("ramp_enabled_1") is False
    dev.wait(dev.invoke("go_to_temperature", setpoint=77.0, heater_range=3))
    assert dev.read("setpoint_1_actual") == 77.0 and dev.read("heater_range_1") == 3
    deadline = time.time() + 5
    while dev.read("temperature_a") < 60 and time.time() < deadline:
        time.sleep(0.02)
    assert dev.read("temperature_a") > 60, dev.read("temperature_a")
    assert 0 <= dev.read("heater_output_1") <= 100
    drv.close()


def test_srs_twin_signal_follows_sensitivity_and_auto_phase():
    drv, dev = _twin("srs-lockin")
    dev.write("output_interface", 1)
    dev.write("sine_amplitude", 1.0)
    dev.write("sensitivity_index", 20)                                     # 10 mV full scale
    r = dev.read("r")
    assert abs(r - 1e-3) < 1e-9 and dev.read("theta") < 0
    dev.wait(dev.invoke("auto_phase"))
    assert abs(dev.read("theta")) < 1e-6
    snap = dev.wait(dev.invoke("snapshot"))["result"]["replies"][0].split(",")
    assert len(snap) == 4 and abs(float(snap[2]) - r) < 1e-9
    dev.write("sensitivity_index", 10)                                     # 5 uV full scale: overload clamps r
    assert dev.read("r") == 5e-6
    _refused(-32010, lambda: dev.write("aux_out_1", 11))
    drv.close()


def test_thorlabs_twin_reads_the_head_and_rejects_wavelengths_the_head_cannot_take():
    drv, dev = _twin("thorlabs-power-meter")
    assert dev.read("sensor_head").startswith("S121C")
    dev.write("wavelength", 532)
    assert dev.read("wavelength") == 532.0
    p = dev.read("power")
    assert 0.9e-3 < p < 1.2e-3, p
    dev.write("wavelength", 800)                                           # wrong wavelength, wrong reading
    assert dev.read("power") != p
    dev.write("wavelength", 300)                                           # inside the descriptor, outside the head
    assert dev.read("last_error").startswith("-222")
    _refused(-32014, lambda: dev.write("wavelength", 532.5))               # 1 nm grid
    assert dev.read("temperature") == 23.45
    assert dev.describe("full")["safety"]["estop"] is False
    drv.close()


def test_psu_twin_enables_with_protection_and_trips_on_ocp():
    drv, dev = _twin("bench-power-supply")
    dev.wait(dev.invoke("configure_ch1", voltage=5.0, current_limit=1.0, ovp=6.0, ocp=0.2))
    assert dev.read("output_ch1") is False
    r = dev.wait(dev.invoke("enable_ch1", approved=True))
    assert r["state"] == "done" and drv.link.sent[-3:] == [":OUTP:OVP CH1,ON", ":OUTP:OCP CH1,ON", ":OUTP CH1,ON"]
    # 5 V into 10 ohm draws 0.5 A, above the 0.2 A OCP: the twin trips the output off like the supply
    assert dev.read("output_ch1") is False and "Protection" in dev.read("last_error")
    dev.write("ocp_ch1", 1.0)
    dev.wait(dev.invoke("enable_ch1", approved=True))
    assert dev.read("output_ch1") is True and dev.read("voltage_ch1") == 5.0 and dev.read("current_ch1") == 0.5
    assert abs(dev.read("power_ch1") - 2.5) < 1e-9
    dev.wait(dev.invoke("disable_ch1"))
    assert dev.read("output_ch1") is False
    _refused(-32010, lambda: dev.write("voltage_setpoint_ch3", 6))
    drv.close()


def test_scope_twin_measures_clips_and_reports_invalid_as_9e37():
    drv, dev = _twin("rigol-oscilloscope")
    dev.write("ch1_scale_v", 0.5)
    assert dev.read("ch1_scale_actual") == 0.5
    assert abs(dev.read("vpp_ch1") - 2.0) < 1e-6 and dev.read("freq_ch1") == 1000.0
    dev.write("ch1_scale_v", 0.1)                                          # 2 Vpp on a 0.8 V screen: clipped
    assert dev.read("vmax_ch1") == 0.4
    dev.write("ch1_scale_v", 0.3)                                          # snaps to the 1-2-5 sequence
    assert dev.read("ch1_scale_actual") == 0.2
    r = dev.wait(dev.invoke("measure", item="VPP", channel="CHAN2"))
    assert float(r["result"]["replies"][0]) == 9.9e37
    dev.wait(dev.invoke("single"))
    assert dev.read("trigger_status") == "TD"
    dev.wait(dev.invoke("stop"))
    assert dev.read("trigger_status") == "STOP"
    _refused(-32012, lambda: dev.invoke("autoset"))
    _refused(-32010, lambda: dev.write("trigger_source", "D0"))
    assert dev.describe("full")["safety"]["estop"] is False
    drv.close()


def test_injected_faults_and_estop_commands_reach_the_fake_link():
    for name, spec in PACKAGES.items():
        drv, dev = _twin(name)
        assert dev.call("sim/fault", {"mode": "raise", "on": "read"})["armed"]["mode"] == "raise"
        signal = {"keithley-smu": "output_on", "lakeshore-temperature": "temperature_a", "srs-lockin": "r",
                  "thorlabs-power-meter": "power", "bench-power-supply": "voltage_ch1",
                  "rigol-oscilloscope": "trigger_status"}[name]
        _refused_any = None
        try:
            dev.read(signal); raise AssertionError("expected the injected fault")
        except RemoteError as e:
            _refused_any = e
        assert _refused_any is not None
        dev.call("sim/fault", {"mode": None})
        dev.read(signal)                                                   # disarmed: reads again
        if spec["estop"]:
            before = len(drv.link.sent)
            dev.estop()
            assert drv.link.sent[before:] == spec["estop"], (name, drv.link.sent[before:])
            assert dev.read("state") == "estop"
            try:
                dev.write(*spec["write"]); raise AssertionError("writes must be refused during e-stop")
            except RemoteError as e:
                assert "stop" in str(e).lower(), e
            dev.reset()
            assert dev.read("state") == "idle"
        drv.close()


if __name__ == "__main__":
    import traceback
    failed = 0
    for fname, fn in sorted(globals().items()):
        if fname.startswith("test_") and callable(fn):
            try:
                fn(); print("ok ", fname)
            except Exception:                                          # noqa: BLE001
                failed += 1; print("FAIL", fname); traceback.print_exc()
    print(f"{failed} failed")
    sys.exit(1 if failed else 0)
