"""MHP driver for TA Instruments Discovery / Q-series DSC and TGA under TRIOS (file-based route, Windows PC).

The package writes one run-list file per sample into the folder the lab's TRIOS automation
(TRIOS Auto / autoloader run queue, or a person importing the run list) reads, waits for TRIOS
to export the run as a text file into the export folder, parses the curve and estimates an
onset and a peak (DSC) or the mass loss (TGA). TRIOS loads the pan, runs the temperature
program and exports; the package touches no hardware. Formats: references/trios_files.md.
"""
from __future__ import annotations

import csv
import json
import os
import pathlib
import re
import time

from openmhp.driver import DeviceFault, Driver, InvalidValue, Job, LimitViolation

HERE = pathlib.Path(__file__).parent
RUNLIST_COLUMNS = ["Sample Name", "Instrument", "Pan Position", "Sample Mass (mg)", "Procedure", "Data File", "Export File"]
MAX_C = {"dsc": 600.0, "tga": 1000.0}
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}$")
_NUM = re.compile(r"^[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?$")
_STEP_META = re.compile(r"^(step name|number of points|procedure name|proceduresegments)$", re.I)


def load_config() -> dict:
    p = HERE / "config.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def procedure_text(segments: list[dict]) -> str:
    """The segments as TRIOS writes them in a procedure summary: 'Ramp 10.00 °C/min to 300.00 °C; Isothermal for 5.00 min'."""
    parts = []
    for s in segments:
        if s["type"] == "ramp":
            parts.append(f"Ramp {s['rate_k_min']:.2f} °C/min to {s['to_c']:.2f} °C")
        else:
            parts.append(f"Isothermal for {s['hold_min']:.2f} min at {s['to_c']:.2f} °C")
        if s["type"] == "ramp" and s.get("hold_min"):
            parts.append(f"Isothermal for {s['hold_min']:.2f} min")
    return "; ".join(parts)


def program_duration_s(segments: list[dict], start_c: float = 25.0) -> float:
    t, temp = 0.0, start_c
    for s in segments:
        if s["type"] == "ramp":
            t += abs(s["to_c"] - temp) / s["rate_k_min"] * 60
            temp = s["to_c"]
        t += (s.get("hold_min") or 0) * 60
    return t


def parse_trios_export(text: str) -> dict:
    """A TRIOS text export: header lines (key<TAB>value), then one or more [step] blocks, each with a
    column-name row, a units row and tab-separated data rows. Returns {header, columns, rows}."""
    header, columns, units, rows = {}, [], [], []
    in_step = False
    for raw in text.splitlines():
        line = raw.rstrip("\r\n")
        if not line.strip():
            continue
        if line.strip().lower() == "[step]":
            in_step, columns, units = True, [], []
            continue
        cells = line.split("\t")
        if cells and cells[0].strip().lower() == "data point":          # RheoJAX's example prefixes rows
            cells = cells[1:]
        if in_step:
            if _STEP_META.match(cells[0].strip()):
                header[cells[0].strip()] = "\t".join(cells[1:]).strip()   # Step name, Number of points
                continue
            if not columns:
                if any(_NUM.match(c.strip()) for c in cells[:2]):
                    continue                                        # a stray numeric line before the header
                columns = [c.strip() for c in cells]
                continue
            numeric = all(_NUM.match(c.strip()) for c in cells[: len(columns)] if c.strip())
            if not units and not numeric:
                units = [c.strip() for c in cells]
                continue
            if numeric and len(cells) >= 2:
                try:
                    rows.append([float(c) if c.strip() else float("nan") for c in cells[: len(columns)]])
                except ValueError:
                    pass
        elif len(cells) >= 2:
            header[cells[0].strip()] = "\t".join(cells[1:]).strip()
    return {"header": header, "columns": columns, "rows": rows}


def _col(columns: list[str], *words: str) -> int | None:
    for i, c in enumerate(columns):
        cl = c.lower()
        if all(w in cl for w in words):
            return i
    return None


def analyse(parsed: dict, instrument: str) -> dict:
    """Simple estimates, documented as such: a straight baseline from the first tenth of the curve, the
    extremum of the deviation from it (peak), and the intersection of the baseline with the tangent at
    the steepest point of the leading edge (onset). TGA: mass loss over the run and the same tangent onset
    on the weight curve; peak is the temperature of the fastest loss."""
    cols, rows = parsed["columns"], parsed["rows"]
    it = _col(cols, "temperature")
    if instrument == "dsc":
        iy = _col(cols, "heat flow", "normalized")
        iy = _col(cols, "heat flow") if iy is None else iy
    else:
        iy = _col(cols, "weight", "%")
        iy = _col(cols, "weight") if iy is None else iy
    if it is None or iy is None or len(rows) < 20:
        return {"onset_c": None, "peak_c": None, "mass_loss_pct": None}
    T = [r[it] for r in rows]
    Y = [r[iy] for r in rows]
    n0 = max(5, len(T) // 10)
    # baseline through the first tenth (least squares)
    mt, my = sum(T[:n0]) / n0, sum(Y[:n0]) / n0
    sxx = sum((t - mt) ** 2 for t in T[:n0]) or 1e-9
    slope = sum((t - mt) * (y - my) for t, y in zip(T[:n0], Y[:n0])) / sxx
    base = [my + slope * (t - mt) for t in T]
    dev = [y - b for y, b in zip(Y, base)]
    ipk = max(range(len(dev)), key=lambda i: abs(dev[i]))
    if abs(dev[ipk]) < 1e-12:
        return {"onset_c": None, "peak_c": None, "mass_loss_pct": None}
    # steepest point on the leading edge (between the baseline region and the peak)
    best, ib = 0.0, None
    for i in range(n0, max(n0 + 1, ipk)):
        dT = T[i + 1] - T[i - 1] if 0 < i < len(T) - 1 else 0
        if abs(dT) > 1e-9:
            g = (dev[i + 1] - dev[i - 1]) / dT
            if abs(g) > best:
                best, ib = abs(g), i
    onset = None
    if ib is not None and best > 0:
        g = (dev[ib + 1] - dev[ib - 1]) / (T[ib + 1] - T[ib - 1])
        onset = T[ib] - dev[ib] / g                           # tangent meets the baseline (dev = 0)
    out = {"onset_c": round(onset, 2) if onset is not None else None, "peak_c": round(T[ipk], 2), "mass_loss_pct": None}
    if instrument == "tga":
        y0, y1 = sum(Y[:n0]) / n0, sum(Y[-n0:]) / n0
        out["mass_loss_pct"] = round(100.0 * (y0 - y1) / y0, 2) if y0 else None
        out["peak_c"] = round(T[ib], 2) if ib is not None else None   # fastest loss, not an extremum
    return out


class TriosBackend:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.log: list[str] = []
        self.pending: dict[str, pathlib.Path] = {}

    def _dir(self, key: str) -> pathlib.Path:
        d = self.cfg.get(key)
        if not d:
            raise DeviceFault(f"config.json is missing {key} (copy config.example.json and fill it in)",
                              {"transient": False, "recovery": "operator"})
        return pathlib.Path(d)

    def open(self) -> None:
        for key in ("run_dir", "export_dir"):
            d = self._dir(key)
            if not d.is_dir():
                raise DeviceFault(f"{key} {d} does not exist", {"transient": True, "recovery": "operator"})
        if not os.access(self._dir("run_dir"), os.W_OK):
            raise DeviceFault(f"run_dir {self._dir('run_dir')} is not writable", {"transient": True, "recovery": "operator"})

    def write_run(self, token: str, p: dict, export_name: str) -> pathlib.Path:
        path = self._dir("run_dir") / f"{token}.csv"
        row = [p["sample_name"], p["instrument"].upper(), "" if p.get("pan_position") is None else str(p["pan_position"]),
               f"{p['mass_mg']:.3f}", procedure_text(p["program"]["segments"]), f"{token}.tri", export_name]
        tmp = path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, lineterminator="\r\n")
            w.writerow(RUNLIST_COLUMNS)
            w.writerow(row)
        os.replace(tmp, path)
        self.pending[token] = path
        self.log.append(f"wrote run list {path.name}: {p['sample_name']} {p['instrument']} pan {p.get('pan_position')} {p['mass_mg']} mg")
        return path

    def queue_depth(self) -> int:
        try:
            return sum(1 for f in self._dir("run_dir").glob("*.csv") if f.is_file())
        except DeviceFault:
            return 0

    def picked_up(self, token: str) -> bool:
        p = self.pending.get(token)
        return p is not None and not p.exists()

    def export_path(self, export_name: str) -> pathlib.Path | None:
        p = self._dir("export_dir") / export_name
        return p if p.is_file() else None

    def live_temperature(self) -> float | None:
        """The last Temperature of a live export TRIOS keeps appending to, when config names one."""
        f = self.cfg.get("live_export_file")
        if not f or not pathlib.Path(f).is_file():
            return None
        try:
            parsed = parse_trios_export(pathlib.Path(f).read_text(encoding="utf-8", errors="replace"))
        except OSError:
            return None
        it = _col(parsed["columns"], "temperature")
        if it is None or not parsed["rows"]:
            return None
        return round(parsed["rows"][-1][it], 2)

    def parse(self, export_name: str, instrument: str) -> dict:
        p = self.export_path(export_name)
        parsed = parse_trios_export(p.read_text(encoding="utf-8", errors="replace"))
        if not parsed["rows"]:
            raise DeviceFault(f"{p.name} holds no data rows", {"transient": True, "recovery": "retry_after"})
        return {"file": str(p), "points": len(parsed["rows"]), **analyse(parsed, instrument)}

    def abort(self) -> list[str]:
        removed = []
        for token, p in list(self.pending.items()):
            if p.exists():
                try:
                    p.unlink()
                    removed.append(p.name)
                except OSError:
                    pass
            self.pending.pop(token, None)
        self.log.append(f"estop: removed {len(removed)} queued run list(s): {removed}")
        return removed


class TADscTga(Driver):
    def setup(self) -> None:
        self.cfg = load_config()
        self.hw = None
        self.last_result = None
        self.stopped = False

    def make_backend(self):
        return TriosBackend(self.cfg)

    def time_scale(self) -> float:
        return 1.0

    def _hw(self) -> TriosBackend:
        if self.hw is None:
            hw = self.make_backend()
            hw.open()
            self.hw = hw
        return self.hw

    def on_read(self, name: str):
        if name == "connected":
            try:
                self._hw()
                return True
            except DeviceFault:
                return False
        if name == "queue_depth":
            return self._hw().queue_depth()
        if name == "sample_temperature":
            return self._hw().live_temperature()
        if name == "last_result":
            return self.last_result
        raise InvalidValue(f"unknown signal {name}")

    def validate_params(self, action: str, params: dict) -> None:
        if action != "queue_run":
            return
        if not _NAME.match(str(params.get("sample_name", ""))):
            raise InvalidValue("sample_name must be letters, digits, spaces, underscore, hyphen or dot")
        inst = params["instrument"]
        segs = params["program"]["segments"]
        if not segs:
            raise InvalidValue("program.segments must hold at least one segment")
        hi = float((self.cfg.get("max_temperature_c") or {}).get(inst, MAX_C[inst]))
        for i, s in enumerate(segs):
            if s["to_c"] > hi:
                raise LimitViolation(f"segments[{i}].to_c={s['to_c']} above the {inst.upper()} limit {hi} degC",
                                     {"max": hi, "instrument": inst})
            if s["type"] == "ramp" and s.get("rate_k_min") is None:
                raise InvalidValue(f"segments[{i}]: a ramp needs rate_k_min")
            if s["type"] == "isothermal" and not s.get("hold_min"):
                raise InvalidValue(f"segments[{i}]: an isothermal segment needs hold_min")
        pans = int(self.cfg.get("pan_positions", 50))
        if params.get("pan_position") is not None and not 1 <= int(params["pan_position"]) <= pans:
            raise LimitViolation(f"pan_position {params['pan_position']} is outside 1..{pans}", {"min": 1, "max": pans})
        max_h = float(self.cfg.get("max_run_hours", 12))
        if program_duration_s(segs) > max_h * 3600:
            raise LimitViolation(f"the program would take {program_duration_s(segs) / 3600:.1f} h; max_run_hours is {max_h}",
                                 {"max": max_h})

    def on_invoke(self, job: Job):
        if job.action != "queue_run":
            raise InvalidValue(f"unhandled action {job.action}")
        hw = self._hw()
        p = job.params
        self.stopped = False
        token = f"mhp_{time.strftime('%Y%m%d')}_{job.id.replace('job_', '')}"
        export_name = f"{token}.txt"
        if hw.export_path(export_name) is not None:
            raise InvalidValue(f"{export_name} already exists in export_dir")
        started = time.time()
        hw.write_run(token, p, export_name)
        self.checkpoint(job, 0.05, phase="queued for TRIOS")
        expected = (program_duration_s(p["program"]["segments"]) + float(self.cfg.get("load_equilibrate_s", 300))) * self.time_scale()
        poll = float(self.cfg.get("poll_s", 10)) * self.time_scale()
        wait = float(self.cfg.get("result_wait_s", 2 * expected / self.time_scale() + 1800)) * self.time_scale()
        t0 = time.monotonic()
        try:
            while hw.export_path(export_name) is None:
                if self.stopped:
                    raise DeviceFault("stopped: the queued run list was removed; a run already started must be "
                                      "stopped in TRIOS", {"transient": False, "recovery": "operator"})
                elapsed = time.monotonic() - t0
                if hw.picked_up(token):
                    self.checkpoint(job, min(0.95, 0.1 + 0.85 * elapsed / max(expected, 1e-6)), phase="running")
                    t = hw.live_temperature()
                    if t is not None:
                        self.emit_signal("sample_temperature", t)
                else:
                    self.checkpoint(job, 0.05, phase="waiting for TRIOS to read the run list")
                if elapsed > wait:
                    raise DeviceFault(f"no export {export_name} after {wait / self.time_scale():.0f} s; the run list "
                                      f"{token}.csv is left in {self.cfg.get('run_dir')}",
                                      {"transient": True, "recovery": "retry_after"})
                time.sleep(poll)
            time.sleep(min(poll, 2.0 * self.time_scale()))          # let TRIOS finish writing the export
        finally:
            hw.pending.pop(token, None)
        parsed = hw.parse(export_name, p["instrument"])
        result = {"sample_name": p["sample_name"], **parsed,
                  "duration_s": round((time.time() - started) / self.time_scale(), 1)}
        self.last_result = result
        self.emit_signal("last_result", result)
        return result

    def on_estop(self) -> None:
        self.stopped = True
        if self.hw is not None:
            self.hw.abort()

    @classmethod
    def probe(cls, cfg: dict) -> str:
        hw = TriosBackend(cfg)
        hw.open()
        return f"run lists go to {cfg.get('run_dir')}, exports are read from {cfg.get('export_dir')} ({hw.queue_depth()} waiting)"
