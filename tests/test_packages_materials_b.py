"""Materials-characterization packages, wave B: Rigaku SmartLab under SmartLab Studio II and Malvern Panalytical
Empyrean/Aeris under Data Collector (file-based, method-driven), Instron under Bluehill Universal (WCF backend,
template), Anton Paar MCR under RheoCompass (file-based, method-driven) and Bruker Dektak XT under Vision64 (TCP
backend, template). No vendor library is installed and there is no config.json: the real drivers must load and
read `connected` False, and the twins must run through the same gates as the real drivers.

    PYTHONPATH=. python tests/test_packages_materials_b.py      (or: python -m pytest tests/test_packages_materials_b.py -q)
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile
import time
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ["OPENMHP_HOME"] = tempfile.mkdtemp(prefix="openmhp-materials-b-")
os.environ["OPENMHP_SIM_TIME_SCALE"] = "0.0005"

from openmhp.client import LocalDevice, RemoteError      # noqa: E402
from openmhp.driver import DeviceFault                   # noqa: E402
from openmhp.package import load_driver                  # noqa: E402
from openmhp.validate import validate_path               # noqa: E402

FILE_PACKAGES = ["rigaku-smartlab-xrd", "panalytical-empyrean-xrd", "anton-paar-rheometer"]
SDK_PACKAGES = ["instron-bluehill-tester", "kla-dektak-profilometer"]
PACKAGES = FILE_PACKAGES + SDK_PACKAGES
ROOT = pathlib.Path(__file__).resolve().parents[1] / "supported-devices"


def refused(code, fn):
    try:
        fn()
        raise AssertionError(f"expected a refusal with {code}")
    except RemoteError as e:
        assert e.code == code, (e.code, str(e))
        return e


class _Broken:
    """A backend whose open() fails: what the twin looks like when the vendor software is gone."""
    def open(self):
        raise DeviceFault("link down (test)")


def twin(name):
    drv = load_driver(ROOT / name, sim=True)
    dev = LocalDevice(drv)
    assert dev.read("connected") is True
    assert dev.read("state") == "idle" and dev.read("busy") is False
    assert dev.read("calibration_status") == "unknown"                 # no record yet: says so, never guesses
    return drv, dev


def examples_dry_run(dev, drv):
    """The first example of every action that takes parameters is accepted as a dry run (confirm-gated ones
    with approval), and a confirm-gated action is refused without it."""
    for a in drv.descriptor["actions"]:
        if not a.get("params"):
            continue
        ex = a["examples"][0]
        if a.get("approval") == "confirm":
            refused(-32012, lambda: dev.invoke(a["name"], **ex))      # a real call needs a person's confirmation
        r = dev.invoke(a["name"], dry_run=True, approved=True, **ex)
        assert r["state"] == "dryRun", r


def fault_then_estop(dev, drv, signal="connected"):
    """sim/fault raise-on-read fails the next read; e-stop runs the backend's stop and latches the state."""
    assert dev.call("sim/fault", {"mode": "raise", "on": "read"})["armed"]["mode"] == "raise"
    try:
        dev.read(signal)
        raise AssertionError("the injected read fault did not fire")
    except RemoteError as e:
        assert "injected fault" in str(e), e
    if dev.read("state") != "idle":
        dev.reset()
    assert dev.read(signal) is not None                            # once only
    dev.estop("test")
    assert dev.read("state") == "estop"
    assert any("estop" in line for line in drv.hw.log), drv.hw.log


def broken_link_refuses(dev, drv, action, example):
    """An open `connected` interlock: swap in a backend that cannot open and the gate refuses with -32011."""
    good_hw, drv.hw, drv.make_backend = drv.hw, None, lambda: _Broken()
    assert dev.read("connected") is False
    refused(-32011, lambda: dev.invoke(action, approved=True, **example))
    drv.hw = good_hw
    assert dev.read("connected") is True


def test_packages_validate_and_real_drivers_load():
    for name in PACKAGES:
        v = validate_path(str(ROOT / name))
        assert v["ok"], (name, v["errors"])
        assert [w for w in v["warnings"] if "no location" not in w] == [], (name, v["warnings"])
        real = LocalDevice(load_driver(ROOT / name))           # no vendor library, no config.json
        assert real.read("connected") is False, name
        action = next(a for a in real.describe("full")["actions"] if a.get("params"))
        refused(-32011, lambda: real.invoke(action["name"], approved=True, **action["examples"][0]))
    for name in PACKAGES:                                     # every package ships one validated method record
        drv = load_driver(ROOT / name, sim=True)
        found = LocalDevice(drv).method_find("demo compound", "demo-assay")
        assert found["choice"] == "one" and found["method"]["validated"] is not None, (name, found)


def test_rigaku_smartlab_xrd_twin():
    drv, dev = twin("rigaku-smartlab-xrd")
    assert dev.read("queue_depth") == 0 and dev.read("sample_changer_position") is None and dev.read("last_result") is None
    examples_dry_run(dev, drv)
    prog = {"start_2theta": 5, "end_2theta": 60, "step": 0.02, "speed_deg_min": 10}
    refused(-32010, lambda: dev.invoke("queue_scan", approved=True, sample_id="x", position=2, program={**prog, "speed_deg_min": 500}))
    refused(-32010, lambda: dev.invoke("queue_scan", approved=True, sample_id="x", position=11, program=prog))   # changer_positions
    refused(-32010, lambda: dev.invoke("queue_scan", approved=True, sample_id="x", position=2,
                                       program={**prog, "start_2theta": 2, "end_2theta": 145, "step": 0.005, "speed_deg_min": 0.01}))  # max_scan_hours
    refused(-32014, lambda: dev.invoke("queue_scan", approved=True, sample_id="x", position=2, program={**prog, "end_2theta": 5}))
    refused(-32014, lambda: dev.invoke("queue_scan", approved=True, sample_id="../x", position=2, program=prog))
    refused(-32010, lambda: dev.invoke("queue_scan", approved=True, sample_id="x", position=2, program={**prog, "mode": "fast"}))
    broken_link_refuses(dev, drv, "queue_scan", {"sample_id": "x", "position": 2, "program": prog})
    assert dev.method_find("demo compound", "demo-assay")["method"]["name"] == "scan_5_60"
    j = dev.invoke("queue_scan", approved=True, sample_id="batch12_formA", position=2, program=prog)
    assert dev.read("busy") is True and dev.read("queue_depth") == 1              # the job file sits in the folder until taken
    r = dev.wait(j, poll=0.02)
    assert r["state"] == "done" and r["resultMismatch"] is None, r
    res = r["result"]
    assert res["points"] == 2751 and res["two_theta_range"] == [5.0, 60.0] and res["format"] == "rasx"
    assert res["target"] == "Cu" and res["voltage_kv"] == 40.0 and res["current_ma"] == 30.0 and res["scan_speed_deg_min"] == 10.0
    assert dev.read("last_result") == res and dev.read("queue_depth") == 0 and dev.read("sample_changer_position") is None
    with zipfile.ZipFile(res["file"]) as z:
        assert {"root.xml", "Data0/Profile0.txt", "Data0/MesurementConditions0.xml"} <= set(z.namelist())
    # the twin wrote the .ras beside it: parse its header and the three-column rows directly
    real = sys.modules[type(drv).__module__].real
    ras = pathlib.Path(res["file"]).with_suffix(".ras").read_bytes()
    assert ras.startswith(b"*RAS_DATA_START\r\n*RAS_HEADER_START\r\n")
    header, pts = real.parse_ras(ras.decode("ascii"))
    assert header["*FILE_SAMPLE"] == "batch12_formA" and header["*MEAS_SCAN_MODE"] == "CONTINUOUS"
    assert header["*MEAS_SCAN_START"] == "5.0000" and header["*MEAS_SCAN_STOP"] == "60.0000" and header["*MEAS_SCAN_STEP"] == "0.0200"
    assert header["*MEAS_SCAN_SPEED_UNIT"] == "deg/min" and int(header["*MEAS_DATA_COUNT"]) == len(pts) == 2751
    assert pts[0][0] == 5.0 and abs(pts[-1][0] - 60.0) < 1e-6 and all(c >= 0 for _, c in pts)
    assert max(c for a, c in pts if 25.4 < a < 25.8) > 10 * max(c for a, c in pts if 50 < a < 52)   # the 25.6 deg peak
    # a .ras with a quoted indexed key and a two-column row still parses
    h2, p2 = real.parse_ras('*RAS_DATA_START\n*RAS_HEADER_START\n*MEAS_COND_AXIS_NAME-3 "Omega"\n*RAS_HEADER_END\n'
                            '*RAS_INT_START\n10.0 5\n10.02 7 1.0\n*RAS_INT_END\n*RAS_DATA_END\n')
    assert h2 == {"*MEAS_COND_AXIS_NAME-3": "Omega"} and p2 == [(10.0, 5.0), (10.02, 7.0)]
    h3, p3 = real.parse_rasx(pathlib.Path(res["file"]).read_bytes())
    assert h3["*MEAS_COND_XG_VOLTAGE"] == "40" and len(p3) == 2751
    # cancelling before the job was taken removes the file
    job = dev.invoke("queue_scan", approved=True, sample_id="cancel_me", position=1, program=prog)
    dev.cancel(job)
    assert dev.wait(job, poll=0.02)["state"] == "cancelled"
    fault_then_estop(dev, drv)
    assert drv.hw.queue_depth() == 0


def test_panalytical_empyrean_xrd_twin():
    drv, dev = twin("panalytical-empyrean-xrd")
    assert dev.read("queue_depth") == 0 and dev.read("sample_changer_position") is None
    examples_dry_run(dev, drv)
    prog = {"start_2theta": 5, "end_2theta": 60, "step": 0.026, "time_per_step_s": 0.5}
    refused(-32010, lambda: dev.invoke("queue_scan", approved=True, sample_id="x", position=2, program={**prog, "step": 0.0005}))
    refused(-32010, lambda: dev.invoke("queue_scan", approved=True, sample_id="x", position=7, program=prog))    # changer_positions
    refused(-32010, lambda: dev.invoke("queue_scan", approved=True, sample_id="x", position=2,
                                       program={"start_2theta": 2, "end_2theta": 142, "step": 0.001, "time_per_step_s": 100}))  # max_scan_hours
    refused(-32014, lambda: dev.invoke("queue_scan", approved=True, sample_id="x", position=2, program={**prog, "end_2theta": 4}))
    refused(-32014, lambda: dev.invoke("queue_scan", approved=True, sample_id="x", position=2, program={**prog, "program_file": "../p.xrdmp"}))
    refused(-32010, lambda: dev.invoke("queue_scan", approved=True, sample_id="x", position=2, program={**prog, "scan_axis": "Phi"}))
    broken_link_refuses(dev, drv, "queue_scan", {"sample_id": "x", "position": 2, "program": prog})
    assert dev.method_find("demo compound", "demo-assay")["method"]["name"] == "gonio_5_60"
    j = dev.invoke("queue_scan", approved=True, sample_id="batch12_formA", position=2, program=prog)
    r = dev.wait(j, poll=0.02)
    assert r["state"] == "done" and r["resultMismatch"] is None, r
    res = r["result"]
    assert res["points"] == 2116 and res["two_theta_range"] == [5.0, 59.99] and res["counting_time_s"] == 0.5
    assert res["status"] == "Completed" and res["measurement_type"] == "Scan" and res["schema_version"] == "2.1"
    text = pathlib.Path(res["file"]).read_text(encoding="utf-8")
    assert 'xmlns="http://www.xrdml.com/XRDMeasurement/2.1"' in text and "<counts unit=\"counts\">" in text
    assert '<positions axis="2Theta" unit="deg"><startPosition>5.0000</startPosition>' in text
    real = sys.modules[type(drv).__module__].real
    # a schema-1.5 file with intensities and listPositions parses the same way
    old = ('<?xml version="1.0"?><xrdMeasurements xmlns="http://www.xrdml.com/XRDMeasurement/1.5" status="Completed">'
           '<xrdMeasurement measurementType="Scan" status="Completed"><scan appendNumber="0" mode="Continuous" scanAxis="Gonio" status="Aborted">'
           '<dataPoints><positions axis="2Theta" unit="deg"><listPositions>10 10.5 11</listPositions></positions>'
           '<commonCountingTime unit="seconds">2.00</commonCountingTime><intensities unit="counts">4 9 2</intensities>'
           '</dataPoints></scan></xrdMeasurement></xrdMeasurements>')
    p = real.parse_xrdml(old.encode())
    assert p["schema_version"] == "1.5" and p["points"] == 3 and p["two_theta_range"] == [10.0, 11.0] and p["status"] == "Aborted"
    assert p["counting_time_s"] == 2.0 and p["intensities"] == [4.0, 9.0, 2.0]
    try:
        real.parse_xrdml(b"<foo/>")
        raise AssertionError("not XRDML")
    except DeviceFault:
        pass
    fault_then_estop(dev, drv)
    assert drv.hw.queue_depth() == 0


def test_anton_paar_rheometer_twin():
    drv, dev = twin("anton-paar-rheometer")
    assert dev.read("hood_closed") is True and dev.read("temperature") is None and dev.read("temperature_setpoint") is None
    examples_dry_run(dev, drv)
    fc = {"shear_rate_start": 0.1, "shear_rate_end": 1000, "points": 21, "point_duration_s": 10, "log": True}
    common = dict(sample_name="batch12_gel", test_type="flow_curve", measuring_system="CP50-1", temperature_c=25)
    refused(-32010, lambda: dev.invoke("queue_test", approved=True, **{**common, "temperature_c": 250}, flow_curve=fc))
    refused(-32010, lambda: dev.invoke("queue_test", approved=True, **common, flow_curve={**fc, "shear_rate_end": 5000}))
    refused(-32010, lambda: dev.invoke("queue_test", approved=True, **common, flow_curve={**fc, "points": 200, "point_duration_s": 600}))  # max_test_hours
    refused(-32014, lambda: dev.invoke("queue_test", approved=True, **{**common, "temperature_c": 25.05}, flow_curve=fc))  # resolution 0.1
    refused(-32014, lambda: dev.invoke("queue_test", approved=True, **common))                                           # flow_curve missing
    refused(-32014, lambda: dev.invoke("queue_test", approved=True, **{**common, "measuring_system": "../x"}, flow_curve=fc))
    # the hood interlock: the lab's state file says open
    pathlib.Path(drv.cfg["hood_state_file"]).write_text("open\n")
    assert dev.read("hood_closed") is False
    refused(-32011, lambda: dev.invoke("queue_test", approved=True, **common, flow_curve=fc))
    pathlib.Path(drv.cfg["hood_state_file"]).write_text("closed\n")
    broken_link_refuses(dev, drv, "queue_test", {**common, "flow_curve": fc})
    assert dev.method_find("demo compound", "demo-assay")["method"]["name"] == "flow_curve_0p1_1000"
    j = dev.invoke("queue_test", approved=True, **common, flow_curve=fc)
    deadline = time.time() + 5
    while dev.read("temperature_setpoint") is None and time.time() < deadline:
        time.sleep(0.005)
    assert dev.read("temperature_setpoint") == 25.0 and 20 <= dev.read("temperature") <= 26       # measured follows the live export
    r = dev.wait(j, poll=0.02)
    assert r["state"] == "done" and r["resultMismatch"] is None, r
    res = r["result"]
    assert res["points"] == 21 and res["columns"][:5] == ["Point No.", "Time", "Shear Rate", "Shear Stress", "Viscosity"]
    assert res["summary"]["shear_rate"] == 1000.0 and 0.2 < res["summary"]["viscosity_pa_s"] < 0.6 and res["summary"]["storage_modulus_pa"] is None
    assert 24.5 <= res["temperature_mean_c"] <= 25.5 and dev.read("temperature_setpoint") is None
    raw = pathlib.Path(res["file"]).read_bytes()
    assert raw.startswith((b"\xff\xfe", b"\xfe\xff")) and "Interval data:\tPoint No." in raw.decode("utf-16")
    sweep = dev.wait(dev.invoke("queue_test", approved=True, sample_name="batch12_gel", test_type="frequency_sweep", measuring_system="PP25",
                                temperature_c=25, frequency_sweep={"strain_pct": 1, "frequency_start_hz": 0.1, "frequency_end_hz": 100, "points": 16}),
                     poll=0.02)["result"]
    assert sweep["points"] == 16 and sweep["summary"]["frequency_hz"] == 100.0 and sweep["summary"]["viscosity_pa_s"] is None
    assert 1000 < sweep["summary"]["storage_modulus_pa"] < 2500 and sweep["summary"]["loss_modulus_pa"] < sweep["summary"]["storage_modulus_pa"]
    real = sys.modules[type(drv).__module__].real
    p = real.parse_export("Name:\ts\nInterval and data points:\t1\t2\nInterval data:\tTime [s]\tViscosity [Pa·s]\tTemperature [°C]\n"
                          "\t1\t2,5\tn.a.\n\t2\t1.234,5\t25\n")
    assert p["columns"] == ["Time", "Viscosity", "Temperature"] and p["rows"] == [[1.0, 2.5, None], [2.0, 1234.5, 25.0]]
    fault_then_estop(dev, drv)
    assert drv.hw.queue_depth() == 0


def test_instron_bluehill_tester_twin():
    drv, dev = twin("instron-bluehill-tester")
    assert dev.read("crosshead_state") == "ready" and dev.read("frame_ready") is True and dev.read("load") == 0.0
    examples_dry_run(dev, drv)
    spec = {"label": "batch12_bar3", "width_mm": 10, "thickness_mm": 2, "gauge_length_mm": 50}
    lim = {"max_load_N": 2000, "max_extension_mm": 100}
    common = dict(bluehill_method="Tensile_ASTM_D638.im_tens", specimen=spec, rate_mm_min=5, limits=lim)
    refused(-32010, lambda: dev.invoke("run_test", approved=True, **{**common, "rate_mm_min": 5000}))
    refused(-32010, lambda: dev.invoke("run_test", approved=True, **{**common, "limits": {**lim, "max_load_N": 6000}}))   # config load_cell_N 5000
    refused(-32010, lambda: dev.invoke("run_test", approved=True, **{**common, "limits": {**lim, "max_extension_mm": 1000}}))
    refused(-32014, lambda: dev.invoke("run_test", approved=True, **{**common, "bluehill_method": "..\\x.im_tens"}))
    refused(-32014, lambda: dev.invoke("run_test", approved=True, **{**common, "specimen": {**spec, "label": "bad/label"}}))
    broken_link_refuses(dev, drv, "run_test", common)
    assert dev.method_find("demo compound", "demo-assay")["method"]["name"] == "tensile_d638_5mm_min"
    j = dev.invoke("run_test", approved=True, **common)
    deadline = time.time() + 5
    while dev.read("extension") < 1.0 and time.time() < deadline:
        time.sleep(0.005)
    assert dev.read("crosshead_state") == "testing" and dev.read("frame_ready") is False and dev.read("load") > 100
    refused(-32011, lambda: dev.invoke("run_test", approved=True, **common))                 # the frame is busy testing
    r = dev.wait(j, poll=0.02)
    assert r["state"] == "done" and r["resultMismatch"] is None, r
    res = r["result"]
    assert res["end_reason"] == "break" and 1300 < res["peak_load_N"] < 1450 and 1900 < res["modulus_MPa"] < 2100
    assert 0.11 < res["strain_at_break"] < 0.13 and abs(res["stress_at_peak_MPa"] - res["peak_load_N"] / 20) < 0.01
    text = pathlib.Path(res["file"]).read_text()
    assert "Maximum Force,Modulus (Automatic Young's)" in text and "(N),(MPa)" in text and pathlib.Path(res["raw_file"]).is_file()
    assert any(s.startswith("StartTest Tensile_ASTM_D638.im_tens batch12_bar3_mhp_") for s in drv.hw.log)
    assert dev.read("crosshead_state") == "ready" and dev.read("last_result") == res
    lim_run = dev.wait(dev.invoke("run_test", approved=True, **{**common, "limits": {**lim, "max_load_N": 500}}), poll=0.02)["result"]
    assert lim_run["end_reason"] == "limit" and 495 < lim_run["peak_load_N"] < 520 and lim_run["strain_at_break"] is None
    # cancelling a running test stops the crosshead
    job = dev.invoke("run_test", approved=True, **common)
    deadline = time.time() + 5
    while dev.read("extension") < 0.5 and time.time() < deadline:
        time.sleep(0.005)
    dev.cancel(job)
    assert dev.wait(job, poll=0.02)["state"] == "cancelled" and "StopTest" in drv.hw.log
    assert dev.wait(dev.invoke("stop_crosshead"))["result"] == {"stopped": True}
    real = sys.modules[type(drv).__module__].real
    vals = real.parse_results_csv("Sample name,s,\n\nSpecimen label,Maximum Load,Modulus (Automatic Young's)\n,(N),(MPa)\nA,12.5,2000\nB,14,2100\n",
                                  {**real.COLUMN_DEFAULTS, "peak_load": "Maximum Load"}, "A")
    assert vals["peak_load"] == 12.5 and vals["modulus"] == 2000.0 and vals["strain_at_break"] is None
    fault_then_estop(dev, drv, "load")
    assert drv.hw.log[-3:] == ["StopTest", "DisableFrame", "estop: stop crosshead, disable frame"]
    assert dev.read("crosshead_state") == "disabled" and dev.read("frame_ready") is False


def test_kla_dektak_profilometer_twin():
    drv, dev = twin("kla-dektak-profilometer")
    assert dev.read("status") == "idle"
    examples_dry_run(dev, drv)
    common = dict(recipe="step_height_2um.visrcp", sample_id="wafer12_die3", length_um=1000, force_mg=3, speed_um_s=100)
    refused(-32010, lambda: dev.invoke("scan", approved=True, **{**common, "force_mg": 20}))
    refused(-32010, lambda: dev.invoke("scan", approved=True, **{**common, "length_um": 55000, "speed_um_s": 1}))   # max_duration_s
    refused(-32014, lambda: dev.invoke("scan", approved=True, **{**common, "force_mg": 3.001}))                      # resolution 0.01
    refused(-32014, lambda: dev.invoke("scan", approved=True, **{**common, "length_um": 100, "speed_um_s": 100}))    # under 3 s
    refused(-32014, lambda: dev.invoke("scan", approved=True, **{**common, "recipe": "step.txt"}))
    refused(-32010, lambda: dev.invoke("scan", approved=True, **{**common, "range": "2mm"}))
    broken_link_refuses(dev, drv, "scan", common)
    assert dev.method_find("demo compound", "demo-assay")["method"]["name"] == "step_height_1mm"
    j = dev.invoke("scan", approved=True, **common)
    deadline = time.time() + 5
    while dev.read("status") != "scanning" and time.time() < deadline:
        time.sleep(0.002)
    assert dev.read("status") == "scanning" and dev.read("busy") is True
    r = dev.wait(j, poll=0.02)
    assert r["state"] == "done" and r["resultMismatch"] is None, r
    res = r["result"]
    assert 490 < res["step_height_nm"] < 510 and res["scan_length_um"] == 1000.0 and res["stylus_force_mg"] == 3.0
    assert pathlib.Path(res["file"]).read_bytes().startswith(b"VCA DATA\x01\x00\x00\x55") and res["file"].endswith(".OPDx")
    db = pathlib.Path(res["db_file"]).read_text()
    assert db.startswith("Date,Time,Sample ID,Recipe,Scan Length (um),Stylus Force (mg),ASH") and "wafer12_die3_mhp_" in db
    assert any(s.startswith("SET Duration 10.0") for s in drv.hw.log) and any(s.startswith("SET Profile Hills and Valleys") for s in drv.hw.log)
    assert dev.read("status") == "idle" and dev.read("last_result") == res
    assert dev.wait(dev.invoke("tower_up"))["result"] == {"tower": "home"}
    # a second scan at higher force logs a slightly lower step (the twin's film compresses)
    soft = dev.wait(dev.invoke("scan", approved=True, **{**common, "force_mg": 15, "sample_id": "soft"}), poll=0.02)["result"]
    assert soft["step_height_nm"] < res["step_height_nm"]
    real = sys.modules[type(drv).__module__].real
    assert real.db_row("Sample ID,ASH\nA,1\nB,2\nA,3\n", real.COLUMN_DEFAULTS, "A") == {"Sample ID": "A", "ASH": "3"}
    assert real.db_row("Other,ASH\nA,1\n", real.COLUMN_DEFAULTS, "A") is None
    # cancelling a running scan aborts and raises the tower
    job = dev.invoke("scan", approved=True, **{**common, "sample_id": "cancel_me"})
    deadline = time.time() + 5
    while dev.read("status") != "scanning" and time.time() < deadline:
        time.sleep(0.002)
    dev.cancel(job)
    assert dev.wait(job, poll=0.02)["state"] == "cancelled" and drv.hw.log[-2:] == ["ABORT -> OK", "TOWER_HOME -> OK"]
    fault_then_estop(dev, drv, "status")
    assert drv.hw.log[-3:] == ["ABORT -> OK", "TOWER_HOME -> OK", "estop: abort, tower up"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
