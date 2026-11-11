"""The pharma-biologics packages: Sartorius Biostat (OPC UA bindings), BMG/SoftMax/Spark plate reader, Hamilton
STAR and Opentrons OT-2 (PyLabRobot shape), Beckman Vi-CELL BLU (OPC UA), Sartorius Octet (automation socket)
and Malvern Zetasizer (.NET SDK). No vendor library is installed: the real drivers load and report
`connected` false, the twins run through the gates, fault injection and e-stop.

    PYTHONPATH=. python tests/test_packages_pharma_bio.py      (or pytest)
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["OPENMHP_HOME"] = tempfile.mkdtemp(prefix="openmhp-pharma-bio-")
os.environ["OPENMHP_SIM_TIME_SCALE"] = "0.0001"

from openmhp.client import LocalDevice, RemoteError            # noqa: E402
from openmhp.package import load_driver                        # noqa: E402
from openmhp.validate import validate_path                     # noqa: E402

PACKAGES = ["sartorius-biostat-bioreactor", "bmg-clariostar-plate-reader", "hamilton-star", "beckman-vicell-blu",
            "sartorius-octet-bli", "malvern-zetasizer-dls", "opentrons-ot2"]


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
    methods = Path(_folder(name)) / "methods"
    if methods.is_dir():                                          # a run appends to the method's runs file (M6):
        import shutil                                             # keep that out of the shipped package
        copy = Path(tempfile.mkdtemp(prefix=f"methods-{name}-")) / "methods"
        shutil.copytree(methods, copy)
        drv.methods_dir = str(copy)
    return drv, LocalDevice(drv)


def wait_until(fn, timeout=5.0):
    deadline = time.time() + timeout
    while not fn() and time.time() < deadline:
        time.sleep(0.005)
    assert fn(), "condition not reached"


# ------------------------------------------------------------------ every package, the same bar ---- #
def test_packages_validate_load_and_rehearse():
    for name in PACKAGES:
        v = validate_path(_folder(name))
        assert v["ok"], (name, v["errors"])
        assert [w for w in v["warnings"] if "no location" not in w] == [], (name, v["warnings"])

        real = LocalDevice(load_driver(_folder(name)))              # no vendor library, no config.json
        assert real.read("connected") is False, name

        drv, d = twin(name)
        assert d.read("state") == "idle" and d.read("busy") is False and d.read("connected") is True, name
        assert d.read("calibration_status") == "unknown", name    # no record yet: says so, never guesses
        full = d.call("device/describe", {"detail": "full"})
        for action in full["actions"]:
            if not action.get("params"):
                continue
            ex = action["examples"][0]
            try:
                d.invoke(action["name"], dry_run=True, approved=True, **ex)
            except RemoteError as e:
                assert e.code == -32011, (name, action["name"], e.message)   # an open interlock is the only excuse
        # a twin answers fault injection: the next read fails with the injected fault
        assert d.call("sim/fault", {"mode": "raise", "on": "read"})["armed"]["mode"] == "raise"
        try:
            d.read("connected"); raise AssertionError("expected the injected fault")
        except RemoteError as e:
            assert "injected" in e.message
        assert d.read("connected") is True                          # one-shot: the twin answers again
        drv.close()


# ------------------------------------------------------------------------- bioreactor (OPC UA) ---- #
def test_biostat_bioreactor():
    drv, d = twin("sartorius-biostat-bioreactor")
    assert d.read("phase") == "" and d.read("temperature") == 22.0
    refused(-32010, lambda: d.write("temperature_setpoint", 60))
    refused(-32014, lambda: d.write("ph_setpoint", 7.005))                   # off the 0.01 grid
    refused(-32012, lambda: d.write("agitation_setpoint", 200))             # a person confirms stirring speed
    refused(-32011, lambda: d.invoke("add_feed", volume_ml=100, rate_ml_h=50))   # stirrer off: feed would pool
    d.write("agitation_setpoint", 200, approved=True)
    wait_until(lambda: d.read("agitation_running") is True)
    r = d.wait(d.invoke("add_feed", volume_ml=150, rate_ml_h=50))
    assert r["state"] == "done" and r.get("resultMismatch") is None and r["result"]["volume_ml"] == 150
    assert ("write", "ns=2;s=Unit1.SUBS.SP", 50.0) in drv.server.log
    r = d.wait(d.invoke("start_batch", recipe="HEK_transient_5d", duration_s=600))
    assert r["state"] == "done" and r.get("resultMismatch") is None
    assert r["result"]["recipe"] == "HEK_transient_5d" and 590 < r["result"]["duration_s"] < 700
    assert r["result"]["final"]["phase"] == "Stopped"
    # a method-driven action without params or method asks for one (M7)
    e = refused(-32015, lambda: d.invoke("start_batch"))
    assert "cho_fedbatch_14d" in str(e.data)
    found = d.method_find("cho")
    assert found["choice"] == "one"
    j = d.run_method("_shared/cho_fedbatch_14d", wait=False)
    wait_until(lambda: d.read("phase") == "Inoculation")
    refused(-32012, lambda: d.invoke("stop_batch"))
    d.estop()
    assert d.read("state") == "estop"
    writes = [(n, v) for kind, n, *rest in drv.server.log if kind == "write" for v in rest]
    assert ("ns=2;s=Unit1.STIRR.SP", 0.0) in writes and ("ns=2;s=Unit1.GASFL.Mode", 0) in writes
    assert ("ns=2;s=Unit1.TEMP.Mode", 0) in writes
    drv.close()


# ------------------------------------------------------------------------------ plate reader ---- #
def test_plate_reader():
    drv, d = twin("bmg-clariostar-plate-reader")
    assert d.read("plate_in") is True and d.read("robot_access_ready") is False
    refused(-32010, lambda: d.write("temperature_setpoint", 60))
    d.write("temperature_setpoint", 37)
    assert ("Temp", 37) in drv.hw.log
    d.write("temperature_setpoint", None)                                   # incubator off: null is in the contract
    refused(-32011, lambda: d.invoke("plate_in"))                            # tray is in: nothing to close on
    r = d.wait(d.invoke("read", protocol="abs_600", plate_id="PLT-1"))
    assert r["state"] == "done" and r.get("resultMismatch") is None
    assert len(r["result"]["wells"]) == 96 and r["result"]["wells"]["A1"] > 0 and Path(r["result"]["file"]).is_file()
    assert d.wait(d.invoke("plate_out"))["result"]["plate_in"] is False and d.read("robot_access_ready") is True
    refused(-32011, lambda: d.invoke("read", protocol="abs_600", plate_id="PLT-1"))   # no plate inside
    assert d.wait(d.invoke("plate_in"))["result"]["plate_in"] is True
    refused(-32014, lambda: d.invoke("read", protocol="../abs", plate_id="PLT-1"))
    assert d.method_find("od600")["choice"] == "one"
    d.invoke("read", protocol="fluor_gfp_kinetic", plate_id="PLT-2")
    wait_until(lambda: d.read("busy") is True)
    d.estop()
    assert d.read("state") == "estop" and drv.hw.log[-2:] == ["Terminate", "PlateIn"]
    drv.close()


# ------------------------------------------------------------------- Hamilton STAR and OT-2 ---- #
def _liquid_handler(name, tips, boundary_open):
    drv, d = twin(name)
    assert d.read("robot_access_ready") is False and d.read("connect_error") is None
    refused(-32010, lambda: d.write("volume_cap", 5000))
    refused(-32010, lambda: d.invoke("aspirate", resources=["src_plate/A1"], vols=[5000]))
    d.write("volume_cap", 300)
    refused(-32010, lambda: d.invoke("aspirate", resources=["src_plate/A1"], vols=[500]))   # above the mounted tip
    refused(-32014, lambda: d.invoke("aspirate", resources=["nowhere/A1"], vols=[50]))      # not on the deck
    refused(-32014, lambda: d.invoke("aspirate", resources=["src_plate/A1"], vols=[50, 50]))
    r = d.wait(d.invoke("pick_up_tips", tip_spots=[tips]))
    assert r["state"] == "done" and r.get("resultMismatch") is None
    assert d.wait(d.invoke("aspirate", resources=["src_plate/A1"], vols=[100], flow_rate=50))["state"] == "done"
    assert d.wait(d.invoke("dispense", resources=["dst_plate/A1"], vols=[100]))["state"] == "done"
    log = drv.server.lh.log if name == "opentrons-ot2" else drv.server.log
    assert ("aspirate", ["src_plate/A1"], [100.0]) in log and ("dispense", ["dst_plate/A1"], [100.0]) in log
    boundary_open(drv, True)
    assert d.read("robot_access_ready") is True
    refused(-32011, lambda: d.invoke("drop_tips", tip_spots=["trash"]))      # cover/door open: no motion
    boundary_open(drv, False)
    assert d.wait(d.invoke("drop_tips", tip_spots=["trash"]))["state"] == "done"
    d.estop()
    assert d.read("state") == "estop" and log[-1] == "stop" and d.read("connected") is False
    drv.close()


def test_hamilton_star():
    def cover(drv, open_):
        drv.server.backend.cover = open_
    _liquid_handler("hamilton-star", "tips_1000/A1", cover)
    drv, d = twin("hamilton-star")
    assert d.wait(d.invoke("move_plate", plate="src_plate", to="site_2"))["state"] == "done"
    assert ("move_plate", "src_plate", "site_2") in drv.server.log
    drv.close()


def test_opentrons_ot2():
    def door(drv, open_):
        drv.server.door = open_
    _liquid_handler("opentrons-ot2", "tips_300/A1", door)
    drv, d = twin("opentrons-ot2")
    assert "move_plate" not in d.call("device/describe", {"detail": "card"})["actions"]   # no gripper on an OT-2
    drv.close()


# ---------------------------------------------------------------------------- Vi-CELL BLU ---- #
def test_vicell_blu():
    drv, d = twin("beckman-vicell-blu")
    assert d.read("status") == "Idle" and d.read("reagent_remaining") == 180 and d.read("robot_access_ready") is True
    refused(-32010, lambda: d.invoke("count", position="cup", cell_type="CHO", dilution=50))
    refused(-32010, lambda: d.invoke("count", position="30", cell_type="CHO"))
    refused(-32010, lambda: d.invoke("count", position="cup", cell_type="CHO", wash="rinse"))
    refused(-32012, lambda: d.invoke("prime"))
    r = d.wait(d.invoke("count", position="cup", cell_type="CHO"))
    assert r["state"] == "done" and r.get("resultMismatch") is None and r["defaulted"]["count.dilution"] == 1
    res = r["result"]
    assert 85 < res["viability_pct"] < 100 and res["images"] is None and res["viable_cells_per_ml"] < res["total_cells_per_ml"]
    assert d.read("reagent_remaining") == 179
    assert [c for c, _ in drv.server.log] == ["RequestLock", "StartSample", "GetSampleResults", "ReleaseLock"]
    d.invoke("count", position="3", cell_type="HEK293", save_images=True)
    wait_until(lambda: d.read("status") == "Running")
    assert d.read("robot_access_ready") is False
    refused(-32011, lambda: d.invoke("count", position="4", cell_type="HEK293"))   # the stage is busy
    d.estop()
    assert d.read("state") == "estop"
    time.sleep(0.2)                                                          # the cancelled count releases the lock
    assert "Stop" in [c for c, _ in drv.server.log[-3:]] and drv.server.log[-1][0] == "ReleaseLock"
    drv.close()


# ----------------------------------------------------------------------------------- Octet ---- #
def test_octet_bli():
    drv, d = twin("sartorius-octet-bli")
    assert d.read("status") == "OK" and d.read("temperature") is None and d.read("plate_in") is True
    refused(-32010, lambda: d.write("temperature_setpoint", 45))
    refused(-32014, lambda: d.write("temperature_setpoint", 30.5))           # whole degrees only
    d.write("temperature_setpoint", 30)
    assert "SetValue -t30" in drv.hw.log
    refused(-32011, lambda: d.invoke("plate_in"))                            # stage is closed already
    assert d.wait(d.invoke("plate_out"))["result"]["plate_in"] is False and d.read("robot_access_ready") is True
    refused(-32011, lambda: d.invoke("run_experiment", method="IgG_quant_ProA.fmf", sample_plate_id="P", sensor_tray_id="T"))
    assert d.wait(d.invoke("plate_in"))["result"]["plate_in"] is True
    refused(-32014, lambda: d.invoke("run_experiment", method="IgG_quant_ProA", sample_plate_id="P", sensor_tray_id="T"))
    r = d.wait(d.invoke("run_experiment", method="IgG_quant_ProA.fmf", sample_plate_id="SP-1", sensor_tray_id="T-1"))
    assert r["state"] == "done" and r.get("resultMismatch") is None
    assert r["result"]["sensors"] == 1 and r["result"]["file"].startswith("\\\\octet-pc") and 1400 < r["result"]["duration_s"] < 1700
    assert d.method_find("mab")["choice"] == "one"
    j = d.run_method("_shared/mab_kinetics_proa", {"sample_plate_id": "SP-2", "sensor_tray_id": "T-2"}, wait=False)
    wait_until(lambda: d.read("status").startswith("Running"))
    d.estop()
    assert d.read("state") == "estop" and drv.hw.log[-1] == "Stop"
    drv.close()


# ------------------------------------------------------------------------------- Zetasizer ---- #
def test_zetasizer():
    drv, d = twin("malvern-zetasizer-dls")
    assert d.read("status") == "Idle" and 20 < d.read("cell_temperature") < 30
    refused(-32010, lambda: d.write("temperature_setpoint", 95))
    refused(-32010, lambda: d.write("equilibration_s", 1000))
    d.write("temperature_setpoint", 25.0)
    r = d.wait(d.invoke("measure_size", sop="mAb_size_25C.zsop", sample_name="mAb-12"))
    assert r["state"] == "done" and r.get("resultMismatch") is None
    assert 9 < r["result"]["z_average_nm"] < 12 and r["result"]["peaks"][0]["intensity_pct"] > 90 and Path(r["result"]["file"]).is_file()
    r = d.wait(d.invoke("measure_zeta", sop="LNP_zeta_PBS.zsop", sample_name="LNP-3"))
    assert r["state"] == "done" and r.get("resultMismatch") is None and r["result"]["zeta_mv"] < -5
    refused(-32014, lambda: d.invoke("measure_size", sop="size.txt", sample_name="x"))
    assert d.method_find("mab", action="measure_size")["choice"] == "one"
    # the only interlock is connected: make the fake SDK unreachable and the measurement is refused as open
    drv.hw = None
    real_make = drv.make_backend
    drv.make_backend = _raise
    refused(-32011, lambda: d.invoke("measure_size", sop="mAb_size_25C.zsop", sample_name="y"))
    drv.make_backend = real_make
    d.write("equilibration_s", 600)
    d.invoke("measure_size", sop="LNP_size_25C.zsop", sample_name="LNP-4")
    wait_until(lambda: d.read("busy") is True)
    d.estop()
    assert d.read("state") == "estop" and drv.hw.log[-1] == "AbortMeasurement"
    drv.close()


def _raise():
    from openmhp.driver import DeviceFault
    raise DeviceFault("the SDK is not reachable (test)")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok ", name)
