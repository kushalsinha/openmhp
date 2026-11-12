"""The three declarative Modbus packages of the pharma wave: Thermo Heracell VIOS CO2 incubator,
BINDER KBF/KMF stability chamber and SP LyoStar freeze dryer. All three are register-map
templates (no vendor Modbus document was readable), so what is tested is the package contract:
validate passes, the real driver loads without pymodbus, and the twin runs through every gate."""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["OPENMHP_HOME"] = tempfile.mkdtemp(prefix="openmhp-modbus-pkgs-")
os.environ["OPENMHP_SIM_TIME_SCALE"] = "0.0005"

from openmhp.client import LocalDevice, RemoteError            # noqa: E402
from openmhp.package import load_driver, load_package           # noqa: E402
from openmhp.validate import validate_path                      # noqa: E402

REPO = Path(__file__).resolve().parents[1]
PACKAGES = ["thermo-heracell-co2-incubator", "binder-stability-chamber", "sp-lyostar-freeze-dryer"]


def _folder(name: str) -> str:
    return str(REPO / "supported-devices" / name)


def _refused(code, fn):
    try:
        fn(); raise AssertionError(f"expected a refusal with {code}")
    except RemoteError as e:
        assert e.code == code, e
        return e


def _wait_until(fn, timeout=5.0):
    deadline = time.time() + timeout
    while not fn() and time.time() < deadline:
        time.sleep(0.01)
    assert fn(), "condition not met in time"


def test_packages_validate_and_the_real_driver_loads_without_pymodbus():
    for name in PACKAGES:
        v = validate_path(_folder(name))
        assert v["ok"], (name, v["errors"])
        left = [w for w in v["warnings"] if "no location" not in w and "robot_access_ready" not in w]
        assert not left, (name, left)
        pkg = load_package(_folder(name))
        assert pkg.meta["driver"] == "driver.py:Device" and pkg.meta["sim"] == "sim.py:Sim"
        assert (pkg.dir / "driver.py").read_text().count("import") == 1
        # the real driver opens pymodbus in setup(); without it the package must fail cleanly, never half-load
        try:
            dev = LocalDevice(load_driver(_folder(name)))
            assert dev.read("connected") is False
        except (ImportError, RemoteError, RuntimeError):
            pass
        for rel in ("references/setup.md", "references/registers.md", "config.example.json", "config.schema.json"):
            assert (pkg.dir / rel).is_file(), (name, rel)
        assert "unverified" in (pkg.dir / "references" / "registers.md").read_text().lower()
        assert "## First hardware test" in (pkg.dir / "references" / "setup.md").read_text()


def _common(dev: LocalDevice):
    assert dev.read("state") == "idle" and dev.read("busy") is False and dev.read("connected") is True
    assert dev.read("calibration_status") == "unknown"            # no record yet: says so, never guesses
    assert dev.read("qualification_status") == "unknown"
    for a in dev.call("device/describe", {"detail": "full"}).get("actions", []):
        ex = (a.get("examples") or [None])[0]
        if a.get("params"):
            assert ex is not None, a["name"]
            r = dev.call("actions/invoke", {"name": a["name"], "params": ex, "dryRun": True, "approved": True})
            assert r["job"]["state"] == "dryRun", r
    _refused(-32040, lambda: dev.read("no_such_signal"))


def test_heracell_incubator_twin():
    drv = load_driver(_folder("thermo-heracell-co2-incubator"), sim=True)
    dev = LocalDevice(drv)
    _common(dev)
    assert 36.0 <= dev.read("temperature") <= 38.0 and abs(dev.read("co2") - 5.0) < 0.5
    assert dev.read("door_closed") is True and dev.read("alarm_active") is False
    assert dev.read("temperature_setpoint_actual") == 37.0
    dev.write("co2_setpoint", 8.0)
    assert dev.read("co2_setpoint_actual") == 8.0 and ("holding", 101, [800]) in drv.link.log
    _wait_until(lambda: dev.read("co2") > 7.5)                     # the twin's gas model follows the setpoint
    _refused(-32010, lambda: dev.write("temperature_setpoint", 60))
    _refused(-32014, lambda: dev.write("temperature_setpoint", 37.05))   # off the 0.1 grid
    drv.link.discrete[0] = 0                                        # door opened: readings drift, alarm follows
    assert dev.read("door_closed") is False
    drv.link.discrete[0] = 1
    assert dev.call("sim/fault", {"mode": "raise", "on": "read"})["armed"]["mode"] == "raise"
    try:
        dev.read("temperature"); raise AssertionError("expected the injected fault")
    except RemoteError:
        pass
    dev.call("sim/fault", {"mode": None})
    # estop: false, so a stop request latches the state and reports that nothing was sent
    before = len(drv.link.log)
    r = dev.call("safety/estop", {})
    assert r["state"] == "estop" and r["stopped"] is False and "no Modbus estop steps" in r["stop_error"]
    assert len(drv.link.log) == before and dev.read("state") == "estop"
    drv.close()


def test_binder_chamber_twin():
    drv = load_driver(_folder("binder-stability-chamber"), sim=True)
    dev = LocalDevice(drv)
    _common(dev)
    assert abs(dev.read("temperature") - 25.0) < 0.01 and abs(dev.read("humidity") - 60.0) < 0.01
    assert dev.read("temperature_setpoint_actual") == 25.0 and dev.read("light_on") is False
    # both setpoints are GxP events: refused without a person's confirmation, then written as floats
    _refused(-32012, lambda: dev.write("temperature_setpoint", 40))
    dev.call("settings/write", {"name": "temperature_setpoint", "value": 40, "approved": True})
    assert dev.read("temperature_setpoint_actual") == 40.0 and drv.link.log[-1][:2] == ("holding", 4270)
    _refused(-32010, lambda: dev.call("settings/write", {"name": "humidity_setpoint", "value": 95, "approved": True}))
    _wait_until(lambda: dev.read("temperature") > 25.5)
    drv.link.discrete[0] = 0
    assert dev.read("door_closed") is False
    _wait_until(lambda: dev.read("alarm_active") is True)
    drv.link.discrete[0] = 1
    assert dev.call("sim/fault", {"mode": "raise", "on": "read"})["armed"]["mode"] == "raise"
    try:
        dev.read("humidity"); raise AssertionError("expected the injected fault")
    except RemoteError:
        pass
    dev.call("sim/fault", {"mode": None})
    before = len(drv.link.log)
    r = dev.call("safety/estop", {})
    assert r["state"] == "estop" and r["stopped"] is False and len(drv.link.log) == before
    assert dev.read("state") == "estop"
    drv.close()


def test_lyostar_freeze_dryer_twin():
    drv = load_driver(_folder("sp-lyostar-freeze-dryer"), sim=True)
    dev = LocalDevice(drv)
    _common(dev)
    assert dev.read("phase_code") == 0 and dev.read("idle") is True and dev.read("recipe_running") is False
    assert dev.read("chamber_pressure") > 900 and dev.read("condenser_temperature") < -80
    assert dev.read("product_temperature_1") == 20.0
    # methods: the example record is served and found by compound
    found = dev.call("methods/find", {"compound": "example-small-molecule-api"})
    assert found["choice"] == "one" and found["method"]["name"] == "mannitol-sucrose-5pct"
    _refused(-32015, lambda: dev.call("actions/invoke", {"name": "start_recipe"}))
    _refused(-32010, lambda: dev.invoke("start_recipe", recipe=150))
    _refused(-32014, lambda: dev.invoke("start_recipe", recipe=3, extra=1))
    # interlocks: door open refuses; hold refuses while nothing runs
    _refused(-32011, lambda: dev.invoke("hold"))
    drv.link.discrete[0] = 0
    _refused(-32011, lambda: dev.invoke("start_recipe", recipe=3))
    drv.link.discrete[0] = 1
    r = dev.wait(dev.invoke("start_recipe", recipe=3))
    assert r["state"] == "done" and r["result"] == {"steps": 2}
    assert ("holding", 110, [3]) in drv.link.log and ("coil", 0, [1]) in drv.link.log
    assert dev.read("recipe_running") is True and dev.read("idle") is False and dev.read("phase_code") == 2
    assert dev.read("usage_count") == 1
    _refused(-32011, lambda: dev.invoke("defrost_condenser", approved=True))
    _wait_until(lambda: dev.read("phase_code") == 4, timeout=20)   # primary drying: chamber pulled down
    _wait_until(lambda: dev.read("chamber_pressure") < 1.0, timeout=20)
    assert dev.read("pirani_pressure") > dev.read("chamber_pressure")   # water vapour: Pirani reads high
    dev.wait(dev.invoke("hold"))
    assert drv.link.coils[1] == 1 and dev.read("phase_code") == 6
    _refused(-32012, lambda: dev.write("shelf_setpoint", -10))
    _refused(-32012, lambda: dev.invoke("stop_recipe"))
    dev.call("settings/write", {"name": "shelf_setpoint", "value": -10, "approved": True})
    assert ("holding", 100, [65436]) in drv.link.log                  # -100 tenths as int16
    assert dev.call("sim/fault", {"mode": "raise", "on": "read"})["armed"]["mode"] == "raise"
    try:
        dev.read("shelf_temperature"); raise AssertionError("expected the injected fault")
    except RemoteError:
        pass
    dev.call("sim/fault", {"mode": None})
    dev.estop()
    assert drv.link.log[-2:] == [("coil", 0, [0]), ("coil", 3, [0])] and dev.read("state") == "estop"
    assert dev.read("recipe_running") is False
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
