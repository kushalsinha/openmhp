"""MHP driver for a Thermo Orbitrap Tribrid (Fusion, Lumos, Eclipse, Ascend) through the Instrument API (IAPI)
via pythonnet, Windows only.

Every .NET call lives in IapiBackend so the simulated twin can replace it. Member names come from Thermo's
open iapi repository (github.com/thermofisherlsms/iapi, GettingStarted.md and the tribrid examples); the ones
that could not be read there are marked `# unverified` and listed in references/iapi.md.
"""
from __future__ import annotations

import csv
import json
import pathlib
import threading
import time

from openmhp.driver import DeviceFault, Driver, InvalidValue, Job, JobCancelled

HERE = pathlib.Path(__file__).parent
ASSEMBLIES = ("Thermo.TNG.Factory", "API-2.0", "Fusion.API-1.0")


def load_config() -> dict:
    p = HERE / "config.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def _as_dict(net_dict) -> dict:
    out = {}
    try:
        for kv in net_dict:
            out[str(kv.Key)] = str(kv.Value)
    except Exception:                                    # noqa: BLE001  a plain mapping already
        out = dict(net_dict or {})
    return out


class IapiBackend:
    """Thermo IAPI through pythonnet: connection, state, scan events and custom scans."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.lock = threading.Lock()
        self.scans_seen = 0
        self.last: dict | None = None                    # the most recent scan, summarised
        self.pending: dict[str, dict] = {}               # access id -> scan summary, for custom scan requests
        self.container = self.access = self.control = self.acq = self.scans = self.msc = None

    def open(self) -> None:
        folder = self.cfg.get("assembly_dir")
        if not folder:
            raise DeviceFault("config.json is missing or has no assembly_dir (copy config.example.json and fill it in)")
        import sys
        import clr                                       # pythonnet
        if folder not in sys.path:
            sys.path.append(folder)
        for name in ASSEMBLIES:
            clr.AddReference(name)
        from Thermo.TNG.Factory import Factory
        from Thermo.Interfaces.FusionAccess_V1 import IFusionInstrumentAccessContainer
        self.container = Factory[IFusionInstrumentAccessContainer].Create()
        self.container.StartOnlineAccess()
        deadline = time.monotonic() + float(self.cfg.get("connect_timeout_s", 30))
        while not self.container.ServiceConnected:
            if time.monotonic() > deadline:
                raise DeviceFault("the Tune/IAPI service did not connect; is the instrument PC's Tune running with the IAPI licence?")
            time.sleep(0.2)
        self.access = self.container.Get(int(self.cfg.get("instrument_index", 1)))
        self.control = self.access.Control
        self.acq = self.control.Acquisition
        self.scans = self.control.GetScans(False)
        self.msc = self.access.GetMsScanContainer(0)
        self.msc.MsScanArrived += self._arrived

    def close(self) -> None:
        try:
            if self.msc is not None:
                self.msc.MsScanArrived -= self._arrived
            if self.scans is not None:
                self.scans.Dispose()
        except Exception:                                # noqa: BLE001
            pass

    # ---- scan events ---------------------------------------------------------------------- #
    def _arrived(self, sender, e) -> None:
        try:
            scan = e.GetScan()
            header, trailer = _as_dict(scan.Header), _as_dict(scan.Trailer)
            peaks = [(float(c.Mz), float(c.Intensity)) for c in scan.Centroids]
            summary = {"scan_number": int(float(header.get("Scan", header.get("ScanNumber", 0)))),
                       "tic": float(header["TIC"]) if header.get("TIC") not in (None, "") else None,   # unverified key
                       "header": header, "peaks": peaks, "access_id": trailer.get("Access ID")}
        except Exception as ex:                          # noqa: BLE001  never let a .NET callback die loudly
            summary = {"scan_number": -1, "tic": None, "header": {}, "peaks": [], "access_id": None,
                       "error": f"{type(ex).__name__}: {ex}"}
        with self.lock:
            self.scans_seen += 1
            self.last = summary
            if summary.get("access_id") is not None:
                self.pending[str(summary["access_id"])] = summary

    # ---- state ---------------------------------------------------------------------------- #
    def instrument_name(self) -> str:
        return str(self.access.InstrumentName)                                              # unverified

    def connected(self) -> bool:
        return bool(self.access.Connected)                                                  # unverified

    def system_state(self) -> str:
        return str(self.acq.State.SystemState)                                              # InstrumentState enum

    def system_mode(self) -> str:
        return str(self.acq.State.SystemMode)                                               # unverified

    def last_scan(self) -> dict | None:
        with self.lock:
            return self.last

    # ---- custom scans --------------------------------------------------------------------- #
    def request_custom_scan(self, values: dict, running_number: int) -> None:
        cs = self.scans.CreateCustomScan()
        for k, v in values.items():
            cs.Values[k] = str(v)
        cs.RunningNumber = running_number
        cs.SingleProcessingDelay = 0.0                                                      # as in the examples
        if self.scans.SetCustomScan(cs) is False:
            raise DeviceFault("the instrument did not accept the custom scan (SetCustomScan returned false)")

    def take_scan(self, running_number: int) -> dict | None:
        with self.lock:
            return self.pending.pop(str(running_number), None)

    def cancel_custom_scan(self) -> None:
        self.scans.CancelCustomScan()


class OrbitrapIAPI(Driver):
    def setup(self) -> None:
        self.cfg = load_config()
        self.hw = None
        self.running_number = int(time.time()) % 100000
        self.last_custom = None

    def make_backend(self):
        return IapiBackend(self.cfg)

    def time_scale(self) -> float:
        return 1.0

    def _hw(self):
        if self.hw is None:
            hw = self.make_backend()
            try:
                hw.open()
            except DeviceFault:
                raise
            except Exception as e:                       # noqa: BLE001  pythonnet / .NET exceptions
                raise DeviceFault(f"cannot reach the IAPI: {type(e).__name__}: {e}") from None
            self.hw = hw
        return self.hw

    def on_read(self, name: str):
        if name == "connected":
            try:
                return bool(self._hw().connected())
            except DeviceFault:
                return False
            except Exception as e:                       # noqa: BLE001
                raise DeviceFault(f"connection state unreadable: {type(e).__name__}: {e}") from None
        hw = self._hw()
        try:
            if name == "instrument_name":
                return hw.instrument_name()
            if name == "instrument_state":
                return hw.system_state()
            if name == "acquisition_state":
                return hw.system_mode()
            if name == "last_scan_number":
                s = hw.last_scan()
                return int(s["scan_number"]) if s else 0
            if name == "tic":
                s = hw.last_scan()
                return s["tic"] if s else None
            if name == "last_custom_scan":
                return self.last_custom
        except DeviceFault:
            raise
        except Exception as e:                           # noqa: BLE001
            raise DeviceFault(f"{name} unreadable: {type(e).__name__}: {e}") from None
        raise InvalidValue(f"unknown signal {name}")

    def validate_params(self, action: str, params: dict) -> None:
        if action == "request_custom_scan" and params["first_mass"] >= params["last_mass"]:
            raise InvalidValue("request_custom_scan: first_mass must be below last_mass")

    def _peaks_csv(self, job: Job, scan: dict) -> str:
        root = pathlib.Path(self.cfg.get("data_dir") or HERE / "data")
        root.mkdir(parents=True, exist_ok=True)
        file = root / f"{time.strftime('%Y%m%d-%H%M%S')}_scan{scan['scan_number']}_{job.id}.csv"
        with file.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(("mz", "intensity"))
            w.writerows((round(mz, 5), round(i, 2)) for mz, i in scan["peaks"])
        return str(file)

    def on_invoke(self, job: Job):
        hw = self._hw()
        if job.action == "cancel_custom_scan":
            try:
                hw.cancel_custom_scan()
            except Exception as e:                       # noqa: BLE001
                raise DeviceFault(f"CancelCustomScan failed: {type(e).__name__}: {e}") from None
            return {"cancelled": True}
        if job.action != "request_custom_scan":
            raise InvalidValue(f"unhandled action {job.action}")
        p = job.params
        self.running_number += 1
        rn = self.running_number
        values = {"ScanType": "Full", "FirstMass": p["first_mass"], "LastMass": p["last_mass"],
                  "OrbitrapResolution": int(p["resolution"]), "AGCTarget": int(p["agc_target"]),
                  "MaxIT": p["max_it_ms"],                                                  # unverified key
                  "Polarity": 0 if p["polarity"] == "positive" else 1,                      # unverified key and encoding
                  "MassAnalyzer": "OrbitrapMS"}                                              # unverified value
        try:
            hw.request_custom_scan(values, rn)
        except DeviceFault:
            raise
        except Exception as e:                           # noqa: BLE001
            raise DeviceFault(f"SetCustomScan failed: {type(e).__name__}: {e}") from None
        scale = self.time_scale()
        timeout = (float(p["max_it_ms"]) / 1000 + float(self.cfg.get("scan_timeout_s", 30))) * scale
        t0 = time.monotonic()
        while True:
            try:
                self.checkpoint(job, min(0.95, (time.monotonic() - t0) / timeout), phase="waiting for the scan")
            except JobCancelled:
                try:
                    hw.cancel_custom_scan()
                except Exception:                        # noqa: BLE001
                    pass
                raise
            scan = hw.take_scan(rn)
            if scan is not None:
                break
            if time.monotonic() - t0 > timeout:
                try:
                    hw.cancel_custom_scan()
                except Exception:                        # noqa: BLE001
                    pass
                raise DeviceFault(f"no scan with access id {rn} arrived within {timeout / scale:.0f} s; "
                                  "is the instrument On and acquiring (Tune or a method running)?")
            time.sleep(0.02)
        result = {"scan_number": int(scan["scan_number"]), "points": len(scan["peaks"]),
                  "peaks_csv": self._peaks_csv(job, scan), "tic": scan["tic"],
                  "first_mass": p["first_mass"], "last_mass": p["last_mass"], "resolution": int(p["resolution"]),
                  "polarity": p["polarity"], "running_number": rn,
                  "base_peak_mz": max(scan["peaks"], key=lambda t: t[1])[0] if scan["peaks"] else None}
        self.last_custom = result
        self.emit_signal("last_custom_scan", result)
        return result

    def on_estop(self) -> None:
        try:
            if self.hw is not None:
                self.hw.cancel_custom_scan()
        except Exception:                                # noqa: BLE001  must not raise
            pass

    # ---- setup-time check (`mhp node setup`) ------------------------------------------------ #
    @classmethod
    def probe(cls, cfg: dict) -> str:
        folder = pathlib.Path(cfg.get("assembly_dir") or "")
        missing = [n for n in ASSEMBLIES if not (folder / f"{n}.dll").is_file()]
        if missing:
            raise DeviceFault(f"{', '.join(missing)} not found in {folder}; they ship with the licensed IAPI from Thermo")
        try:
            import clr                                   # noqa: F401
        except ImportError:
            raise DeviceFault("pythonnet is not installed (pip install pythonnet)") from None
        hw = IapiBackend(cfg)
        hw.open()
        try:
            return f"IAPI connected to {hw.instrument_name()}; state {hw.system_state()}"
        finally:
            hw.close()
