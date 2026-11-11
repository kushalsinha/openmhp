"""SDK-route packages, wave A: Ocean Insight (seabreeze), PalmSens (MethodSCRIPT serial), Thermo Orbitrap (IAPI),
Micro-Manager (pymmcore-plus), LabJack (LJM) and NI-DAQmx. No vendor library is installed: the real drivers must
load and read `connected` False, and the twins must run through the same gates as the real drivers.

    PYTHONPATH=. python tests/test_packages_sdk_a.py      (or: python -m pytest tests/test_packages_sdk_a.py -q)
"""
import os
import struct
import sys
import tempfile
import time

os.environ["OPENMHP_HOME"] = tempfile.mkdtemp()
os.environ["OPENMHP_SIM_TIME_SCALE"] = "0.001"
sys.path.insert(0, ".")

from openmhp.client import LocalDevice, RemoteError                        # noqa: E402
from openmhp.driver import DeviceFault                                     # noqa: E402
from openmhp.package import load_driver, load_package                      # noqa: E402
from openmhp.validate import validate_path                                 # noqa: E402

PACKAGES = ["ocean-insight-spectrometer", "palmsens-potentiostat", "thermo-orbitrap-iapi",
            "micro-manager-microscope", "labjack-t-series", "ni-daqmx"]


def refused(code, fn):
    try:
        fn()
        raise AssertionError(f"expected a refusal with {code}")
    except RemoteError as e:
        assert e.code == code, e
        return e


class _Broken:
    """A backend whose open() fails: what the twin's fake link looks like when the instrument is gone."""
    def open(self):
        raise DeviceFault("link down (test)")


def _twin(name):
    drv = load_driver(f"supported-devices/{name}", sim=True)
    return drv, LocalDevice(drv)


def _common(name):
    """The checks every package must pass, as the brief lists them."""
    v = validate_path(f"supported-devices/{name}")
    assert v["ok"], (name, v["errors"])
    assert [w for w in v["warnings"] if "no location" not in w] == [], (name, v["warnings"])
    real = LocalDevice(load_driver(f"supported-devices/{name}"))            # no SDK, no config.json
    assert real.read("connected") is False, name
    drv, d = _twin(name)
    assert d.read("state") == "idle" and d.read("busy") is False and d.read("connected") is True, name
    assert d.read("calibration_status") == "unknown", name                  # no record yet: says so, never guesses
    desc = load_package(f"supported-devices/{name}").descriptor
    for a in desc["actions"]:
        ex = (a.get("examples") or [{}])[0]
        r = d.invoke(a["name"], dry_run=True, approved=True, **ex)
        assert r["state"] == "dryRun", (name, a["name"], r)
    # an open interlock: every action here needs `connected`; break the link and the gate refuses
    good_hw, drv.hw, drv.make_backend = drv.hw, None, lambda: _Broken()
    assert d.read("connected") is False
    first = next(a for a in desc["actions"] if "connected" in (a.get("interlocks") or []))
    refused(-32011, lambda: d.invoke(first["name"], **(first.get("examples") or [{}])[0]))
    drv.hw = good_hw
    assert d.read("connected") is True
    # fault injection on the twin: the next read fails
    assert d.call("sim/fault", {"mode": "raise", "on": "read"})["armed"]["mode"] == "raise"
    sig = next(s["name"] for s in desc["signals"] if s.get("source") not in ("runtime", "record"))
    try:
        d.read(sig)
        raise AssertionError("expected the injected fault")
    except RemoteError as e:
        assert "injected fault" in str(e), e
    if d.read("state") != "idle":
        d.reset()
    assert d.read("state") == "idle" and d.read(sig) is not None
    return drv, d, desc


def test_ocean_insight_spectrometer():
    drv, d, desc = _common("ocean-insight-spectrometer")
    refused(-32010, lambda: d.write("integration_time_us", 20_000_000))
    refused(-32014, lambda: d.write("integration_time_us", 1000.5))          # integers only
    d.write("integration_time_us", 200_000)
    d.write("scans_to_average", 3)
    assert d.read("integration_time") == 200_000 and d.read("dark_stored") is False
    drv.link.lamp_on = False                                                # a person blocks the light
    dark = d.wait(d.invoke("acquire_dark", label="shutter closed"))
    drv.link.lamp_on = True
    assert dark["state"] == "done" and dark["resultMismatch"] is None
    assert d.read("dark_stored") is True and dark["result"]["averages"] == 3
    lit = d.wait(d.invoke("acquire", label="sample"))["result"]
    assert lit["dark_subtracted"] is True and len(lit["intensity"]) == len(lit["wavelength_nm"]) == 1044
    assert lit["file"].endswith(".csv") and os.path.isfile(lit["file"])
    assert max(lit["intensity"]) > 20 * max(dark["result"]["intensity"]) and lit["saturated"] is False
    raw = d.wait(d.invoke("acquire", subtract_dark=False))["result"]
    assert raw["dark_subtracted"] is False and raw["intensity"][0] - lit["intensity"][0] > 1000   # the dark level, removed
    d.write("tec_setpoint_c", -10)
    assert "tec -10" in drv.link.log
    d.write("integration_time_us", 300_000)
    assert d.read("dark_stored") is False                                   # a dark is only valid for its exposure
    d.estop()
    assert d.read("state") == "estop" and drv.link.log[-1] == "tec off"
    assert d.read("saturated") is False


def test_palmsens_potentiostat():
    drv, d, desc = _common("palmsens-potentiostat")
    refused(-32010, lambda: d.write("current_range_max_A", 1.0))
    refused(-32010, lambda: d.invoke("ca", e_V=3.0, duration_s=1))
    refused(-32014, lambda: d.invoke("cv", e_begin_V=0.9, e_vertex1_V=0.5, e_vertex2_V=-0.5))
    assert d.read("device_type") == "EmStat Pico" and d.read("firmware").startswith("espico")
    ca = d.wait(d.invoke("ca", e_V=0.5, interval_s=0.1, duration_s=5))
    assert ca["state"] == "done" and ca["resultMismatch"] is None
    r = ca["result"]
    assert r["points"] == 50 and abs(r["i_final_A"] - 0.5 / 2000) < 2e-5 and r["e_final_V"] == 0.5
    assert "meas_loop_ca p c 500m 100m 5" in r["script"] and r["script"][-1].strip() == "cell_off"
    assert any(line.startswith("meas_loop_ca") for line in drv.link.log)
    ocp = d.wait(d.invoke("ocp", duration_s=2))["result"]
    assert ocp["i_final_A"] is None and 0.3 < ocp["e_final_V"] < 0.45
    cv = d.wait(d.invoke("cv", e_begin_V=0.0, e_vertex1_V=0.6, e_vertex2_V=-0.2, n_scans=2))["result"]
    assert cv["points"] == 2 * 160 and any("nscans(2)" in line for line in cv["script"])
    # cancelling a running technique sends Z and the job ends cancelled, with the cell off
    job = d.invoke("lsv", e_begin_V=-0.5, e_end_V=0.5, scan_rate_mV_s=10)
    deadline = time.time() + 5
    while not d.read("running") and time.time() < deadline:
        time.sleep(0.005)
    d.cancel(job)
    assert d.wait(job)["state"] == "cancelled" and "Z" in drv.link.log and d.read("cell_on") is False
    d.estop()
    assert d.read("state") == "estop" and drv.link.log[-3:] == ["set_pgstat_chan 0", "cell_off", ""]


def test_thermo_orbitrap_iapi():
    drv, d, desc = _common("thermo-orbitrap-iapi")
    refused(-32010, lambda: d.invoke("request_custom_scan", first_mass=5000, last_mass=6000))
    refused(-32010, lambda: d.invoke("request_custom_scan", first_mass=400, last_mass=1200, resolution=70000))
    refused(-32014, lambda: d.invoke("request_custom_scan", first_mass=1200, last_mass=400))
    assert d.read("instrument_state") == "On"
    n0 = d.read("last_scan_number")
    time.sleep(0.1)
    assert d.read("last_scan_number") > n0 and d.read("tic") > 0          # the instrument scans on its own
    j = d.wait(d.invoke("request_custom_scan", first_mass=400, last_mass=1200, polarity="negative"))
    assert j["state"] == "done" and j["resultMismatch"] is None
    r = j["result"]
    assert r["points"] > 10 and 400 <= r["base_peak_mz"] <= 1200 and r["polarity"] == "negative"
    assert os.path.isfile(r["peaks_csv"]) and d.read("last_custom_scan")["scan_number"] == r["scan_number"]
    assert any(s.startswith(f"SetCustomScan {r['running_number']} ") and "FirstMass=400" in s for s in drv.link.log)
    assert d.wait(d.invoke("cancel_custom_scan"))["result"] == {"cancelled": True}
    d.estop()
    assert d.read("state") == "estop" and drv.link.log[-1] == "CancelCustomScan"


def test_micro_manager_microscope():
    drv, d, desc = _common("micro-manager-microscope")
    refused(-32010, lambda: d.write("exposure_ms", 20000))
    refused(-32010, lambda: d.write("z_um", 600))                            # the lab's soft limit, from config
    refused(-32014, lambda: d.write("channel", "Brightfield"))               # not a preset of the loaded config
    refused(-32010, lambda: d.invoke("acquire_z_stack", z_start_um=0, z_end_um=100, step_um=0.1))   # 1001 planes
    d.write("channel", "FITC")
    d.write("exposure_ms", 50)
    assert d.read("channel") == "FITC" and d.read("channels") == ["DAPI", "FITC", "Rhodamine", "Cy5"]
    snap = d.wait(d.invoke("snap", label="focus"))
    assert snap["state"] == "done" and snap["resultMismatch"] is None
    with open(snap["result"]["file"], "rb") as f:
        head = f.read(8)
    assert head[:4] == b"II*\x00" and struct.unpack("<I", head[4:])[0] == 8      # a TIFF any reader opens
    assert os.path.getsize(snap["result"]["file"]) == 8 + 2 + 12 * 9 + 4 + 256 * 256 * 2
    mv = d.wait(d.invoke("move_xy", x_um=1200.0, y_um=-350.0))["result"]
    assert mv == {"x_um": 1200.0, "y_um": -350.0} and d.read("xy_position") == mv
    refused(-32050, lambda: d.cancel(d.invoke("move_xy", x_um=0, y_um=0)))   # pymmcore blocks: not cancellable
    time.sleep(0.05)
    stack = d.wait(d.invoke("acquire_z_stack", z_start_um=-5, z_end_um=5, step_um=1))["result"]
    assert stack["count"] == 11 and len(stack["files"]) == 11 and d.read("z_um") == 0.0
    d.estop()
    assert d.read("state") == "estop" and drv.link.log[-1] == "stop XY; stop Z"


def test_labjack_t_series():
    drv, d, desc = _common("labjack-t-series")
    refused(-32010, lambda: d.write("dac0", 5.5))
    refused(-32010, lambda: d.write("ain_range_0", 5))                       # not in the enum
    refused(-32014, lambda: d.write("dac1", 1.0005))                         # off the 1 mV grid
    refused(-32010, lambda: d.invoke("sample", channels=["AIN0"], rate_hz=5000, seconds=1))
    refused(-32010, lambda: d.invoke("sample", channels=["AIN9"], rate_hz=10, seconds=1))
    d.write("dac0", 2.5)
    assert abs(d.read("ain1") - 2.5) < 0.05                                  # the twin jumpers DAC0 to AIN1
    d.write("fio2", True)
    assert d.read("dio_state") & 0b0100 and "eWriteName FIO2 1.0" in drv.link.log
    slow = d.wait(d.invoke("sample", channels=["AIN1", "AIN2"], rate_hz=10, seconds=2))
    assert slow["state"] == "done" and slow["resultMismatch"] is None
    assert slow["result"]["samples"] == 20 and abs(slow["result"]["mean_V"]["AIN1"] - 2.5) < 0.05
    fast = d.wait(d.invoke("sample", channels=["AIN0"], rate_hz=500, seconds=1))["result"]
    assert fast["samples"] == 500 and abs(fast["mean_V"]["AIN0"]) < 0.2 and any("eStreamStart 500.0" in s for s in drv.link.log)
    with open(fast["csv"]) as f:
        assert f.readline().strip() == "t_s,AIN0" and len(f.readlines()) == 500
    d.estop()
    assert d.read("state") == "estop" and drv.link.log[-1].startswith("eWriteNames DAC0=0.0 DAC1=0.0 FIO0=0.0")
    assert d.read("dio_state") & 0b1111 == 0 and d.read("dac0") == 0.0


def test_ni_daqmx():
    drv, d, desc = _common("ni-daqmx")
    refused(-32010, lambda: d.write("ao0", 12))
    refused(-32014, lambda: d.write("ao1", 0.0005))
    refused(-32010, lambda: d.invoke("sample", channels=["ai0"], rate_hz=0.5, seconds=1))
    refused(-32010, lambda: d.invoke("sample", channels=["ai7"], rate_hz=10, seconds=1))
    assert d.read("product_type") == "USB-6009" and d.read("device") == "Dev1"
    d.write("ao0", 2.5)
    assert abs(d.read("ai1") - 2.5) < 0.05                                   # the twin jumpers ao0 to ai1
    refused(-32020, lambda: d.write("ao1", -3))                              # a 6009 cannot do negative AO: DaqError
    d.reset()
    d.write("port0_line1", True)
    assert d.read("port0_state") == 0b0010 and "write port0_line1 high" in drv.link.log
    rec = d.wait(d.invoke("sample", channels=["ai1", "ai2"], rate_hz=100, seconds=2))
    assert rec["state"] == "done" and rec["resultMismatch"] is None
    r = rec["result"]
    assert r["samples"] == 200 and r["rate_hz"] == 100 and abs(r["mean_V"]["ai1"] - 2.5) < 0.05 and abs(r["mean_V"]["ai2"] - 0.5) < 0.05
    with open(r["csv"]) as f:
        assert f.readline().strip() == "t_s,ai1,ai2"
    d.estop()
    assert d.read("state") == "estop" and drv.link.log[-4:] == ["write port0_line0 low", "write port0_line1 low",
                                                                "write port0_line2 low", "write port0_line3 low"]
    assert d.read("port0_state") == 0 and d.read("ao0") == 0.0


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok ", name)
