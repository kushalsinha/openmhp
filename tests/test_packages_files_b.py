"""File-based vendor-software routes, wave B: Agilent Cary UV-Vis/FTIR (Cary WinUV / MicroLab), ProteinSimple
Maurice (Compass for iCE), QuantStudio 5/7 (Design & Analysis) and Cytek Aurora (SpectroFlo).

Each package writes a request file into a watched folder and waits for the vendor software's export. The real
drivers load with no vendor library and no config.json and answer `connected` False; the twins play the
instrument PC, write the export files in the documented formats, and run through every gate.
"""
from __future__ import annotations

import os
import struct
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["OPENMHP_HOME"] = tempfile.mkdtemp(prefix="openmhp-files-b-")     # job records and twin folders stay out of ~/.openmhp
os.environ["OPENMHP_SIM_TIME_SCALE"] = "0.0005"

from openmhp.client import LocalDevice, RemoteError            # noqa: E402
from openmhp.package import load_driver                        # noqa: E402
from openmhp.validate import validate_path                     # noqa: E402

REPO = Path(__file__).resolve().parents[1]
PACKAGES = {
    "agilent-cary-uvvis-ftir": "scan",
    "protein-simple-maurice-ce": "queue_run",
    "thermo-quantstudio-qpcr": "queue_run",
    "cytek-aurora-flow-cytometer": "queue_acquisition",
}


def _refused(code, fn):
    try:
        fn()
        raise AssertionError(f"expected a refusal with {code}")
    except RemoteError as e:
        assert e.code == code, e
        return e


def _twin(name):
    drv = load_driver(REPO / "supported-devices" / name, sim=True)
    return drv, LocalDevice(drv)


def _wait_busy(dev, want=True, within=5.0):
    deadline = time.time() + within
    while dev.read("busy") is not want and time.time() < deadline:
        time.sleep(0.005)


def test_packages_validate_and_real_drivers_load_without_vendor_software():
    for name, action in PACKAGES.items():
        folder = REPO / "supported-devices" / name
        v = validate_path(str(folder))
        assert v["ok"], (name, v["errors"])
        assert [w for w in v["warnings"] if "no location" not in w] == [], (name, v["warnings"])
        real = LocalDevice(load_driver(folder))                      # no config.json: folders unknown
        assert real.read("connected") is False
        assert real.read("state") == "idle" and real.read("busy") is False
        spec = next(a for a in real.describe()["actions"] if a["name"] == action)
        assert spec["methods"] is True and spec["approval"] == "confirm" and isinstance(spec["returns"], dict)
        assert real.call("methods/find", {"compound": "x"})["choice"] in ("none", "one", "several")


def test_common_gates_on_every_twin():
    """Reserved signals, the first example as a dry run, approval, the connected interlock, fault injection, e-stop."""
    for name, action in PACKAGES.items():
        drv, dev = _twin(name)
        assert dev.read("state") == "idle" and dev.read("busy") is False and dev.read("connected") is True
        assert dev.read("calibration_status") == "unknown" and dev.read("queue_depth") == 0
        assert dev.read("last_result") is None
        examples = next(a for a in drv.descriptor["actions"] if a["name"] == action)["examples"]
        assert examples, name
        for ex in examples:
            assert dev.invoke(action, dry_run=True, **ex)["state"] == "dryRun", (name, ex)
        _refused(-32012, lambda: dev.invoke(action, **examples[0]))                   # a person confirms
        _refused(-32040, lambda: dev.read("no_such_signal"))
        # the interlock: the share with the watched folders drops
        drv.hw.folders_ok = False
        assert dev.read("connected") is False
        _refused(-32011, lambda: dev.invoke(action, approved=True, **examples[0]))
        drv.hw.folders_ok = True
        assert dev.read("connected") is True
        # a method saved under _shared is found and dry-runs with overrides
        found = dev.call("methods/list", {"action": action})
        assert found["count"] >= 1, name
        m = found["methods"][0]
        j = dev.call("actions/invoke", {"name": action, "method": {"name": m["name"], "project": m["project"]},
                                        "dryRun": True})["job"]
        assert j["state"] == "dryRun" and j["method"]["name"] == m["name"]
        # fault injection: the next read fails and the twin stays usable afterwards
        assert dev.call("sim/fault", {"mode": "raise", "on": "read"})["armed"]["mode"] == "raise"
        try:
            dev.read("queue_depth")
            raise AssertionError("expected the injected fault")
        except RemoteError:
            pass
        assert dev.read("queue_depth") == 0
        # e-stop while a request waits: the request is withdrawn, the job is cancelled, state reads estop
        drv.hw.hold = True                                           # nobody at the instrument PC
        job = dev.invoke(action, approved=True, **examples[0])
        deadline = time.time() + 5
        while dev.read("queue_depth") != 1 and time.time() < deadline:        # the worker writes the request
            time.sleep(0.005)
        assert dev.read("queue_depth") == 1 and dev.read("busy") is True
        dev.estop()
        assert dev.read("state") == "estop"
        assert dev.wait(job)["state"] == "cancelled"
        assert any(line.startswith("withdraw ['mhp_") for line in drv.hw.log), drv.hw.log
        assert dev.read("queue_depth") == 0
        drv.close()


def test_cary_scan_writes_request_and_reads_the_csv_export():
    drv, dev = _twin("agilent-cary-uvvis-ftir")
    _refused(-32010, lambda: dev.invoke("scan", approved=True, sample_name="x", mode="uvvis", start=150, stop=340))
    _refused(-32010, lambda: dev.invoke("scan", approved=True, sample_name="x", mode="ftir", start=4000, stop=650, step=50))
    _refused(-32014, lambda: dev.invoke("scan", approved=True, sample_name="x", mode="ftir", start=4000, stop=650, step=3))
    _refused(-32014, lambda: dev.invoke("scan", approved=True, sample_name="../x", mode="uvvis", start=240, stop=340))
    _refused(-32014, lambda: dev.invoke("scan", approved=True, sample_name="x", mode="uvvis", start=240, stop=245))
    r = dev.wait(dev.invoke("scan", approved=True, sample_name="mAb lot 12 A280", mode="uvvis", start=240, stop=340, step=1, baseline=True))
    assert r["state"] == "done" and r.get("resultMismatch") is None, r
    res = r["result"]
    assert res["points"] == 101 and res["x_unit"] == "nm" and res["y_unit"] == "Abs"
    assert abs(res["lambda_max_nm"] - 280) <= 2 and 0.5 < res["max_abs"] < 1.2
    text = Path(res["file"]).read_text()
    assert text.splitlines()[1] == "Wavelength (nm),Abs" and "mhp_" in text.splitlines()[0]
    assert any(l.startswith("request mhp_") for l in drv.hw.log)
    assert dev.read("last_result")["sample_name"] == "mAb lot 12 A280"
    r = dev.wait(dev.invoke("scan", approved=True, sample_name="excipient ID", mode="ftir", start=4000, stop=650, step=4))
    assert r.get("resultMismatch") is None and r["result"]["x_unit"] == "/cm" and r["result"]["lambda_max_nm"] is None
    assert abs(r["result"]["points"] - ((4000 - 650) / 4 + 1)) <= 1            # 837.5 intervals: the twin rounds
    assert Path(r["result"]["file"]).read_text().splitlines()[2].startswith("4000.00,")
    # the parser copes with the real-world variants: title lines, quoted headers, a stray blank line
    from openmhp.package import load_package
    mod = sys.modules[type(drv).__mro__[1].__module__]
    parsed = mod.parse_spectrum_csv('Sample\n"Wavelength (nm)","Abs"\n\n300.0,0.5\n301.0,0.7\n', "uvvis")
    assert parsed == {"points": 2, "x_unit": "nm", "y_unit": "Abs", "max_abs": 0.7, "lambda_max_nm": 301.0, "x_min": 300.0, "x_max": 301.0}
    assert dev.read("usage_count") == 2
    drv.close()


def test_maurice_queue_run_reads_the_peak_table():
    drv, dev = _twin("protein-simple-maurice-ce")
    assert dev.read("cartridge_present") is True
    _refused(-32010, lambda: dev.invoke("queue_run", approved=True, sample_name="x", position="A1", method="m", replicates=4))
    _refused(-32014, lambda: dev.invoke("queue_run", approved=True, sample_name="x", position="A13", method="m"))
    _refused(-32014, lambda: dev.invoke("queue_run", approved=True, sample_name="x", position="A1", method="m", injections=2))
    r = dev.wait(dev.invoke("queue_run", approved=True, sample_name="mAb-7 lot 23", position="A1", method="cIEF_mAb_pH3-10", replicates=2))
    assert r["state"] == "done" and r.get("resultMismatch") is None, r
    res = r["result"]
    assert len(res["peaks"]) == 8 and {p["label"] for p in res["peaks"]} == {"Acidic 1", "Acidic 2", "Main", "Basic 1"}
    assert 55 < res["main_peak_pct"] < 70 and all(8 < p["position"] < 9 for p in res["peaks"])
    batch_lines = [l for l in drv.hw.log if l.startswith("batch mhp_")]
    assert batch_lines and res["file"].endswith("_peaks.csv")
    r = dev.wait(dev.invoke("queue_run", approved=True, sample_name="reduced", position="B3", method="CE-SDS_reduced_25min"))
    assert r.get("resultMismatch") is None and [p["label"] for p in r["result"]["peaks"]] == ["LC", "HC", "Main", "HMW"]
    assert 90 < r["result"]["main_peak_pct"] < 100 and r["result"]["duration_s"] > 2000
    mod = sys.modules[type(drv).__mro__[1].__module__]
    peaks = mod.parse_peak_table("Sample Name\tPeak\tApparent MW\tArea\tArea %\nx mhp_t\t\t148.2\t1000\t95.5\ny\t\t1\t1\t1\n", "mhp_t")
    assert peaks == [{"label": None, "position": 148.2, "area": 1000.0, "area_pct": 95.5}]
    assert mod.main_peak_pct([]) is None
    drv.close()


def test_quantstudio_queue_run_writes_the_plate_setup_and_reads_results():
    drv, dev = _twin("thermo-quantstudio-qpcr")
    ex = next(a for a in drv.descriptor["actions"] if a["name"] == "queue_run")["examples"][0]
    assert dev.read("block_temperature") is None and dev.read("run_state") == "idle"
    _refused(-32010, lambda: dev.invoke("queue_run", approved=True, **{**ex, "plate_setup": [{"well": "A1", "sample": "s", "target": "t", "task": "BAD"}]}))
    _refused(-32010, lambda: dev.invoke("queue_run", approved=True, **{**ex, "program": {"stages": [{"steps": [{"temp": 120, "hold_s": 1}], "cycles": 1}]}}))
    _refused(-32010, lambda: dev.invoke("queue_run", approved=True, **{**ex, "program": {"stages": [{"steps": [{"temp": 95, "hold_s": 1}], "cycles": 61}]}}))
    _refused(-32014, lambda: dev.invoke("queue_run", approved=True, **{**ex, "plate_setup": ex["plate_setup"] + [{"well": "A1", "sample": "dup", "target": "GAPDH"}]}))
    _refused(-32014, lambda: dev.invoke("queue_run", approved=True, **{**ex, "template": "x.eds"}))
    job = dev.invoke("queue_run", approved=True, **ex)
    deadline = time.time() + 5
    while dev.read("run_state") == "idle" and time.time() < deadline:          # the worker writes the plate first
        time.sleep(0.005)
    assert dev.read("run_state") in ("running", "queued")
    r = dev.wait(job)
    assert r["state"] == "done" and r.get("resultMismatch") is None, r
    res = r["result"]
    assert res["wells"] == 3 and [x["well"] for x in res["results"]] == ["A1", "A2", "A3"]
    ntc = res["results"][2]
    assert ntc["sample"] == "NTC" and ntc["ct"] is None and ntc["amp_status"] == "No Amp" and ntc["quantity"] is None
    assert all(20 < x["ct"] < 30 and x["amp_status"] == "Amp" for x in res["results"][:2])
    assert 2000 < res["duration_s"] < 4000                       # 3 min + 40 cycles of (1+20 s, 20+20 s) with 20 s ramps
    assert any(l.startswith("plate mhp_") and "_plate_setup.txt" in l for l in drv.hw.log)
    assert dev.read("run_state") == "idle"
    mod = sys.modules[type(drv).__mro__[1].__module__]
    rows = mod.parse_results("Block Type,96-Well\n\nWell,Sample Name,Target Name,Cq,Amp Status\n1,s mhp_t,GAPDH,Undetermined,N/A\n2,other,GAPDH,20.1,Amp\n", "mhp_t")
    assert rows == [{"well": "1", "sample": "s", "target": "GAPDH", "ct": None, "quantity": None, "amp_status": "N/A"}]
    drv.close()


def test_aurora_queue_acquisition_writes_a_worklist_and_reads_fcs31():
    drv, dev = _twin("cytek-aurora-flow-cytometer")
    assert dev.read("sheath_level_ok") is True
    _refused(-32010, lambda: dev.invoke("queue_acquisition", approved=True, sample_name="x", position="A1", stop_events=10))
    _refused(-32010, lambda: dev.invoke("queue_acquisition", approved=True, sample_name="x", position="A1", flow_rate="fast"))
    _refused(-32014, lambda: dev.invoke("queue_acquisition", approved=True, sample_name="x", position="Z9"))
    r = dev.wait(dev.invoke("queue_acquisition", approved=True, sample_name="lot 42 viability", position="A1",
                            template="Viability_7AAD", stop_events=10000, flow_rate="medium"))
    assert r["state"] == "done" and r.get("resultMismatch") is None, r
    res = r["result"]
    assert res["events"] == 10000 and res["parameters"] == 10 and res["channels"][:2] == ["Time", "FSC-A"]
    assert res["stats_file"].endswith("_stats.csv") and res["fcs_file"].endswith(".fcs")
    raw = Path(res["fcs_file"]).read_bytes()
    assert raw[:10] == b"FCS3.1    " and len(raw[:58]) == 58
    text_begin, text_end, data_begin, data_end = (int(raw[a:b]) for a, b in ((10, 18), (18, 26), (26, 34), (34, 42)))
    assert text_begin == 58 and raw[text_begin:text_begin + 1] == b"/"
    assert data_end - data_begin + 1 == 10000 * 10 * 4
    first_event = struct.unpack("<10f", raw[data_begin:data_begin + 40])
    assert first_event[0] >= 0 and first_event[1] > 0
    text = raw[text_begin:text_end + 1].decode()
    for kw in ("$BEGINANALYSIS", "$BEGINDATA", "$BEGINSTEXT", "$BYTEORD/1,2,3,4/", "$DATATYPE/F/", "$ENDANALYSIS",
               "$ENDDATA", "$ENDSTEXT", "$MODE/L/", "$NEXTDATA/0/", "$PAR/10/", "$TOT/10000/", "$P1B/32/", "$P1E/0,0/",
               "$P1N/Time/", "$P1R/", "$P10N/R1-A/"):
        assert kw in text, kw
    # the time criterion stops first
    r = dev.wait(dev.invoke("queue_acquisition", approved=True, sample_name="unstained", position="T1", template=None,
                            stop_events=1000000, stop_time_s=10, flow_rate="low"))
    assert r.get("resultMismatch") is None and r["result"]["events"] == 8000
    # an export still being written (DATA shorter than $TOT x $PAR x 4) is refused as incomplete
    mod = sys.modules[type(drv).__mro__[1].__module__]
    short = Path(res["fcs_file"]).with_name("short.fcs")
    short.write_bytes(raw[:-4000])
    try:
        mod.fcs_summary(short)
        raise AssertionError("a truncated DATA segment was accepted")
    except mod.DeviceFault as e:
        assert "incomplete" in str(e)
    assert any(l.startswith("worklist mhp_") for l in drv.hw.log)
    drv.close()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok ", name)
