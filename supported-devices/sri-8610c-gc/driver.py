"""MHP driver for an SRI 8610C gas chromatograph through PeakSimple's .NET connector (pythonnet, Windows).

The connector calls are the ones the open-source catalight package uses for the same instrument.
Vendor calls are confined to PeakSimpleBackend.
"""
from __future__ import annotations

import json
import pathlib
import re
import time

from openmhp.driver import DeviceFault, Driver, InvalidValue, Job, JobCancelled

HERE = pathlib.Path(__file__).parent


def load_config() -> dict:
    p = HERE / "config.json"
    return json.loads(p.read_text()) if p.is_file() else {}


def parse_results(text: str) -> list[dict]:
    """Best-effort peak table: rows of component, retention, area[, height][, concentration]."""
    peaks = []
    for line in text.splitlines():
        cells = [c.strip().strip('"') for c in re.split(r"[\t,;]", line) if c.strip()]
        nums = []
        for c in cells:
            try:
                nums.append(float(c))
            except ValueError:
                pass
        names = [c for c in cells if not re.fullmatch(r"[-+0-9.eE]+", c)]
        if len(nums) >= 2 and names:
            peak = {"component": names[0], "retention_min": nums[0], "area": nums[1]}
            if len(nums) >= 3:
                peak["extra"] = nums[2:]
            peaks.append(peak)
    return peaks


def control_run_time_s(control_path) -> float | None:
    """Run length from the control file: '<CHANNEL 1 TIME>=' is in milliseconds."""
    try:
        for line in pathlib.Path(control_path).read_text(errors="replace").splitlines():
            if line.startswith("<CHANNEL 1 TIME>="):
                return int(line.split("=")[-1].strip()) / 1000
    except (OSError, ValueError):
        pass
    return None


def parse_asc(text: str) -> dict:
    """PeakSimple ASCII chromatogram (.ASC): 'key=value' header with the sampling rate (Hz) and point
    count, then one reading per line (first comma field). Returns a peak list from a simple
    threshold integration; calibrated results come from PeakSimple's own result file."""
    rate, y = None, []
    for line in text.splitlines():
        s = line.strip()
        if not s or "IPOINT" in s:
            continue
        if "=" in s:
            if "RATE" in s.upper() and rate is None:
                m = re.search(r"=\s*([0-9.]+)", s)
                rate = float(m.group(1)) if m else None
            continue
        try:
            y.append(float(s.split(",")[0]) / 1000)
        except ValueError:
            continue
    if not y or not rate:
        return {"points": len(y), "peaks": []}
    srt = sorted(y)
    base = srt[len(srt) // 2]
    noise = (srt[int(len(srt) * 0.75)] - srt[int(len(srt) * 0.25)]) or 1e-9
    thr = base + 8 * noise
    peaks, i, dt_min = [], 0, 1 / rate / 60
    while i < len(y):
        if y[i] > thr:
            j = i
            while j < len(y) and y[j] > thr:
                j += 1
            apex = max(range(i, j), key=y.__getitem__)
            if j - i >= 3:
                peaks.append({"retention_min": round(apex * dt_min, 3), "height": round(y[apex] - base, 4),
                              "area": round(sum(v - base for v in y[i:j]) * dt_min * 60, 4)})
            i = j
        else:
            i += 1
    return {"points": len(y), "rate_hz": rate, "duration_min": round(len(y) * dt_min, 2), "peaks": peaks}


class PeakSimpleBackend:
    """SRI's PeaksimpleConnector.dll through pythonnet. The same calls catalight uses
    (catalight/equipment/gc_control/sri_gc.py): Connect, LoadControlFile, SetRunning, IsRunning."""
    TRIES = 3

    def __init__(self, cfg: dict):
        self.cfg, self.channel = cfg, int(cfg.get("channel", 1))

    def open(self) -> None:
        if not self.cfg.get("connector_dll"):
            raise DeviceFault("config.json is missing (copy config.example.json and fill it in)")
        import clr                                    # pythonnet
        clr.AddReference(self.cfg["connector_dll"])
        import Peaksimple
        self.conn = Peaksimple.PeaksimpleConnector()
        self.conn.Connect()

    def _retry(self, what: str, call):
        last = None
        for _ in range(self.TRIES):
            try:
                return call()
            except Exception as e:                    # noqa: BLE001  ConnectionWriteFailedException is transient
                last = e
                if type(e).__name__ == "NoConnectionException":
                    break
                time.sleep(1)
        raise DeviceFault(f"PeakSimple {what} failed: {type(last).__name__}: {last}. If the link was broken, "
                          "restart PeakSimple and this device server; the connector cannot reconnect on its own.")

    def start(self, control_path: str) -> None:
        self._retry("LoadControlFile", lambda: self.conn.LoadControlFile(control_path))
        time.sleep(5)                                 # PeakSimple needs a moment after loading a control file
        self._retry("SetRunning", lambda: self.conn.SetRunning(self.channel, True))

    def is_running(self) -> bool:
        return bool(self._retry("IsRunning", lambda: self.conn.IsRunning(self.channel)))

    def stop(self) -> None:
        self.conn.SetRunning(self.channel, False)

    def collect(self, started: float, sample) -> list[tuple[str, str]]:
        """Every file PeakSimple wrote into the results folder since the run started -> [(path, text)]."""
        folder = pathlib.Path(self.cfg["results_dir"])
        deadline = time.monotonic() + float(self.cfg.get("result_wait_s", 60))
        while True:
            files = sorted((f for f in folder.iterdir() if f.is_file() and f.stat().st_mtime >= started
                            and f.suffix.lower() in (".asc", ".res", ".log", ".txt", ".csv")), key=lambda f: f.name)
            if files or time.monotonic() > deadline:
                time.sleep(1 if files else 0)         # let PeakSimple finish writing the last file
                return [(str(f), f.read_text(errors="replace")) for f in files]
            time.sleep(1)


class SRI8610C(Driver):
    def setup(self) -> None:
        self.cfg = load_config()
        self.hw = None
        self.is_running, self.runs, self.runs_day, self.last_result = False, 0, time.strftime("%Y%m%d"), None

    def make_backend(self):
        return PeakSimpleBackend(self.cfg)

    def time_scale(self) -> float:
        return 1.0

    def _hw(self):
        if self.hw is None:
            hw = self.make_backend()
            try:
                hw.open()
            except Exception as e:                    # noqa: BLE001
                raise DeviceFault(f"cannot reach PeakSimple: {type(e).__name__}: {e}") from None
            self.hw = hw
        return self.hw

    def on_read(self, name: str):
        if name == "connected":
            try:
                self._hw()
                return True
            except DeviceFault:
                return False
        if name == "running":
            return self.is_running
        if name == "runs_today":
            return self.runs if self.runs_day == time.strftime("%Y%m%d") else 0
        if name == "last_result":
            return self.last_result
        raise InvalidValue(f"unknown signal {name}")

    def validate_params(self, action: str, params: dict) -> None:
        if action == "run_method":
            name = params.get("control_file")
            if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9 _.\-]+\.con", name, re.I) or ".." in name:
                raise InvalidValue("run_method.control_file must be a plain file name ending in .con (no folders)")

    def on_invoke(self, job: Job):
        if job.action != "run_method":
            raise InvalidValue(f"unhandled action {job.action}")
        hw = self._hw()
        p = job.params
        control = pathlib.Path(self.cfg.get("control_dir", "")) / p["control_file"]
        if self.cfg.get("control_dir") and not control.is_file():
            raise InvalidValue(f"control file {p['control_file']} is not in the method folder")
        run_s = float(p.get("run_time_s") or control_run_time_s(control) or 0)
        if run_s <= 0:
            raise InvalidValue("run_time_s was not given and the control file has no '<CHANNEL 1 TIME>=' line")
        started = time.time()
        hw.start(str(control))
        self.is_running = True
        try:
            scale = self.time_scale()
            t0, limit = time.monotonic(), (run_s * 1.5 + 60) * scale
            time.sleep(min(2.0, run_s * scale))        # give the run a moment to show as running
            while hw.is_running():
                elapsed = time.monotonic() - t0
                if elapsed > limit:
                    raise DeviceFault(f"PeakSimple still reports running after {limit:.0f} s (method is {run_s:.0f} s)")
                try:
                    self.checkpoint(job, min(0.98, elapsed / (run_s * scale)), phase="chromatogram")
                except JobCancelled:
                    hw.stop()
                    raise
                time.sleep(min(1.0, run_s * scale / 20))
            files = hw.collect(started, p.get("sample"))
        finally:
            self.is_running = False
        if time.strftime("%Y%m%d") != self.runs_day:
            self.runs, self.runs_day = 0, time.strftime("%Y%m%d")
        self.runs += 1
        result = {"control_file": p["control_file"], "sample": p.get("sample"), "run_time_s": run_s,
                  "injected_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(started)),
                  "files": [f for f, _ in files], "chromatograms": {}, "peaks": [], "raw": ""}
        for path, text in files:
            name = pathlib.PurePath(path).name
            if name.lower().endswith(".asc"):
                result["chromatograms"][name] = parse_asc(text)
            else:
                result["peaks"] += parse_results(text)
                result["raw"] += text[:2000]
        if not files:
            result["warning"] = ("PeakSimple wrote no files into results_dir; in the control file set "
                                 "'<DATA FILE PATH>=' to that folder and the POSTRUN SAVE DATA / SAVE RESULTS options to 1")
        self.last_result = {k: v for k, v in result.items() if k != "raw"}
        self.emit_signal("last_result", self.last_result)
        self.emit_signal("runs_today", self.runs)
        return result

    def on_estop(self) -> None:
        try:
            if self.hw is not None and self.is_running:
                self.hw.stop()
        except Exception:                             # noqa: BLE001  must not raise
            pass
        self.is_running = False
