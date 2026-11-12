"""MHP driver for Gamry Interface 1010 / Reference 620 potentiostats through the Gamry Electrochemistry
Toolkit COM interface (GamryCOM, installed with the Gamry Framework on Windows), driven with pywin32.

The Toolkit exposes a device list (IGamryDeviceList.EnumSections), a potentiostat object (IGamryPstat:
Init with the device's section name, Open, SetCell CellOn/CellOff, SetSignal, Close), data-acquisition
objects (IGamryDtaqChrono, IGamryDtaqRcv, IGamryDtaqOcv, IGamryReadZ for EIS: Init, Run, Cook, Stop)
and signal generators (IGamrySignalConst, IGamrySignalRupdn, IGamrySignalRamp: Init with the pstat and
the waveform parameters). Those names come from Gamry's Electrochemistry Toolkit brochure (Rev 1.0,
2018), the application note "Steps for Creating an Application Using GamryCOM" (2015) and a published
Python example that drives a Reference 600 through win32com. The argument lists of the Dtaq and Signal
Init calls, the Cook column order and the ReadZ members are marked `# unverified` and listed in
references/gamrycom.md: check them against the Toolkit reference manual installed with the Framework.
Every COM call sits in GamryBackend; the twin replaces it with a dummy cell.
"""
from __future__ import annotations

import csv
import json
import math
import pathlib
import time

from openmhp.driver import DeviceFault, Driver, InvalidValue, Job, JobCancelled, LimitViolation

HERE = pathlib.Path(__file__).parent
CELL_ON, CELL_OFF = 1, 0            # GamryCOM.CellOn / CellOff: 1 and 0 in the published Python example
PSTAT_MODE = 1                      # GamryCOM.PstatMode (potentiostatic control)       # unverified value
COOK_COLUMNS = {"chrono": {"t": 0, "v": 1, "i": 3}, "rcv": {"t": 0, "v": 1, "i": 3}, "ocv": {"t": 0, "v": 1, "i": None}}   # unverified


def load_config() -> dict:
    p = HERE / "config.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def frequencies(f_start: float, f_end: float, per_decade: int) -> list[float]:
    """Logarithmic sweep from f_start to f_end, `per_decade` points per decade, both ends included."""
    decades = abs(math.log10(f_start) - math.log10(f_end))
    n = max(2, int(round(decades * per_decade)) + 1)
    return [10 ** (math.log10(f_start) + (math.log10(f_end) - math.log10(f_start)) * k / (n - 1)) for k in range(n)]


class _ComRun:
    """One Dtaq running on the instrument; rows are (t_s, e_V, i_A)."""

    def __init__(self, backend, dtaq, cols: dict, expected_s: float):
        self.backend, self.dtaq, self.cols, self.expected_s = backend, dtaq, cols, expected_s
        self.t0, self.quiet, self.error = time.monotonic(), 0, None

    def poll(self) -> list[tuple]:
        try:
            count, points = self.dtaq.Cook(1024)                                  # unverified: returns (count, columns)
        except Exception as e:                                                   # noqa: BLE001
            self.error = f"{type(e).__name__}: {e}"
            return []
        rows = []
        if count:
            cols = list(zip(*points)) if points and not isinstance(points[0], (int, float)) else []
            for row in (cols or []):
                t, v = float(row[self.cols["t"]]), float(row[self.cols["v"]])
                i = float(row[self.cols["i"]]) if self.cols.get("i") is not None else None
                rows.append((t, v, i))
            self.quiet = 0
        else:
            self.quiet += 1
        return rows

    def alive(self) -> bool:
        if self.error:
            return False
        return (time.monotonic() - self.t0) < self.expected_s + 2.0 or self.quiet < 5

    def stop(self) -> None:
        try:
            self.dtaq.Stop()
        finally:
            self.backend.cell(False)


class GamryBackend:
    """The only class that touches GamryCOM."""

    def __init__(self, cfg: dict):
        self.cfg, self.com, self.pstat, self.section = cfg, None, None, None
        self.log: list[str] = []

    def open(self) -> None:
        if "device" not in self.cfg:
            raise DeviceFault("config.json is missing (copy config.example.json and fill it in)")
        try:
            import win32com.client as com                                        # pywin32, Windows only
        except ImportError:
            raise DeviceFault("pywin32 is not installed (pip install pywin32); the Gamry Toolkit is a Windows COM interface") from None
        self.com = com
        devlist = com.Dispatch("GamryCOM.GamryDeviceList")
        sections = [str(s) for s in devlist.EnumSections()]
        want = self.cfg.get("device") or ""
        if want and want not in sections:
            raise DeviceFault(f"no Gamry instrument named {want!r}; the Framework lists {sections}", {"transient": True})
        if not sections:
            raise DeviceFault("the Gamry Framework lists no instrument (is it powered and connected?)", {"transient": True})
        self.section = want or sections[0]
        self.pstat = com.Dispatch("GamryCOM.GamryPstat")
        self.pstat.Init(self.section)
        self.pstat.Open()
        self.log.append(f"open {self.section}")

    def close(self) -> None:
        if self.pstat is not None:
            try:
                self.pstat.SetCell(CELL_OFF)
                self.pstat.Close()
            finally:
                self.pstat = None

    def cell(self, on: bool) -> None:
        self.pstat.SetCell(CELL_ON if on else CELL_OFF)
        self.log.append("cell on" if on else "cell off")

    def start(self, kind: str, p: dict) -> _ComRun:
        com, pstat = self.com, self.pstat
        cols = (self.cfg.get("cook_columns") or {}).get(kind) or COOK_COLUMNS[kind]
        if kind == "ocv":
            dtaq = com.Dispatch("GamryCOM.GamryDtaqOcv")
            dtaq.Init(pstat)                                                       # unverified
            signal = com.Dispatch("GamryCOM.GamrySignalConst")
            signal.Init(pstat, 0.0, p["duration_s"], p["sample_s"], PSTAT_MODE)   # unverified argument order
            expected = p["duration_s"]
        elif kind == "chrono":
            dtaq = com.Dispatch("GamryCOM.GamryDtaqChrono")
            dtaq.Init(pstat, 0)                                                    # unverified: 0 = ChronoAmp
            signal = com.Dispatch("GamryCOM.GamrySignalConst")
            signal.Init(pstat, p["e_V"], p["duration_s"], p["sample_s"], PSTAT_MODE)   # unverified argument order
            expected = p["duration_s"]
        elif kind == "rcv":
            dtaq = com.Dispatch("GamryCOM.GamryDtaqRcv")
            dtaq.Init(pstat)                                                       # unverified
            signal = com.Dispatch("GamryCOM.GamrySignalRupdn")
            rate = p["scan_rate_mV_s"] / 1000
            signal.Init(pstat, p["e_init_V"], p["e_vertex1_V"], p["e_vertex2_V"], p["e_final_V"],
                        rate, 0.0, 0.0, 0.0, p["step_V"] / rate, p["cycles"], PSTAT_MODE)   # unverified argument order
            expected = p["expected_s"]
        else:
            raise InvalidValue(kind)
        pstat.SetSignal(signal)
        if kind != "ocv":
            self.cell(True)
        dtaq.Run(True)
        self.log.append(f"run {kind}")
        return _ComRun(self, dtaq, cols, expected)

    def measure_z(self, f_hz: float, e_dc_V: float, amplitude_V: float) -> tuple[float, float]:
        """One EIS point: (Zreal, Zimag) in ohm at f_hz. Member names unverified."""
        if getattr(self, "readz", None) is None:
            self.readz = self.com.Dispatch("GamryCOM.GamryReadZ")
            self.readz.Init(self.pstat)                                            # unverified
            self.pstat.SetVoltage(e_dc_V)                                           # unverified
            self.cell(True)
        self.readz.Measure(f_hz, amplitude_V)                                      # unverified: asynchronous in the Toolkit
        deadline = time.monotonic() + max(5.0, 10.0 / f_hz)
        while time.monotonic() < deadline:
            try:
                if float(self.readz.Zfreq()) == f_hz:                              # unverified
                    return float(self.readz.Zreal()), float(self.readz.Zimag())   # unverified
            except Exception:                                                      # noqa: BLE001  not ready yet
                pass
            time.sleep(0.05)
        raise DeviceFault(f"no impedance point came back at {f_hz:g} Hz", {"transient": True})

    def end_z(self) -> None:
        self.readz = None
        self.cell(False)


class Device(Driver):
    def setup(self) -> None:
        self.cfg = load_config()
        self.hw = None
        self.cell_on = False
        self.is_running = False
        self.last_result = None

    def make_backend(self):
        return GamryBackend(self.cfg)

    def time_scale(self) -> float:
        return 1.0

    def _hw(self):
        if self.hw is None:
            hw = self.make_backend()
            try:
                hw.open()
            except DeviceFault:
                raise
            except Exception as e:                           # noqa: BLE001  vendor boundary
                raise DeviceFault(f"cannot open the Gamry instrument: {type(e).__name__}: {e}", {"transient": True}) from None
            self.hw = hw
        return self.hw

    def _vendor(self, what: str, fn):
        try:
            return fn()
        except (DeviceFault, InvalidValue):
            raise
        except Exception as e:                               # noqa: BLE001  vendor boundary
            raise DeviceFault(f"GamryCOM {what} failed: {type(e).__name__}: {e}", {"transient": True}) from None

    def on_read(self, name: str):
        if name == "connected":
            try:
                self._hw()
                return True
            except DeviceFault:
                return False
        if name == "device":
            return self._hw().section
        if name == "cell_on":
            return self.cell_on
        if name == "output_enabled":
            return self.cell_on
        if name == "running":
            return self.is_running
        if name == "last_result":
            return self.last_result
        raise InvalidValue(f"unknown signal {name}")

    def on_write(self, name: str, value):
        if name != "output_enabled":
            raise InvalidValue(f"unknown setting {name}")
        self._vendor("SetCell", lambda: self._hw().cell(bool(value)))
        self.cell_on = bool(value)
        return None

    def validate_params(self, action: str, params: dict) -> None:
        if action == "cv":
            e = [params.get("e_init_V"), params.get("e_vertex1_V"), params.get("e_vertex2_V")]
            if all(isinstance(x, (int, float)) for x in e) and e[1] == e[2]:
                raise InvalidValue("cv: e_vertex1_V and e_vertex2_V must differ")
            ef = params.get("e_final_V")
            if ef is not None and isinstance(ef, (int, float)) and not (min(e) <= ef <= max(e)):
                raise LimitViolation("cv: e_final_V must lie between the vertices")
        if action == "eis":
            fs, fe = params.get("f_start_Hz"), params.get("f_end_Hz")
            if isinstance(fs, (int, float)) and isinstance(fe, (int, float)) and fs <= fe:
                raise InvalidValue("eis: f_start_Hz must be above f_end_Hz (the sweep runs from high to low frequency)")
            if isinstance(fs, (int, float)) and isinstance(fe, (int, float)):
                n = len(frequencies(fs, fe, int(params.get("points_per_decade", 10))))
                if n > int(self.cfg.get("max_eis_points", 200)):
                    raise LimitViolation(f"eis: {n} frequency points; keep it under max_eis_points ({self.cfg.get('max_eis_points', 200)})")
        for key in ("duration_s",):
            if key in params and isinstance(params[key], (int, float)) and params[key] > float(self.cfg.get("max_run_s", 3600)):
                raise LimitViolation(f"{action}.{key} exceeds max_run_s ({self.cfg.get('max_run_s', 3600)}) in config.json")

    def _plan(self, job: Job) -> tuple[str, dict, float]:
        p = job.params
        if job.action == "ocp":
            return "ocv", {"duration_s": float(p["duration_s"]), "sample_s": float(p["sample_s"])}, float(p["duration_s"])
        if job.action == "ca":
            return "chrono", {"e_V": float(p["e_V"]), "duration_s": float(p["duration_s"]), "sample_s": float(p["sample_s"])}, float(p["duration_s"])
        if job.action == "cv":
            e0, e1, e2 = float(p["e_init_V"]), float(p["e_vertex1_V"]), float(p["e_vertex2_V"])
            ef = e0 if p.get("e_final_V") is None else float(p["e_final_V"])
            rate = float(p["scan_rate_mV_s"]) / 1000
            span = abs(e1 - e0) + abs(e2 - e1) + abs(ef - e2) + (int(p["cycles"]) - 1) * (abs(e1 - e2) + abs(e2 - e1))
            plan = {"e_init_V": e0, "e_vertex1_V": e1, "e_vertex2_V": e2, "e_final_V": ef, "scan_rate_mV_s": float(p["scan_rate_mV_s"]),
                    "step_V": float(p["step_V"]), "cycles": int(p["cycles"]), "expected_s": span / rate}
            return "rcv", plan, span / rate
        raise InvalidValue(f"unhandled action {job.action}")

    def _data_path(self, job: Job, ext: str) -> pathlib.Path:
        data_dir = pathlib.Path(self.cfg.get("data_dir") or HERE / "data")
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir / f"{time.strftime('%Y%m%d-%H%M%S')}_{job.action}_{job.id}.{ext}"

    def on_invoke(self, job: Job):
        hw = self._hw()
        if job.action == "eis":
            return self._eis(job, hw)
        kind, plan, expected = self._plan(job)
        path = self._data_path(job, "csv")
        scale = self.time_scale()
        run = self._vendor(f"start {kind}", lambda: hw.start(kind, plan))
        self.is_running, self.cell_on = True, kind != "ocv"
        n, last = 0, None
        started = time.monotonic()
        try:
            with path.open("w", newline="") as f:
                w = csv.writer(f)
                w.writerow(("t_s", "e_V", "i_A"))
                while True:
                    alive = run.alive()
                    rows = run.poll()
                    for t, v, i in rows:
                        w.writerow((round(t, 4), round(v, 6), "" if i is None else i))
                        last = (t, v, i)
                    n += len(rows)
                    if not alive and not rows:
                        break
                    try:
                        self.checkpoint(job, min(0.99, (last[0] / expected) if last and expected else 0.0))
                    except JobCancelled:
                        self._vendor("stop", run.stop)
                        raise
                    time.sleep(min(0.2, max(0.005, 0.2 * scale)))
                    if time.monotonic() - started > (expected + 60) * scale + 5:
                        self._vendor("stop", run.stop)
                        raise DeviceFault("the acquisition did not finish in the expected time; cell turned off")
        finally:
            self.is_running = False
            try:
                hw.cell(False)
            except Exception:                                # noqa: BLE001
                pass
            self.cell_on = False
        if run.error:
            raise DeviceFault(f"acquisition failed: {run.error}. Trace kept at {path}")
        result = {"technique": job.action, "device": hw.section, "points": n, "file": str(path),
                  "duration_s": round(last[0], 3) if last else 0.0,
                  "e_final_V": round(last[1], 6) if last else None,
                  "i_final_A": (None if last is None or last[2] is None else last[2])}
        self.last_result = result
        self.emit_signal("last_result", result)
        return result

    def _eis(self, job: Job, hw) -> dict:
        p = job.params
        freqs = frequencies(float(p["f_start_Hz"]), float(p["f_end_Hz"]), int(p["points_per_decade"]))
        path = self._data_path(job, "csv")
        rows = []
        self.is_running, self.cell_on = True, True
        try:
            with path.open("w", newline="") as f:
                w = csv.writer(f)
                w.writerow(("f_Hz", "z_real_ohm", "z_imag_ohm", "z_mod_ohm", "z_phase_deg"))
                for k, fz in enumerate(freqs):
                    try:
                        self.checkpoint(job, k / len(freqs), frequency_Hz=fz)
                    except JobCancelled:
                        raise
                    zr, zi = self._vendor("ReadZ", lambda: hw.measure_z(fz, float(p["e_dc_V"]), float(p["amplitude_mV"]) / 1000))
                    mod, ph = math.hypot(zr, zi), math.degrees(math.atan2(zi, zr))
                    w.writerow((f"{fz:.6g}", f"{zr:.6g}", f"{zi:.6g}", f"{mod:.6g}", f"{ph:.3f}"))
                    rows.append((fz, zr, zi, mod))
        finally:
            self.is_running = False
            try:
                hw.end_z()
            except Exception:                                # noqa: BLE001
                pass
            self.cell_on = False
        result = {"technique": "eis", "device": hw.section, "points": len(rows), "file": str(path),
                  "f_start_Hz": freqs[0], "f_end_Hz": freqs[-1],
                  "r_hf_ohm": round(rows[0][1], 4) if rows else None, "z_mod_lf_ohm": round(rows[-1][3], 4) if rows else None}
        self.last_result = result
        self.emit_signal("last_result", result)
        return result

    def on_estop(self) -> None:
        """Turn the cell off: SetCell CellOff, then Close the potentiostat object so no output stays applied."""
        try:
            if self.hw is not None:
                self.hw.cell(False)
                self.hw.close()
        except Exception:                                    # noqa: BLE001  must not raise
            pass
        self.hw = None
        self.cell_on = False
        self.is_running = False

    @classmethod
    def discover(cls, cfg: dict, what: str) -> list:
        if what != "device":
            return []
        import win32com.client as com                        # noqa: PLC0415
        return [str(s) for s in com.Dispatch("GamryCOM.GamryDeviceList").EnumSections()]

    @classmethod
    def probe(cls, cfg: dict) -> str:
        hw = GamryBackend(cfg)
        hw.open()
        try:
            return f"Gamry instrument {hw.section} opened through GamryCOM"
        finally:
            hw.close()
