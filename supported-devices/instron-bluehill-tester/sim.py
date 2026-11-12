"""Simulated twin of the Bluehill route: a fake WCF client with a frame in SET UP mode, a specimen that stretches
elastically, yields and breaks at a set strain, and a results-table CSV written at finish the way a Bluehill
export is laid out (parameter rows, blank row, names row, units row, one specimen row)."""
from __future__ import annotations

import importlib.util
import os
import pathlib
import random
import sys
import tempfile
import time

_spec = importlib.util.spec_from_file_location(__name__ + "_real", pathlib.Path(__file__).with_name("driver.py"))
real = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = real
_spec.loader.exec_module(real)

MODULUS_MPA = 2000.0          # a stiff polymer
YIELD_STRAIN = 0.03
BREAK_STRAIN = 0.12


class SimBackend(real.InstronBackend):
    def __init__(self, cfg, scale):
        super().__init__(cfg)
        self.scale = scale
        self.online = True
        self.mode = "setup"
        self.test = None
        self._load = 0.0
        self._ext = 0.0
        self.reason = "finished"

    def open(self) -> None:
        if not self.online:
            raise real.DeviceFault("twin offline", {"transient": True})
        self.log.append("connect")

    def _tick(self):
        t = self.test
        if t is None:
            return
        el = (time.monotonic() - t["t0"]) / self.scale
        ext = t["rate"] / 60 * el
        area = (t["spec"].get("width_mm") or 10) * (t["spec"].get("thickness_mm") or 2)
        l0 = t["spec"].get("gauge_length_mm") or 50
        strain = ext / l0
        if strain <= YIELD_STRAIN:
            stress = MODULUS_MPA * strain
        else:
            stress = MODULUS_MPA * YIELD_STRAIN * (1 + 0.15 * (strain - YIELD_STRAIN) / (BREAK_STRAIN - YIELD_STRAIN))
        load = stress * area * (1 + random.gauss(0, 0.002))
        self._ext, self._load = ext, load
        t["peak"] = max(t["peak"], load)
        done = None
        if strain >= BREAK_STRAIN:
            done = "break"
        elif load >= t["limits"]["max_load_N"]:
            done = "limit"
        elif ext >= t["limits"]["max_extension_mm"]:
            done = "limit"
        if done:
            self._finish(done, strain, stress, ext)

    def _finish(self, reason, strain, stress, ext):
        t = self.test
        self.reason = reason
        self.mode = "setup"
        self._load = 0.0 if reason == "break" else self._load
        area = (t["spec"].get("width_mm") or 10) * (t["spec"].get("thickness_mm") or 2)
        rows = [["Sample name", t["sample"], ""], ["Method", t["method"], ""], ["Crosshead Rate", f"{t['rate']:.2f}", "mm/min"], [],
                ["Specimen label", "Maximum Force", "Modulus (Automatic Young's)", "Tensile stress at Maximum Force", "Tensile strain at Break", "Extension at Break"],
                ["", "(N)", "(MPa)", "(MPa)", "(mm/mm)", "(mm)"],
                [t["spec"]["label"], f"{t['peak']:.2f}", f"{MODULUS_MPA * (1 + random.gauss(0, 0.01)):.1f}", f"{t['peak'] / area:.3f}",
                 f"{strain:.4f}" if reason == "break" else "", f"{ext:.3f}" if reason == "break" else ""]]
        out = pathlib.Path(self.cfg["outputs_dir"])
        (out / (t["sample"] + self.cfg["results_suffix"])).write_text("\r\n".join(",".join(r) for r in rows) + "\r\n", encoding="utf-8")
        (out / (t["sample"] + self.cfg["raw_suffix"])).write_text("Time,Extension,Load\r\n(s),(mm),(N)\r\n0.00,0.000,0.0\r\n", encoding="utf-8")
        self.log.append(f"test ended: {reason}, peak {t['peak']:.1f} N, export written")
        self.test = None

    def frame_mode(self) -> str:
        self._tick()
        return self.mode

    def crosshead(self) -> str:
        self._tick()
        return "moving" if self.test else "stopped"

    def load(self) -> float:
        self._tick()
        return self._load

    def extension(self) -> float:
        self._tick()
        return self._ext

    def test_running(self) -> bool:
        self._tick()
        return self.test is not None

    def end_reason(self) -> str:
        return self.reason

    def start_test(self, method, sample_name, specimen, rate, limits):
        if self.mode != "setup":
            raise real.DeviceFault(f"frame is {self.mode}")
        self.log.append(f"StartTest {method} {sample_name}")
        self.mode = "testing"
        self._ext = self._load = 0.0
        self.test = {"t0": time.monotonic(), "method": method, "sample": sample_name, "spec": specimen, "rate": rate, "limits": limits, "peak": 0.0}

    def stop(self) -> None:
        self.log.append("StopTest")
        if self.test is not None:
            self._finish("stopped", self._ext / (self.test["spec"].get("gauge_length_mm") or 50), 0.0, self._ext)
        self.mode = "setup" if self.mode != "disabled" else self.mode

    def disable_frame(self) -> None:
        self.log.append("DisableFrame")
        self.mode = "disabled"


class SimInstronBluehill(real.InstronBluehill):
    def setup(self) -> None:
        super().setup()
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        base = os.environ.get("OPENMHP_HOME") or tempfile.gettempdir()
        pathlib.Path(base).mkdir(parents=True, exist_ok=True)
        root = pathlib.Path(tempfile.mkdtemp(prefix="instron-bluehill-", dir=base))
        (root / "outputs").mkdir()
        self.cfg = {"endpoint": "net.tcp://sim/BluehillUniversalAPI", "outputs_dir": str(root / "outputs"), "methods_dir": "",
                    "results_suffix": "_Results.csv", "raw_suffix": "_RawData.csv", "max_test_minutes": 60, "poll_s": 1,
                    "load_cell_N": 5000}

    def time_scale(self) -> float:
        return self.scale

    def make_backend(self):
        return SimBackend(self.cfg, self.scale)
