"""MHP driver for Ocean Insight / Ocean Optics USB spectrometers (USB2000+, USB4000, Flame, QE Pro, HR series)
through python-seabreeze.

Every vendor call lives in SeaBreezeBackend so the simulated twin can replace it. The API used is the one
documented at python-seabreeze.readthedocs.io (Spectrometer.from_first_available / from_serial_number,
integration_time_micros, wavelengths, intensities, serial_number, model, max_intensity, f.thermo_electric).
"""
from __future__ import annotations

import csv
import json
import pathlib
import time

from openmhp.driver import DeviceFault, Driver, InvalidValue, Job, JobCancelled, NotSupported

HERE = pathlib.Path(__file__).parent


def load_config() -> dict:
    p = HERE / "config.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


class SeaBreezeBackend:
    """python-seabreeze calls, nothing else."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.spec = None

    def open(self) -> None:
        from seabreeze.spectrometers import Spectrometer
        want = self.cfg.get("serial_number")
        self.spec = Spectrometer.from_serial_number(want) if want else Spectrometer.from_first_available()

    def close(self) -> None:
        if self.spec is not None:
            self.spec.close()

    def identity(self) -> dict:
        s = self.spec
        lo, hi = s.integration_time_micros_limits
        return {"serial_number": str(s.serial_number), "model": str(s.model), "pixels": int(s.pixels),
                "max_intensity": float(s.max_intensity), "integration_limits_us": [int(lo), int(hi)]}

    def set_integration_time(self, micros: int) -> None:
        self.spec.integration_time_micros(int(micros))

    def wavelengths(self) -> list[float]:
        return [float(x) for x in self.spec.wavelengths()]

    def intensities(self, correct_dark_counts: bool, correct_nonlinearity: bool) -> list[float]:
        return [float(x) for x in self.spec.intensities(correct_dark_counts=correct_dark_counts,
                                                        correct_nonlinearity=correct_nonlinearity)]

    def _tec(self):
        return getattr(self.spec.f, "thermo_electric", None)              # unverified: None when the model has no TEC

    def has_tec(self) -> bool:
        return self._tec() is not None

    def detector_temperature(self):
        tec = self._tec()
        if tec is None:
            return None
        return float(tec.read_temperature_degrees_celsius())

    def set_tec(self, setpoint_c):
        tec = self._tec()
        if tec is None:
            raise NotSupported("this spectrometer has no thermo-electric cooler (only the QE Pro and other cooled models do)")
        if setpoint_c is None:
            tec.enable_tec(False)
        else:
            tec.set_temperature_setpoint_degrees_celsius(float(setpoint_c))
            tec.enable_tec(True)


class OceanSpectrometer(Driver):
    def setup(self) -> None:
        self.cfg = load_config()
        self.hw = None
        self.ident: dict = {}
        self.values = {"integration_time_us": 100000, "scans_to_average": 1, "tec_setpoint_c": None}
        self.dark: list[float] | None = None
        self.last_saturated = False

    def make_backend(self):
        return SeaBreezeBackend(self.cfg)

    def time_scale(self) -> float:
        return 1.0

    def _hw(self):
        if self.hw is None:
            hw = self.make_backend()
            try:
                hw.open()
                self.ident = hw.identity()
                hw.set_integration_time(self.values["integration_time_us"])
            except Exception as e:                       # noqa: BLE001  seabreeze raises its own classes
                raise DeviceFault(f"cannot open the spectrometer: {type(e).__name__}: {e}") from None
            self.hw = hw
        return self.hw

    def on_read(self, name: str):
        if name == "connected":
            try:
                self._hw()
                return True
            except DeviceFault:
                return False
        if name == "serial_number":
            self._hw()
            return self.ident["serial_number"]
        if name == "model":
            self._hw()
            return self.ident["model"]
        if name == "integration_time":
            return int(self.values["integration_time_us"])
        if name == "detector_temperature":
            try:
                return self._hw().detector_temperature()
            except Exception as e:                       # noqa: BLE001
                raise DeviceFault(f"detector temperature unreadable: {type(e).__name__}: {e}") from None
        if name == "saturated":
            return bool(self.last_saturated)
        if name == "dark_stored":
            return self.dark is not None
        raise InvalidValue(f"unknown signal {name}")

    def on_write(self, name: str, value) -> None:
        hw = self._hw()
        if name == "integration_time_us":
            lo, hi = self.ident.get("integration_limits_us", [value, value])
            if not lo <= value <= hi:
                raise InvalidValue(f"integration_time_us={value} is outside this model's range {lo}..{hi} us",
                                   {"min": lo, "max": hi})
            try:
                hw.set_integration_time(int(value))
            except Exception as e:                       # noqa: BLE001
                raise DeviceFault(f"integration time not accepted: {type(e).__name__}: {e}") from None
            self.dark = None                             # a dark is only valid for the exposure it was taken with
            self.emit_signal("integration_time", int(value))
        elif name == "tec_setpoint_c":
            try:
                hw.set_tec(value)
            except NotSupported:
                raise
            except Exception as e:                       # noqa: BLE001
                raise DeviceFault(f"TEC command failed: {type(e).__name__}: {e}") from None
        self.values[name] = value

    # ---- acquisition ---------------------------------------------------------------------
    def _spectrum(self, job: Job, p: dict) -> tuple[list[float], list[float]]:
        hw = self._hw()
        averages = int(self.values["scans_to_average"])
        exposure_s = self.values["integration_time_us"] / 1e6
        acc: list[float] | None = None
        wl = hw.wavelengths()
        for k in range(averages):
            try:
                self.checkpoint(job, k / averages, phase="exposing")
            except JobCancelled:
                raise
            try:
                y = hw.intensities(bool(p.get("correct_dark_counts")), bool(p.get("correct_nonlinearity")))
            except Exception as e:                       # noqa: BLE001
                raise DeviceFault(f"no spectrum after {exposure_s:.3f} s exposure: {type(e).__name__}: {e}") from None
            acc = y if acc is None else [a + b for a, b in zip(acc, y)]
        return wl, [v / averages for v in acc]

    def _save(self, job: Job, wl: list[float], y: list[float], kind: str):
        root = self.cfg.get("data_dir")
        if not root:
            return None
        folder = pathlib.Path(root)
        folder.mkdir(parents=True, exist_ok=True)
        file = folder / f"{time.strftime('%Y%m%d-%H%M%S')}_{kind}_{job.id}.csv"
        with file.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(("wavelength_nm", "intensity"))
            w.writerows(zip((round(x, 3) for x in wl), (round(v, 3) for v in y)))
        return str(file)

    def on_invoke(self, job: Job):
        p = job.params
        if job.action not in ("acquire", "acquire_dark"):
            raise InvalidValue(f"unhandled action {job.action}")
        wl, y = self._spectrum(job, p)
        saturated = max(y) >= self.ident.get("max_intensity", float("inf"))
        self.last_saturated = saturated
        self.emit_signal("saturated", saturated)
        dark_subtracted = False
        if job.action == "acquire_dark":
            self.dark = list(y)
            self.emit_signal("dark_stored", True)
        elif p.get("subtract_dark") and self.dark is not None and len(self.dark) == len(y):
            y = [a - b for a, b in zip(y, self.dark)]
            dark_subtracted = True
        file = self._save(job, wl, y, "dark" if job.action == "acquire_dark" else "spectrum")
        return {"wavelength_nm": [round(x, 3) for x in wl], "intensity": [round(v, 3) for v in y],
                "integration_time_us": int(self.values["integration_time_us"]),
                "averages": int(self.values["scans_to_average"]), "saturated": saturated,
                "dark_subtracted": dark_subtracted, "label": p.get("label"), "file": file}

    def on_estop(self) -> None:
        try:
            if self.hw is not None and self.hw.has_tec():
                self.hw.set_tec(None)
        except Exception:                                # noqa: BLE001  must not raise
            pass
        self.values["tec_setpoint_c"] = None

    # ---- setup-time checks (`mhp node setup`) ------------------------------------------- #
    @classmethod
    def discover(cls, cfg: dict, what: str) -> list:
        if what != "spectrometers":
            return []
        try:
            from seabreeze.spectrometers import list_devices
        except ImportError:
            return []
        return [(str(d.serial_number), str(d.model)) for d in list_devices()]

    @classmethod
    def probe(cls, cfg: dict) -> str:
        try:
            from seabreeze.spectrometers import list_devices
        except ImportError:
            raise DeviceFault("python-seabreeze is not installed (pip install seabreeze; then seabreeze_os_setup)") from None
        devs = list_devices()
        if not devs:
            raise DeviceFault("no Ocean Insight spectrometer found on USB (is OceanView closed?)")
        return f"{len(devs)} spectrometer(s): " + ", ".join(f"{d.model} {d.serial_number}" for d in devs)
