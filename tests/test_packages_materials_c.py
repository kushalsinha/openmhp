"""Materials-characterization packages, wave C: Phenom desktop SEM (PPI), TESCAN SEM (SharkSEM, template),
ZEISS SEM (SmartSEM Remote API, template, Windows) and Quantum Design PPMS / DynaCool / MPMS3 (MultiPyVu).
No vendor library is installed: the real drivers must load and read `connected` False, and the twins must
run through the same gates as the real drivers, fault injection and e-stop.

    PYTHONPATH=. python tests/test_packages_materials_c.py      (or: python -m pytest tests/test_packages_materials_c.py -q)
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["OPENMHP_HOME"] = tempfile.mkdtemp(prefix="openmhp-materials-c-")
os.environ["OPENMHP_SIM_TIME_SCALE"] = "0.001"

from openmhp.client import LocalDevice, RemoteError            # noqa: E402
from openmhp.driver import DeviceFault                         # noqa: E402
from openmhp.package import load_driver, load_package          # noqa: E402
from openmhp.validate import validate_path                     # noqa: E402

PACKAGES = ["phenom-desktop-sem", "tescan-sem", "zeiss-sem", "quantum-design-ppms"]
SEMS = ["phenom-desktop-sem", "tescan-sem", "zeiss-sem"]


def _folder(name: str) -> str:
    return str(Path(__file__).resolve().parents[1] / "supported-devices" / name)


def refused(code, fn):
    try:
        fn()
        raise AssertionError(f"expected refusal {code}")
    except RemoteError as e:
        assert e.code == code, f"{e.code} {e.message}"
        return e


def twin(name: str):
    drv = load_driver(_folder(name), sim=True)
    return drv, LocalDevice(drv)


def wait_until(fn, timeout=5.0):
    deadline = time.time() + timeout
    while not fn() and time.time() < deadline:
        time.sleep(0.005)
    assert fn(), "condition not reached"


def _broken():
    raise DeviceFault("the vendor link is down (test)")


def _tiff_ok(path: str, width: int, height: int) -> None:
    with open(path, "rb") as f:
        head = f.read(8)
    assert head[:4] == b"II*\x00", head
    assert os.path.getsize(path) == 8 + 2 + 12 * 9 + 4 + width * height


# ------------------------------------------------------------------ every package, the same bar ---- #
def test_packages_validate_load_and_rehearse():
    for name in PACKAGES:
        v = validate_path(_folder(name))
        assert v["ok"], (name, v["errors"])
        assert [w for w in v["warnings"] if "no location" not in w] == [], (name, v["warnings"])
        meta = load_package(_folder(name)).meta
        assert meta["class"] in ("electron_microscope", "cryostat"), (name, meta["class"])
        if meta["class"] == "electron_microscope":
            assert meta["class_ref"] == "CHMO:0000941", name

        real = LocalDevice(load_driver(_folder(name)))              # no vendor library, no config.json
        assert real.read("connected") is False, name

        drv, d = twin(name)
        assert d.read("state") == "idle" and d.read("busy") is False and d.read("connected") is True, name
        assert d.read("calibration_status") == "unknown", name    # no record yet: says so, never guesses
        desc = load_package(_folder(name)).descriptor
        for action in desc["actions"]:
            ex = (action.get("examples") or [{}])[0]
            try:
                r = d.invoke(action["name"], dry_run=True, approved=True, **ex)
                assert r["state"] == "dryRun", (name, action["name"], r)
            except RemoteError as e:
                assert e.code == -32011, (name, action["name"], e.message)   # an open interlock is the only excuse
        # the connected interlock: break the vendor link and the first action needing it is refused as open
        good_hw, good_make = drv.hw, drv.make_backend
        drv.hw, drv.make_backend = None, _broken
        assert d.read("connected") is False, name
        first = next(a for a in desc["actions"] if "connected" in (a.get("interlocks") or []))
        refused(-32011, lambda: d.invoke(first["name"], approved=True, **(first.get("examples") or [{}])[0]))
        drv.hw, drv.make_backend = good_hw, good_make
        assert d.read("connected") is True, name
        # a twin answers fault injection: the next read fails with the injected fault
        assert d.call("sim/fault", {"mode": "raise", "on": "read"})["armed"]["mode"] == "raise"
        try:
            d.read("connected"); raise AssertionError("expected the injected fault")
        except RemoteError as e:
            assert "injected" in e.message, (name, e.message)
        assert d.read("connected") is True, name                     # one-shot: the twin answers again
        drv.close()


# ------------------------------------------------------------ the three SEMs share a shape (SPEC 13) ---- #
def test_sem_conventions():
    for name in SEMS:
        desc = load_package(_folder(name)).descriptor
        sigs = {s["name"] for s in desc["signals"]}
        assert {"vacuum_ready", "beam_on", "stage_position", "robot_access_ready"} <= sigs, name
        acts = {a["name"]: a for a in desc["actions"]}
        assert "robot_access_ready" in acts["load_sample"]["interlocks"], name
        assert desc["physical"]["automated_load"] is False, name     # no vendor loader documented on any of them
        ret = acts["acquire_image"]["returns"]["properties"]
        assert "file" in ret and "magnification" in ret, name
        for p in ("magnification", "width_px", "height_px"):
            assert acts["acquire_image"]["params"][p]["limits"], (name, p)
        assert desc["safety"]["estop"] is True, name


# ------------------------------------------------------------------------------- Phenom (PPI) ---- #
def test_phenom_desktop_sem():
    drv, d = twin("phenom-desktop-sem")
    assert d.read("operational_mode") == "Unloaded" and d.read("robot_access_ready") is True
    assert d.read("vacuum_ready") is False and d.read("beam_on") is False
    refused(-32010, lambda: d.write("high_voltage", 30))
    refused(-32014, lambda: d.write("high_voltage", 10.05))                  # 0.1 kV grid
    refused(-32011, lambda: d.invoke("move_stage", x_mm=0, y_mm=0))          # holder not loaded: no vacuum
    refused(-32011, lambda: d.invoke("acquire_image", magnification=5000))
    r = d.wait(d.invoke("load_sample"))
    assert r["state"] == "done" and r.get("resultMismatch") is None and r["result"]["loaded"] is True
    assert 55 < r["result"]["duration_s"] < 70 and "Load" in drv.hw.log
    assert d.read("vacuum_ready") is True and d.read("beam_on") is True and d.read("robot_access_ready") is False
    refused(-32011, lambda: d.invoke("load_sample"))                          # already loaded: port not presented
    refused(-32010, lambda: d.invoke("move_stage", x_mm=60, y_mm=0))          # off the 100 x 100 mm stage
    assert d.wait(d.invoke("move_stage", x_mm=12.5, y_mm=-8.0))["result"] == {"x_mm": 12.5, "y_mm": -8.0}
    assert d.read("stage_position") == {"x_mm": 12.5, "y_mm": -8.0} and "MoveTo 0.012500 -0.008000" in drv.hw.log
    d.write("high_voltage", 15)
    assert d.read("high_voltage") == 15.0 and "SetSemHighTension -15000" in drv.hw.log
    refused(-32010, lambda: d.invoke("acquire_image", magnification=100))     # below 160x
    refused(-32010, lambda: d.invoke("acquire_image", magnification=5000, detector="eds"))
    refused(-32014, lambda: d.invoke("acquire_image", magnification=5000, label="../x"))
    r = d.wait(d.invoke("acquire_image", magnification=5000, width_px=640, height_px=480, auto_focus=True, label="loc04"))
    assert r["state"] == "done" and r.get("resultMismatch") is None
    res = r["result"]
    assert res["magnification"] == 5000.0 and res["hfw_um"] == 20.0 and res["high_voltage_kv"] == 15.0
    assert res["stage"] == {"x_mm": 12.5, "y_mm": -8.0} and res["file"].endswith("_loc04_5000x.tif")
    _tiff_ok(res["file"], 640, 480)
    assert "SemAutoFocus" in drv.hw.log and any(s.startswith("SemAcquireImage 640x480") for s in drv.hw.log)
    assert d.read("last_image") == res and r["defaulted"]["acquire_image.frames"] == 1
    r = d.wait(d.invoke("unload_sample"))
    assert r["result"]["loaded"] is False and d.read("robot_access_ready") is True and d.read("vacuum_ready") is False
    d.wait(d.invoke("load_sample"))
    d.invoke("acquire_image", magnification=2000, width_px=1920, height_px=1200, frames=8, dwell_us=100)
    wait_until(lambda: d.read("busy") is True)
    d.estop()
    assert d.read("state") == "estop" and drv.hw.log[-1] == "Standby"
    drv.close()


# ---------------------------------------------------------------------- TESCAN (SharkSEM template) ---- #
def _sem_cycle(name, hv_name, stop_log):
    """The common SEM cycle on the TESCAN and ZEISS twins: vent -> pump -> beam -> stage -> image -> vent -> estop."""
    drv, d = twin(name)
    assert d.read("robot_access_ready") is True and d.read("vacuum_ready") is False and d.read("beam_on") is False
    refused(-32010, lambda: d.write("high_voltage", 40))
    refused(-32011, lambda: d.invoke("set_beam", enable=True))               # chamber at atmosphere
    refused(-32011, lambda: d.invoke("move_stage", x_mm=0, y_mm=0))
    r = d.wait(d.invoke("load_sample"))
    assert r["state"] == "done" and r.get("resultMismatch") is None and r["result"]["vacuum_ready"] is True
    assert d.read("vacuum_ready") is True and d.read("robot_access_ready") is False
    refused(-32011, lambda: d.invoke("load_sample"))                          # pumped: the door may not be opened
    refused(-32011, lambda: d.invoke("acquire_image", magnification=2000))    # beam off
    d.write("high_voltage", 10)
    r = d.wait(d.invoke("set_beam", enable=True))
    assert r["state"] == "done" and r.get("resultMismatch") is None and r["result"] ["beam_on"] is True
    assert r["result"]["high_voltage_kv"] == 10.0 and d.read("beam_on") is True and hv_name in " ".join(map(str, drv.hw.log))
    refused(-32010, lambda: d.invoke("move_stage", x_mm=0, y_mm=0, tilt_deg=95))
    r = d.wait(d.invoke("move_stage", x_mm=5.0, y_mm=-3.5))
    assert r["state"] == "done" and r.get("resultMismatch") is None
    assert r["result"]["x_mm"] == 5.0 and r["result"]["y_mm"] == -3.5 and r["result"]["z_mm"] == d.read("stage_position")["z_mm"]
    r = d.wait(d.invoke("acquire_image", magnification=2000, width_px=320, height_px=256, auto_focus=True, label="grain01"))
    assert r["state"] == "done" and r.get("resultMismatch") is None
    res = r["result"]
    assert res["magnification"] == 2000.0 and res["frames"] == 1 and res["stage"]["x_mm"] == 5.0
    _tiff_ok(res["file"], 320, 256)
    r = d.wait(d.invoke("acquire_image", magnification=20000, width_px=256, height_px=256, frames=4, detector=("bse" if name == "tescan-sem" else "bsd")))
    assert r["state"] == "done" and r.get("resultMismatch") is None and r["result"]["frames"] == 4
    _tiff_ok(r["result"]["file"], 256, 256)
    r = d.wait(d.invoke("unload_sample"))
    assert r["result"]["beam_on"] is False and r["result"]["vacuum_ready"] is False and d.read("robot_access_ready") is True
    d.wait(d.invoke("load_sample"))
    d.wait(d.invoke("set_beam", enable=True))
    d.invoke("move_stage", x_mm=-30, y_mm=30)
    wait_until(lambda: d.read("busy") is True)
    d.estop()
    assert d.read("state") == "estop" and d.read("beam_on") is False and drv.hw.log[-3:] == stop_log
    drv.close()


def test_tescan_sem():
    _sem_cycle("tescan-sem", "HVSetVoltage 10000", ["ScStopScan", "StgStop", "HVBeamOff"])


# ------------------------------------------------------------- ZEISS (SmartSEM Remote API template) ---- #
def test_zeiss_sem():
    _sem_cycle("zeiss-sem", "Set AP_MANUALKV 10.0", ["Execute CMD_FREEZE_ALL", "Execute CMD_STAGE_STOP", "Execute CMD_EHT_OFF"])
    setup = (Path(_folder("zeiss-sem")) / "references" / "setup.md").read_text(encoding="utf-8").lower()
    assert "windows only" in setup or "windows-only" in setup               # the vendor route needs the SmartSEM PC


# ------------------------------------------------------------------------- PPMS (MultiPyVu) ---- #
def test_quantum_design_ppms():
    drv, d = twin("quantum-design-ppms")
    assert d.read("temperature") == 300.0 and d.read("temperature_status") == "Stable"
    assert d.read("field") == 0.0 and d.read("field_status") == "Stable Persistent" and d.read("chamber_state") == "Purged and Sealed"
    refused(-32010, lambda: d.write("temperature_setpoint", 450))
    refused(-32010, lambda: d.write("temperature_rate", 50))
    refused(-32010, lambda: d.write("field_approach", "fast"))               # not in the enum
    refused(-32012, lambda: d.write("field_setpoint", 1000))                  # a person confirms a magnet ramp
    refused(-32012, lambda: d.invoke("set_field_and_wait", field=1000))
    refused(-32012, lambda: d.invoke("discharge_magnet"))
    refused(-32012, lambda: d.invoke("set_chamber", mode="vent_seal"))
    refused(-32010, lambda: d.invoke("set_chamber", mode="open", approved=True))
    d.write("temperature_rate", 10)
    d.write("temperature_approach", "no_overshoot")
    d.write("temperature_setpoint", 305)
    assert drv.hw.log[-1] == "set_temperature 305.0 10.0 no_overshoot" and d.read("temperature_setpoint_actual") == 305.0
    wait_until(lambda: d.read("temperature_status") == "Stable", timeout=10)
    assert d.read("temperature") == 305.0
    r = d.wait(d.invoke("set_temperature_and_wait", temperature=295, rate=5, settle_s=30))
    assert r["state"] == "done" and r.get("resultMismatch") is None
    assert r["result"]["reached"] is True and r["result"]["temperature_K"] == 295.0 and r["result"]["status"] == "Stable"
    assert 140 < r["result"]["duration_s"] < 200                             # 10 K at 5 K/min plus 30 s settle
    d.write("field_driven_mode", "driven")                                   # platform ppms in the twin's config
    d.write("field_setpoint", 2000, approved=True)
    assert drv.hw.log[-1] == "set_field 2000.0 100.0 linear driven"
    wait_until(lambda: d.read("field_status") == "Stable Driven", timeout=10)
    r = d.wait(d.invoke("set_field_and_wait", field=10000, rate=200, approach="no_overshoot", approved=True))
    assert r["state"] == "done" and r.get("resultMismatch") is None
    assert r["result"]["reached"] is True and r["result"]["field_Oe"] == 10000.0 and r["result"]["setpoint_Oe"] == 10000.0
    r = d.wait(d.invoke("discharge_magnet", rate=200, approved=True))
    assert r["state"] == "done" and r.get("resultMismatch") is None and r["result"]["field_Oe"] == 0.0 and d.read("field") == 0.0
    r = d.wait(d.invoke("set_chamber", mode="vent_seal", approved=True))
    assert r["state"] == "done" and r.get("resultMismatch") is None
    assert r["result"]["chamber_state"] == "Vented and Sealed" and d.read("chamber_state") == "Vented and Sealed"
    # a ramp cancelled from here is not stopped on the instrument: MultiVu keeps driving to the setpoint
    j = d.invoke("set_temperature_and_wait", temperature=2, rate=0.5, settle_s=60)
    wait_until(lambda: d.read("busy") is True)
    d.cancel(j)
    r = d.wait(j)
    assert r["state"] == "cancelled" and d.read("temperature_setpoint_actual") == 2.0
    # no software stop: estop is declared false, nothing is sent, the magnet is untouched
    desc = load_package(_folder("quantum-design-ppms")).descriptor
    assert desc["safety"]["estop"] is False and desc["safety"]["watchdog_action"] == "release"
    n = len(drv.hw.log)
    d.estop()
    assert d.read("state") == "estop" and len(drv.hw.log) == n
    drv.close()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok ", name)
