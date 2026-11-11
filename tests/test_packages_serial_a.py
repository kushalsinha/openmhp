"""The declarative-serial wave A packages: IKA EUROSTAR, JULABO CORIO, Mettler Toledo MT-SICS, Sartorius SBI,
Atlas EZO, New Era NE-1000 and Tecan Cavro XLP 6000. For each: the package validates, the real driver cannot
open a port without pyserial (and says so), and the twin runs through the gates: reserved signals, every
action's first example as a dry run, one real job, an out-of-range write, an open interlock, an injected
fault, and an e-stop that reaches the fake port."""
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["OPENMHP_HOME"] = tempfile.mkdtemp(prefix="openmhp-serial-a-")   # job records are durable (C11)
os.environ["OPENMHP_SIM_TIME_SCALE"] = "0.0005"                             # twins run their physics fast

from openmhp.client import LocalDevice, RemoteError            # noqa: E402
from openmhp.package import load_driver, load_package          # noqa: E402
from openmhp.validate import validate_path                     # noqa: E402

PACKAGES = {
    "ika-eurostar-overhead":   {"job": ("start_stirring", {}),            "stop": "STOP_4"},
    "julabo-corio-circulator": {"job": ("start_circulation", {}),         "stop": "out_mode_05 0"},
    "mettler-toledo-balance":  {"job": ("tare", {}),                      "stop": None},
    "sartorius-balance":       {"job": ("tare", {}),                      "stop": None},
    "atlas-ezo-sensors":       {"job": ("configure_for_polling", {}),     "stop": None},
    "new-era-syringe-pump":    {"job": ("infuse", {"volume_ml": 5.0, "rate_ml_min": 1.5}), "stop": "00STP"},
    "tecan-cavro-pump":        {"job": ("aspirate", {"volume_ul": 250}),  "stop": "/1T"},
}


def _refused(code, fn):
    try:
        fn(); raise AssertionError(f"expected a refusal with {code}")
    except RemoteError as e:
        assert e.code == code, (e.code, str(e))
        return e


def _sent(link) -> list[str]:
    return [s.decode(errors="replace") if isinstance(s, bytes) else s for s in link.sent]


def _twin(name):
    drv = load_driver(f"supported-devices/{name}", sim=True)
    return drv, LocalDevice(drv)


def test_packages_validate_and_real_drivers_need_pyserial():
    for name in PACKAGES:
        v = validate_path(f"supported-devices/{name}")
        assert v["ok"], (name, v["errors"])
        assert [w for w in v["warnings"] if "no location" not in w] == [], (name, v["warnings"])
        # the real driver opens the port in setup(); without pyserial that import is the first thing to fail,
        # before anything is sent anywhere, and the twin must load regardless
        try:
            drv = load_driver(f"supported-devices/{name}")
        except ImportError as e:
            assert "serial" in str(e), (name, e)
        except Exception as e:                                   # noqa: BLE001  pyserial present, no such port
            assert type(e).__name__ in ("SerialException", "FileNotFoundError", "OSError"), (name, e)
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
        for a in load_package(f"supported-devices/{name}").descriptor["actions"]:
            example = (a.get("examples") or [{}])[0]
            r = dev.invoke(a["name"], approved=True, dry_run=True, **example)
            assert r.get("dryRun") or r.get("dry_run") or r.get("ok") or r, (name, a["name"], r)
        drv.close()


def test_twins_refuse_out_of_range_writes_and_open_interlocks():
    for name in PACKAGES:
        drv, dev = _twin(name)
        desc = load_package(f"supported-devices/{name}").descriptor
        bounded = [s for s in desc["settings"] if isinstance(s.get("limits"), dict) and "max" in s["limits"]]
        if bounded:
            s = bounded[0]
            _refused(-32010, lambda: dev.write(s["name"], s["limits"]["max"] * 2 + 1))
        else:
            # the Sartorius package has no numeric setting (SBI has none): the gate still refuses unknown names
            assert name == "sartorius-balance", name
            _refused(-32040, lambda: dev.write("no_such_setting", 1))
        action, params = PACKAGES[name]["job"]
        drv.link.is_open = False                                  # the fake port reports closed: `connected` is false
        assert dev.read("connected") is False, name
        _refused(-32011, lambda: dev.invoke(action, approved=True, **params))
        drv.link.is_open = True
        drv.close()


def test_twins_run_a_job_then_fail_on_an_injected_fault():
    for name in PACKAGES:
        drv, dev = _twin(name)
        action, params = PACKAGES[name]["job"]
        r = dev.wait(dev.invoke(action, approved=True, **params), timeout=30)
        assert r["state"] == "done", (name, r)
        assert isinstance(r["result"]["replies"], list), (name, r["result"])
        assert dev.read("usage_count") >= 1, name                            # counted from the device's own jobs
        assert dev.call("sim/fault", {"mode": "raise", "on": "read"})["armed"]["mode"] == "raise"
        try:
            dev.read("connected"); raise AssertionError(f"{name}: expected the injected fault")
        except RemoteError:
            pass
        drv.close()


def test_twins_estop_reaches_the_fake_port():
    for name, spec in PACKAGES.items():
        drv, dev = _twin(name)
        r = dev.estop("test")
        assert dev.read("state") == "estop", name
        if spec["stop"] is None:
            # balances and a sensor circuit have nothing to stop: the package says so (estop: false) and
            # the base reports that no stop command could be sent rather than pretending one was
            assert r["stopped"] is False and r.get("stop_error"), (name, r)
        else:
            assert r["stopped"] is True, (name, r)
            assert spec["stop"] in _sent(drv.link), (name, _sent(drv.link)[-3:])
        drv.close()


def test_package_specifics():
    # IKA: the speed cap is the package's, not the instrument's; running speed follows the setpoint
    drv, dev = _twin("ika-eurostar-overhead")
    dev.write("stir_rpm", 300)
    dev.wait(dev.invoke("start_stirring"))
    time.sleep(0.02)                                                        # 40 simulated seconds: the shaft is up to speed
    assert dev.read("stir_rpm_actual") == 300 and dev.read("torque") > 0
    assert dev.read("device_name") == "EUROSTAR 60 control"
    _refused(-32012, lambda: dev.write("speed_limit", 1500))                 # confirm-gated
    drv.close()

    # JULABO: setpoint resolution, the boolean mode map, and a bath that moves
    drv, dev = _twin("julabo-corio-circulator")
    _refused(-32014, lambda: dev.write("target_temperature", 37.505))       # off the 0.01 grid
    dev.write("target_temperature", 37.5)
    assert dev.read("temperature_setpoint_actual") == 37.5 and dev.read("circulating") is False
    dev.wait(dev.invoke("start_circulation"))
    time.sleep(0.02)                                                        # 40 simulated seconds of heating
    assert dev.read("circulating") is True and dev.read("status_text") == "03 REMOTE START"
    assert 30 < dev.read("bath_temperature") <= 37.5
    drv.close()

    # Mettler: a weight frame parses, an unstable one is told apart, taring zeroes the net
    drv, dev = _twin("mettler-toledo-balance")
    time.sleep(0.01)                                                        # the pan settles (2 simulated seconds)
    assert dev.read("mass_stable") == 12.3456 and dev.read("serial_number") == 'I4 A "1114350697"'
    dev.wait(dev.invoke("tare"))
    assert dev.read("mass_stable") == 0.0 and dev.read("tare_value") == 12.3456
    drv.link.load_g = 20.0
    try:
        dev.read("mass_stable"); raise AssertionError("an unstable balance answers S I, which is not a number")
    except RemoteError as e:
        assert "S I" in str(e)
    drv.close()

    # Sartorius: every command carries ESC, the print frame keeps its sign
    drv, dev = _twin("sartorius-balance")
    time.sleep(0.01)
    assert dev.read("mass") == 12.3456 and dev.read("model").endswith("ENTRIS224I-1S")
    assert all(s.startswith(b"\x1b") for s in drv.link.sent) and b"\x1bx1_\r\n" in drv.link.sent
    dev.wait(dev.invoke("tare"))
    drv.link.load_g = 12.0
    assert dev.read("mass_frame").endswith("g") is False                   # unstable: no unit yet
    assert dev.read("mass") == -0.3456
    drv.close()

    # Atlas: response codes desynchronise reads until configure_for_polling; calibration is confirm-gated
    drv, dev = _twin("atlas-ezo-sensors")
    dev.wait(dev.invoke("configure_for_polling"))
    assert drv.link.ok_codes is False and dev.read("circuit_info") == "?i,pH,1.98"
    assert dev.read("calibrated") is False and abs(dev.read("ph") - 7.4) < 0.05
    _refused(-32012, lambda: dev.invoke("calibrate_ph", point="mid", value=7.0))
    dev.wait(dev.invoke("calibrate_ph", approved=True, point="mid", value=7.0))
    assert dev.read("calibrated") is True and abs(dev.read("ph") - 7.0) < 0.05
    dev.write("temperature_compensation", 25.0)
    assert dev.read("temperature_compensation_actual") == 25.0
    drv.close()

    # New Era: the address prefix, the DIS totals, a refusal before RUN moves nothing
    drv, dev = _twin("new-era-syringe-pump")
    dev.write("diameter_mm", 14.5)
    r = dev.wait(dev.invoke("infuse", volume_ml=2.0, rate_ml_min=4.0), timeout=30)
    assert r["result"]["replies"][0].startswith("\x0200S") and r["result"]["replies"][-1].endswith("ML\x03")
    assert dev.read("infused_volume") == 2.0 and dev.read("withdrawn_volume") == 0.0
    assert "00DIR INF" in _sent(drv.link) and "00RUN" in _sent(drv.link)
    before = len(_sent(drv.link))
    try:                                                                   # the sim's pump refuses > 40 with ?OOR
        dev.wait(dev.invoke("infuse", volume_ml=1.0, rate_ml_min=45.0)); raise AssertionError("expected a failed job")
    except RemoteError as e:
        assert "?OOR" in str(e) and "InvalidValue" in str(e), e
    assert "00RUN" not in _sent(drv.link)[before:]                          # refused before RUN: nothing moved
    drv.close()

    # Tecan: moves before ZR are refused by the pump, volumes become increments from config, Q is polled
    drv, dev = _twin("tecan-cavro-pump")
    _refused(-32012, lambda: dev.invoke("initialize"))
    dev.wait(dev.invoke("initialize", approved=True))
    assert dev.read("plunger_position") == 0 and dev.read("status_reply").startswith("/0`")
    dev.wait(dev.invoke("aspirate", volume_ul=250))
    assert dev.read("plunger_position") == 1500 and "/1P1500R" in _sent(drv.link) and "/1Q" in _sent(drv.link)
    _refused(-32010, lambda: dev.invoke("aspirate", volume_ul=1200))      # more than the 1000 uL syringe's stroke
    dev.wait(dev.invoke("dispense", volume_ul=100))
    assert dev.read("plunger_position") == 900
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
