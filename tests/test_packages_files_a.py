"""File-based pharma packages, wave A: LC-MS worklist builder, Bruker NMR under ICON-NMR, Bruker D8 PXRD under
DIFFRAC.SUITE, TA DSC/TGA under TRIOS. The real drivers load with no config.json (connected reads False), the
twins write the vendor files into temp folders and run through the same gates as the real drivers.

    PYTHONPATH=. python tests/test_packages_files_a.py
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ["OPENMHP_HOME"] = tempfile.mkdtemp(prefix="openmhp-files-a-")
os.environ["OPENMHP_SIM_TIME_SCALE"] = "0.0005"

from openmhp.client import LocalDevice, RemoteError      # noqa: E402
from openmhp.package import load_driver                  # noqa: E402
from openmhp.validate import validate_path               # noqa: E402

PACKAGES = ["lcms-worklist", "bruker-nmr-iconnmr", "bruker-d8-pxrd", "ta-dsc-tga"]
ROOT = pathlib.Path(__file__).resolve().parents[1] / "supported-devices"


def refused(code, fn):
    try:
        fn()
        raise AssertionError(f"expected a refusal with {code}")
    except RemoteError as e:
        assert e.code == code, (e.code, str(e))
        return e


def twin(name):
    drv = load_driver(ROOT / name, sim=True)
    dev = LocalDevice(drv)
    assert dev.read("connected") is True
    assert dev.read("state") == "idle" and dev.read("busy") is False
    assert dev.read("calibration_status") in ("valid", "due", "overdue", "unknown")
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
        r = dev.invoke(a["name"], dry_run=True, **ex)                 # a dry run checks the parameters only
        assert r["state"] == "dryRun", r


def fault_then_estop(dev, drv):
    """sim/fault raise-on-read fails the next read; e-stop runs the backend's abort and latches the state."""
    dev.call("sim/fault", {"mode": "raise", "on": "read"})
    try:
        dev.read("connected")
        raise AssertionError("the injected read fault did not fire")
    except RemoteError:
        pass
    assert dev.read("connected") is True                       # once only
    dev.estop("test")
    assert dev.read("state") == "estop"
    assert any("estop" in line for line in drv.hw.log), drv.hw.log


def test_packages_validate_and_real_drivers_load():
    for name in PACKAGES:
        v = validate_path(str(ROOT / name))
        assert v["ok"], (name, v["errors"])
        assert [w for w in v["warnings"] if "no location" not in w] == [], (name, v["warnings"])
        real = LocalDevice(load_driver(ROOT / name))           # no config.json: nothing to write into
        assert real.read("connected") is False, name
        action = real.describe("full")["actions"][0]
        refused(-32011, lambda: real.invoke(action["name"], approved=True, **action["examples"][0]))


def test_lcms_worklist_twin():
    drv, dev = twin("lcms-worklist")
    assert dev.read("vendor") == "masslynx" and dev.read("last_worklist") is None
    examples_dry_run(dev, drv)
    sample = {"name": "s1", "position": "1:A,1", "injection_volume_ul": 5, "ms_method": "Assay_C18_pos"}
    refused(-32010, lambda: dev.invoke("build_worklist", samples=[{**sample, "injection_volume_ul": 500}]))
    refused(-32014, lambda: dev.invoke("build_worklist", samples=[{**sample, "flow": 2}]))
    refused(-32014, lambda: dev.invoke("build_worklist", samples=[sample, {**sample, "name": "s2", "position": "1:A,2"}],
                                       worklist_name="bad/name"))
    # a saved method carries the method names; the samples come from the call
    found = dev.method_find("demo compound", "demo-assay")
    assert found["choice"] == "one" and found["method"]["name"] == "assay_c18_pos"
    j = dev.invoke("build_worklist", samples=[{"name": "blank", "position": "1:A,1", "sample_type": "blank"},
                                              {"name": "std 1", "position": "1:A,2", "sample_type": "standard"},
                                              {"name": "batch12", "position": "1:A,3"}],
                   ms_method="Assay_C18_pos", lc_method="Assay_C18_grad")
    r = dev.wait(j, poll=0.02)
    assert r["state"] == "done" and r["resultMismatch"] is None, r
    res = r["result"]
    assert res["vendor"] == "masslynx" and res["rows"] == 3 and res["samples"] == 3
    text = pathlib.Path(res["file"]).read_bytes().decode("utf-8")
    lines = text.split("\r\n")
    assert lines[0] == "FILE_NAME,FILE_TEXT,MS_FILE,MS_TUNE_FILE,INLET_FILE,SAMPLE_LOCATION,TYPE,ID,INJ_VOL,Index"
    assert lines[1].endswith(",Blank,blank,5,1") and "Assay_C18_grad" in lines[1]
    assert '"1:A,1"' in lines[1]                                # the comma in the position is quoted
    import csv
    rows = list(csv.DictReader(lines))
    assert [row["TYPE"] for row in rows] == ["Blank", "Standard", "Analyte"] and rows[1]["SAMPLE_LOCATION"] == "1:A,2"
    assert dev.read("last_worklist") == res["file"]
    try:                                                         # a method alone (no samples) is not a run
        dev.wait(dev.invoke("build_worklist", samples=[], ms_method="x"), poll=0.02)
        raise AssertionError("an empty worklist was written")
    except RemoteError as e:
        assert "at least one sample" in str(e), e
    dev.reset()
    # every other vendor renders and reads back through the same code
    for vendor, first in (("xcalibur", "Bracket Type=4"), ("masshunter", "﻿Sample Name,Barcode"),
                          ("sciexos", "Sample Name,Sample ID")):
        drv.cfg["vendor"] = vendor
        drv.hw = None
        r = dev.wait(dev.invoke("build_worklist", samples=[sample, {**sample, "name": "s2", "position": "1:A,2",
                                                                      "sample_type": "qc"}]), poll=0.02)
        assert r["result"]["rows"] == 2 and r["result"]["vendor"] == vendor
        head = pathlib.Path(r["result"]["file"]).read_bytes().decode("utf-8").split("\r\n")[0]
        assert head.startswith(first), (vendor, head)
    # the interlock: a vanished output folder opens `connected`
    drv.cfg["output_dir"] = str(pathlib.Path(drv.cfg["output_dir"]) / "gone")
    drv.hw = None
    assert dev.read("connected") is False
    refused(-32011, lambda: dev.invoke("build_worklist", samples=[sample]))
    drv.cfg["output_dir"] = str(pathlib.Path(drv.cfg["output_dir"]).parent)
    drv.hw = None
    assert dev.read("connected") is True
    fault_then_estop(dev, drv)


def test_bruker_nmr_iconnmr_twin():
    drv, dev = twin("bruker-nmr-iconnmr")
    assert dev.read("queue_depth") == 0 and dev.read("sample_changer_position") is None and dev.read("last_result") is None
    examples_dry_run(dev, drv)
    base = dict(experiment="PROTON", holder=3, solvent="CDCl3")
    refused(-32010, lambda: dev.invoke("queue_experiment", approved=True, **{**base, "holder": 99}))
    refused(-32010, lambda: dev.invoke("queue_experiment", approved=True, **{**base, "ns": 0}))
    refused(-32010, lambda: dev.invoke("queue_experiment", approved=True, **{**base, "solvent": "water"}))
    refused(-32014, lambda: dev.invoke("queue_experiment", approved=True, **{**base, "title": "a\tb"}))
    refused(-32015, lambda: dev.invoke("queue_experiment", approved=True))                # a method or params
    j = dev.invoke("queue_experiment", approved=True, **base, ns=16, d1_s=1.0, title="batch12 crude")
    deadline = time.time() + 5
    while dev.read("sample_changer_position") is None and time.time() < deadline:
        time.sleep(0.005)
    assert dev.read("sample_changer_position") == 3 and dev.read("busy") is True
    r = dev.wait(j, poll=0.02)
    assert r["state"] == "done" and r["resultMismatch"] is None, r
    res = r["result"]
    assert res["expno"] == 1 and res["holder"] == 3 and res["acqus"] == {"NS": 16, "SW": 20.0, "O1": 2470.0, "TD": 65536}
    assert f"{res['dataset']}/1/pdata/1/1r" in res["files"] and f"{res['dataset']}/1/acqus" in res["files"]
    d = pathlib.Path(drv.cfg["data_dir"]) / res["dataset"] / "1"
    assert "##$NS= 16" in (d / "acqus").read_text() and (d / "pdata" / "1" / "title").read_text().strip() == "batch12 crude"
    assert dev.read("sample_changer_position") is None and dev.read("last_result") == res
    assert dev.read("queue_depth") == 0                        # the fake ICON-NMR consumed the job file
    # a second experiment under the same dataset takes the next expno
    r2 = dev.wait(dev.invoke("queue_experiment", approved=True, **base, dataset=res["dataset"]), poll=0.02)["result"]
    assert r2["expno"] == 2
    # e-stop while a job waits: the queued file is removed and the job fails
    drv.cfg["lock_shim_s"] = 10 ** 7                           # the twin's clock does not move
    drv.cfg["result_wait_s"] = 10 ** 8                         # and the driver keeps waiting
    drv.hw.jobs.clear()
    job = dev.invoke("queue_experiment", approved=True, **base)
    deadline = time.time() + 5
    while dev.read("queue_depth") == 0 and time.time() < deadline:
        time.sleep(0.005)
    fault_then_estop(dev, drv)
    try:                                                       # the e-stop cancels the waiting job (or fails it)
        assert dev.wait(job, poll=0.02)["state"] == "cancelled"
    except RemoteError as e:
        assert "stopped" in str(e), e
    assert drv.hw.queue_depth() == 0


def test_bruker_d8_pxrd_twin():
    drv, dev = twin("bruker-d8-pxrd")
    assert dev.read("queue_depth") == 0 and dev.read("sample_changer_position") is None
    examples_dry_run(dev, drv)
    prog = {"start_2theta": 3, "end_2theta": 40, "step": 0.02, "time_per_step_s": 0.5}
    refused(-32010, lambda: dev.invoke("queue_scan", approved=True, sample_id="x", position=2, program={**prog, "step": 0.5}))
    refused(-32010, lambda: dev.invoke("queue_scan", approved=True, sample_id="x", position=12, program=prog))
    refused(-32014, lambda: dev.invoke("queue_scan", approved=True, sample_id="x", position=2, program={**prog, "end_2theta": 3}))
    refused(-32014, lambda: dev.invoke("queue_scan", approved=True, sample_id="../x", position=2, program=prog))
    refused(-32010, lambda: dev.invoke("queue_scan", approved=True, sample_id="x", position=2,
                                       program={"start_2theta": 2, "end_2theta": 70, "step": 0.01,
                                                "time_per_step_s": 10}))                            # max_scan_hours
    assert dev.method_find("demo compound", "demo-assay")["method"]["name"] == "form_screen_3_40"
    j = dev.invoke("queue_scan", approved=True, sample_id="batch12_formA", position=2, program=prog)
    r = dev.wait(j, poll=0.02)
    assert r["state"] == "done" and r["resultMismatch"] is None, r
    res = r["result"]
    assert res["points"] == 1851 and res["two_theta_range"] == [3.0, 40.0] and res["file"].endswith(".brml")
    assert res["xy_file"].endswith(".xy") and pathlib.Path(res["xy_file"]).read_text().startswith("3.0000 ")
    import zipfile
    with zipfile.ZipFile(res["file"]) as z:
        assert "Experiment0/RawData0.xml" in z.namelist()
    # the .xy fallback when the .brml holds no data
    real = sys.modules[type(drv).__module__].real
    assert real.parse_xy("# header\n3.0 10\n3.02\t12\n") == [(3.0, 10.0), (3.02, 12.0)]
    fault_then_estop(dev, drv)


def test_ta_dsc_tga_twin():
    drv, dev = twin("ta-dsc-tga")
    assert dev.read("queue_depth") == 0 and dev.read("sample_temperature") is None
    examples_dry_run(dev, drv)
    seg = {"type": "ramp", "rate_k_min": 10, "to_c": 300}
    common = dict(sample_name="batch12 formA", pan_position=4, mass_mg=3.2)
    refused(-32010, lambda: dev.invoke("queue_run", approved=True, **common, instrument="dsc",
                                       program={"segments": [{**seg, "to_c": 700}]}))                 # DSC limit
    refused(-32010, lambda: dev.invoke("queue_run", approved=True, **common, instrument="tga",
                                       program={"segments": [{**seg, "to_c": 1200}]}))                # shape limit
    refused(-32010, lambda: dev.invoke("queue_run", approved=True, **{**common, "mass_mg": 500}, instrument="dsc",
                                       program={"segments": [seg]}))
    refused(-32014, lambda: dev.invoke("queue_run", approved=True, **common, instrument="dsc",
                                       program={"segments": [{"type": "ramp", "to_c": 300}]}))        # a ramp needs a rate
    refused(-32014, lambda: dev.invoke("queue_run", approved=True, **common, instrument="dsc", program={"segments": []}))
    assert dev.method_find("demo compound", "demo-assay")["method"]["name"] == "dsc_10k_to_300"
    j = dev.invoke("queue_run", approved=True, **common, instrument="dsc", program={"segments": [seg]})
    deadline = time.time() + 5
    while dev.read("sample_temperature") is None and time.time() < deadline:
        time.sleep(0.005)
    assert 25 <= dev.read("sample_temperature") <= 300
    r = dev.wait(j, poll=0.02)
    assert r["state"] == "done" and r["resultMismatch"] is None, r
    res = r["result"]
    assert res["points"] > 100 and 160 <= res["peak_c"] <= 172 and 150 <= res["onset_c"] <= 168 and res["mass_loss_pct"] is None
    text = pathlib.Path(res["file"]).read_bytes().decode("utf-8")
    assert "[step]" in text and "Time\tTemperature\tHeat Flow (Normalized)" in text and "Sample name\tbatch12 formA" in text
    tga = dev.wait(dev.invoke("queue_run", approved=True, sample_name="batch12 formA", mass_mg=8.5, instrument="tga",
                              program={"segments": [{"type": "isothermal", "to_c": 30, "hold_min": 5},
                                                    {"type": "ramp", "rate_k_min": 10, "to_c": 600}]}), poll=0.02)["result"]
    assert 40 <= tga["mass_loss_pct"] <= 44 and 300 <= tga["peak_c"] <= 320 and tga["onset_c"] < tga["peak_c"]
    assert dev.read("last_result") == tga
    fault_then_estop(dev, drv)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
