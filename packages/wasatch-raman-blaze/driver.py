"""MHP driver for a Wasatch Photonics Raman spectrometer behind a BlazeMetrics Blaze probe (Wasatch.PY)."""
from __future__ import annotations

import csv
import json
import pathlib
import time

from openmhp.driver import DeviceFault, Driver, InvalidValue, Job

HERE = pathlib.Path(__file__).parent
SATURATION_COUNTS = 60000


def load_config() -> dict:
    p = HERE / "config.json"
    return json.loads(p.read_text()) if p.is_file() else {}


def _unwrap(r):
    """Newer Wasatch.PY wraps results in a SpectrometerResponse with .data."""
    return getattr(r, "data", r) if type(r).__name__ == "SpectrometerResponse" else r


class WasatchBackend:
    def __init__(self, cfg: dict):
        self.cfg = cfg

    def open(self) -> None:
        from wasatch.WasatchBus import WasatchBus
        from wasatch.WasatchDevice import WasatchDevice
        ids = list(WasatchBus().device_ids)
        if not ids:
            raise DeviceFault("no Wasatch spectrometer found on USB")
        want = self.cfg.get("serial_number")
        self.dev = None
        for device_id in ids:
            dev = WasatchDevice(device_id)
            if not _unwrap(dev.connect()):
                continue
            if want in (None, "", dev.settings.eeprom.serial_number):
                self.dev = dev
                break
            dev.disconnect()
        if self.dev is None:
            raise DeviceFault(f"spectrometer {want!r} not found (saw {len(ids)} device(s))")
        self.wavenumbers = list(self.dev.settings.wavenumbers or [])
        if not self.wavenumbers:
            raise DeviceFault("spectrometer reports no Raman shift axis (no excitation wavelength in its EEPROM)")

    def set(self, name: str, value) -> None:
        self.dev.change_setting(name, value)

    def detector_temperature(self):
        try:
            return float(_unwrap(self.dev.hardware.get_detector_temperature_degC()))
        except Exception:                             # noqa: BLE001  uncooled models
            return None

    def spectrum(self, timeout_s: float) -> list[float]:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            r = _unwrap(self.dev.acquire_data())
            s = getattr(r, "spectrum", None)
            if s is not None and len(s):
                return [float(x) for x in s]
            time.sleep(0.01)
        raise DeviceFault(f"no spectrum within {timeout_s:.0f} s")


class BlazeRaman(Driver):
    def setup(self) -> None:
        self.cfg = load_config()
        self.hw = None
        self.values = {"integration_time_ms": 5000, "scans_to_average": 1, "laser_power_percent": 100, "laser_enable": False}
        self.last_spectrum = None

    def make_backend(self):
        return WasatchBackend(self.cfg)

    def _hw(self):
        if self.hw is None:
            hw = self.make_backend()
            try:
                hw.open()
                hw.set("laser_enable", False)
                hw.set("integration_time_ms", self.values["integration_time_ms"])
                hw.set("scans_to_average", self.values["scans_to_average"])
            except Exception as e:                    # noqa: BLE001
                raise DeviceFault(f"cannot open the Raman spectrometer: {type(e).__name__}: {e}") from None
            self.hw = hw
        return self.hw

    def on_read(self, name: str):
        if name == "connected":
            try:
                self._hw()
                return True
            except DeviceFault:
                return False
        if name == "laser_enabled":
            return bool(self.values["laser_enable"])
        if name == "detector_temperature":
            return self._hw().detector_temperature()
        if name == "last_spectrum":
            return self.last_spectrum
        if name in self.values:
            return self.values[name]
        raise InvalidValue(f"unknown signal {name}")

    def on_write(self, name: str, value) -> None:
        vendor = {"laser_power_percent": "laser_power_perc"}.get(name, name)
        self._hw().set(vendor, value)
        self.values[name] = value
        if name == "laser_enable":
            self.emit_signal("laser_enabled", bool(value))

    # ---- analysis ---------------------------------------------------------------------------
    def _bands(self, wn: list[float], y: list[float]) -> dict:
        hw = float(self.cfg.get("band_half_width_cm1", 12))
        out = {}
        for centre in self.cfg.get("bands_cm1", [149, 219, 419, 630]):
            peak = [v for x, v in zip(wn, y) if abs(x - centre) <= hw]
            flank = sorted(v for x, v in zip(wn, y) if hw < abs(x - centre) <= 3 * hw)
            out[str(centre)] = round(max(peak) - flank[len(flank) // 2], 1) if peak and flank else None
        return out

    def _one(self, hw, label, folder: pathlib.Path, index: int, t0: float) -> dict:
        timeout = self.values["integration_time_ms"] / 1000 * self.values["scans_to_average"] * 2 + 10
        y = hw.spectrum(timeout)
        wn = hw.wavenumbers
        file = folder / f"spectrum_{index:04d}.csv"
        with file.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(("raman_shift_cm1", "counts"))
            w.writerows(zip((round(x, 2) for x in wn), y))
        summary = {"index": index, "t_s": round(time.time() - t0, 2), "label": label, "bands": self._bands(wn, y),
                   "max_counts": round(max(y), 1), "saturated": max(y) >= SATURATION_COUNTS,
                   "laser_enabled": bool(self.values["laser_enable"]),
                   "integration_time_ms": self.values["integration_time_ms"], "file": str(file)}
        self.last_spectrum = summary
        self.emit_signal("last_spectrum", summary)
        return summary

    def on_invoke(self, job: Job):
        hw = self._hw()
        label = job.params.get("label")
        root = pathlib.Path(self.cfg.get("data_dir") or HERE / "data")
        folder = root / f"{time.strftime('%Y%m%d-%H%M%S')}_{job.action}_{job.id}"
        folder.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        if job.action == "acquire":
            return self._one(hw, label, folder, 0, t0)
        if job.action == "acquire_series":
            count, interval = int(job.params["count"]), float(job.params.get("interval_s", 0)) * self.time_scale()
            series = []
            for k in range(count):
                started = time.monotonic()
                self.checkpoint(job, k / count)
                s = self._one(hw, label, folder, k, t0)
                series.append({"t_s": s["t_s"], **s["bands"]})
                while time.monotonic() - started < interval:
                    self.checkpoint(job)
                    time.sleep(min(0.2, interval))
            with (folder / "bands.csv").open("w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(series[0]))
                w.writeheader()
                w.writerows(series)
            keys = [k for k in series[0] if k != "t_s"]
            def mean(rows, k):
                vals = [r[k] for r in rows if r[k] is not None]
                return round(sum(vals) / len(vals), 1) if vals else None
            q = max(1, count // 4)
            return {"count": count, "label": label, "folder": str(folder), "bands_csv": str(folder / "bands.csv"),
                    "laser_enabled": bool(self.values["laser_enable"]),
                    "bands_first_quarter": {k: mean(series[:q], k) for k in keys},
                    "bands_last_quarter": {k: mean(series[-q:], k) for k in keys},
                    "series": series if count <= 60 else series[:: max(1, count // 60)]}
        raise InvalidValue(f"unhandled action {job.action}")

    def time_scale(self) -> float:
        return 1.0

    def on_estop(self) -> None:
        try:
            if self.hw is not None:
                self.hw.set("laser_enable", False)
        except Exception:                             # noqa: BLE001  must not raise
            pass
        self.values["laser_enable"] = False
