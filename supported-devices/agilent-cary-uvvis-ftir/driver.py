"""MHP driver for Agilent Cary 60/3500 UV-Vis (Cary WinUV) and Cary 630 FTIR (MicroLab): a file-based route.

Neither Cary WinUV nor MicroLab offers a public API. The package writes one request file per scan into a
watched folder on the instrument PC, a helper (or a person) runs the scan in the vendor software and exports
the spectrum as CSV into a results folder, and this driver waits for the CSV that carries the job's token
and parses it. Every folder and file format lives in CaryBackend so the simulated twin can replace it.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import time

from openmhp.driver import DeviceFault, Driver, InvalidValue, Job, JobCancelled, LimitViolation

HERE = pathlib.Path(__file__).parent
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.\-]{0,63}$")
RANGES = {"uvvis": (190.0, 1100.0), "ftir": (650.0, 4000.0)}       # nm; /cm
FTIR_RESOLUTIONS = (1, 2, 4, 8, 16)                                 # /cm, MicroLab method choices (unverified)
X_LABEL = {"uvvis": "Wavelength (nm)", "ftir": "Wavenumber (cm-1)"}


def load_config() -> dict:
    p = HERE / "config.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def _num(s: str):
    try:
        return float(s.strip())
    except ValueError:
        return None


def parse_spectrum_csv(text: str, mode: str) -> dict:
    """Two-column ASCII (csv) export: optional title line(s), a header such as 'Wavelength (nm),Abs',
    then x,y rows. Only the numeric pairs are trusted; the header supplies the unit labels when present."""
    xs, ys, x_label, y_label = [], [], None, None
    for raw in text.splitlines():
        line = raw.strip().lstrip("﻿")
        if not line:
            continue
        cells = [c.strip().strip('"') for c in line.split(",")]
        if len(cells) < 2:
            continue
        x, y = _num(cells[0]), _num(cells[1])
        if x is None or y is None:
            if not xs and x_label is None and not any(_num(c) is not None for c in cells[:2]):
                x_label, y_label = cells[0], cells[1]
            continue
        xs.append(x); ys.append(y)
    if not xs:
        raise DeviceFault("the exported file has no numeric x,y rows", {"transient": False, "recovery": "operator"})
    xl = (x_label or "").lower()
    x_unit = "nm" if "nm" in xl else "/cm" if "cm" in xl else ("nm" if mode == "uvvis" else "/cm")
    y_unit = (y_label or "Abs").strip() or "Abs"
    i = max(range(len(ys)), key=ys.__getitem__)
    return {"points": len(xs), "x_unit": x_unit, "y_unit": y_unit, "max_abs": round(ys[i], 5),
            "lambda_max_nm": round(xs[i], 2) if x_unit == "nm" else None,
            "x_min": min(xs), "x_max": max(xs)}


class CaryBackend:
    """The only class that touches the vendor software's folders."""

    REQUEST_EXT = ".json"

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.log: list[str] = []

    def _dir(self, key: str) -> pathlib.Path:
        d = self.cfg.get(key)
        if not d:
            raise DeviceFault(f"config.json has no {key} (copy config.example.json and fill it in)")
        return pathlib.Path(d)

    def open(self) -> None:
        for key in ("import_dir", "results_dir"):
            p = self._dir(key)
            if not p.is_dir():
                raise DeviceFault(f"{key} {p} is not a folder on this machine", {"transient": True, "recovery": "operator"})
            if not os.access(p, os.W_OK):
                raise DeviceFault(f"{key} {p} is not writable", {"transient": True, "recovery": "operator"})

    def pending(self) -> list[pathlib.Path]:
        return sorted(self._dir("import_dir").glob("mhp_*" + self.REQUEST_EXT))

    def queue_depth(self) -> int:
        return len(self.pending())

    def write_request(self, token: str, params: dict) -> str:
        """One JSON request per scan (the contract the helper reads); optionally an ADL sketch beside it."""
        req = {"token": token, "software": "Cary WinUV" if params["mode"] == "uvvis" else "MicroLab",
               "sample_name": params["sample_name"], "mode": params["mode"],
               "start": params["start"], "stop": params["stop"], "step": params["step"],
               "baseline": params["baseline"], "export": f"{token}.csv", "written": time.time()}
        folder = self._dir("import_dir")
        tmp = folder / f"{token}.part"
        tmp.write_text(json.dumps(req, indent=1), encoding="utf-8")
        final = folder / f"{token}{self.REQUEST_EXT}"
        tmp.replace(final)                                   # the helper never sees a half-written file
        if params["mode"] == "uvvis" and self.cfg.get("write_adl"):
            (folder / f"{token}.adl").write_text(self.adl_sketch(token, params), encoding="utf-8")
        self.log.append(f"request {final.name}")
        return str(final)

    @staticmethod
    def adl_sketch(token: str, p: dict) -> str:
        """An ADL program outline for the Scan application. Every statement is unverified (see
        references/file_formats.md): the lab adapts it against the ADL Help in Cary WinUV before use."""
        return "\n".join([
            f"' OpenMHP scan request {token} -- adapt against Cary WinUV ADL Help before running (unverified)",
            f"' Scan {p['start']}..{p['stop']} nm, data interval {p['step']} nm, baseline={'on' if p['baseline'] else 'off'}",
            f"' Export: Save Data As, ASCII (csv), file {token}.csv in the results folder",
            ""])

    def find_result(self, token: str) -> pathlib.Path | None:
        hits = sorted(self._dir("results_dir").glob(f"*{token}*.csv"))
        return hits[0] if hits else None

    def read_result(self, path: pathlib.Path, mode: str) -> dict:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            raise DeviceFault(f"cannot read {path.name}: {e}", {"transient": True, "recovery": "retry_after"}) from None
        return parse_spectrum_csv(text, mode)

    def withdraw(self, token: str | None = None) -> list[str]:
        """Remove this package's request files the helper has not consumed yet (the only stop we have)."""
        gone = []
        for p in self.pending():
            if token is None or p.stem == token:
                try:
                    p.unlink(); gone.append(p.name)
                    adl = p.with_suffix(".adl")
                    if adl.is_file():
                        adl.unlink()
                except OSError:
                    pass
        self.log.append(f"withdraw {gone}")
        return gone

    def poll(self) -> None:
        """Called once per wait cycle; nothing to do on the real folders (the twin writes results here)."""


class Device(Driver):
    def setup(self) -> None:
        self.cfg = load_config()
        self.hw = None
        self.last_result = None
        self.withdrawn: set[str] = set()              # request tokens an e-stop took back

    def make_backend(self):
        return CaryBackend(self.cfg)

    def time_scale(self) -> float:
        return 1.0

    def _hw(self):
        if self.hw is None:
            hw = self.make_backend()
            try:
                hw.open()
            except DeviceFault:
                raise
            except Exception as e:                           # noqa: BLE001
                raise DeviceFault(f"cannot reach the watched folders: {type(e).__name__}: {e}") from None
            self.hw = hw
        return self.hw

    def on_read(self, name: str):
        if name == "connected":
            try:
                self._hw().open()                            # re-checked on every read: a share can drop
                return True
            except DeviceFault:
                return False
        if name == "queue_depth":
            return self._hw().queue_depth()
        if name == "last_result":
            return self.last_result
        raise InvalidValue(f"unknown signal {name}")

    def validate_params(self, action: str, params: dict) -> None:
        if action != "scan":
            return
        name = params.get("sample_name")
        if not isinstance(name, str) or not NAME_RE.match(name):
            raise InvalidValue("scan.sample_name must be 1-64 characters: letters, digits, space, '_', '.', '-'")
        mode = params.get("mode")
        lo, hi = RANGES[mode]
        start, stop, step = params.get("start"), params.get("stop"), params.get("step")
        for k, v in (("start", start), ("stop", stop)):
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not lo <= v <= hi:
                raise LimitViolation(f"scan.{k}={v!r} outside the {mode} range {lo}..{hi}", {"min": lo, "max": hi, "mode": mode})
        if abs(start - stop) < 10:
            raise InvalidValue("scan.start and scan.stop must differ by at least 10 (nm or /cm)")
        if mode == "uvvis":
            if not 0.1 <= step <= 10:
                raise LimitViolation(f"scan.step={step!r}: UV-Vis data interval must be 0.1..10 nm", {"min": 0.1, "max": 10})
        elif step not in FTIR_RESOLUTIONS:
            raise InvalidValue(f"scan.step={step!r}: FTIR resolution must be one of {list(FTIR_RESOLUTIONS)} /cm")

    def on_invoke(self, job: Job):
        if job.action != "scan":
            raise InvalidValue(f"unhandled action {job.action}")
        hw = self._hw()
        p = job.params
        token = f"mhp_{job.id}"
        started = time.time()
        req = hw.write_request(token, p)
        self.emit_signal("queue_depth", hw.queue_depth())
        poll = float(self.cfg.get("poll_s", 5)) * self.time_scale()
        limit = float(self.cfg.get("result_wait_s", 900)) * self.time_scale()
        t0 = time.monotonic()
        try:
            path = None
            while True:
                self.checkpoint(job, min(0.9, (time.monotonic() - t0) / limit), phase="waiting for export")
                hw.poll()
                path = hw.find_result(token)
                if path is not None:
                    break
                if token in self.withdrawn:
                    raise DeviceFault(f"request {token} was withdrawn by an emergency stop before anyone acted on it",
                                      {"transient": False, "recovery": "operator"})
                if time.monotonic() - t0 > limit:
                    raise DeviceFault(f"no export named *{token}*.csv appeared in results_dir within "
                                      f"{self.cfg.get('result_wait_s', 900)} s; the request {pathlib.Path(req).name} is "
                                      f"left in import_dir for a person to see",
                                      {"transient": True, "recovery": "retry_after", "request": req})
                time.sleep(poll)
        except JobCancelled:
            hw.withdraw(token)                            # not yet taken: nothing runs; taken: it finishes in the vendor software
            raise
        time.sleep(min(poll, 1.0))                            # let the exporter close the file
        parsed = hw.read_result(path, p["mode"])
        result = {"sample_name": p["sample_name"], "mode": p["mode"], "file": str(path),
                  "points": parsed["points"], "x_unit": parsed["x_unit"], "y_unit": parsed["y_unit"],
                  "max_abs": parsed["max_abs"], "lambda_max_nm": parsed["lambda_max_nm"],
                  "duration_s": round((time.time() - started) / self.time_scale(), 1)}
        self.last_result = result
        self.emit_signal("last_result", result)
        self.emit_signal("queue_depth", hw.queue_depth())
        return result

    def on_estop(self) -> None:
        """No command stops a Cary; the package withdraws every request the helper has not picked up."""
        if self.hw is not None:
            self.withdrawn.update(pathlib.Path(n).stem for n in self.hw.withdraw())

    @classmethod
    def probe(cls, cfg: dict) -> str:
        hw = CaryBackend(cfg)
        hw.open()
        return (f"request folder {cfg.get('import_dir')} and results folder {cfg.get('results_dir')} are writable; "
                f"{hw.queue_depth()} request(s) waiting")
