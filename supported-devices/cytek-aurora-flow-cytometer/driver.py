"""MHP driver for a Cytek Aurora / Northern Lights under SpectroFlo: a file-based route.

SpectroFlo has no public API. The package writes a worklist CSV (tube or well, sample name, stop criteria, flow
rate) into a watched folder, a helper or a person acquires the sample in SpectroFlo, SpectroFlo writes the FCS 3.1
file (and, optionally, a statistics CSV) into the export folder, and this driver waits for the FCS file carrying
the job's token and reads its TEXT segment. The FCS 3.1 reader follows the ISAC normative reference; every
SpectroFlo file layout lives in SpectroFloBackend so the simulated twin can replace it.
"""
from __future__ import annotations

import csv
import json
import os
import pathlib
import re
import time

from openmhp.driver import DeviceFault, Driver, InvalidValue, Job, JobCancelled, LimitViolation

HERE = pathlib.Path(__file__).parent
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.\-]{0,63}$")
POSITION_RE = re.compile(r"^(?:[A-H](?:[1-9]|1[0-2])|T(?:[1-9]|[1-3][0-9]|40))$")   # plate well A1..H12, or tube T1..T40
FLOW_RATES = {"low": 15, "medium": 30, "high": 60}                     # uL/min, Aurora User's Guide 52-70001-0C
STATS_COLUMNS = ("Population", "Events", "% Parent")


def load_config() -> dict:
    p = HERE / "config.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def read_fcs_text(path: pathlib.Path) -> dict:
    """FCS 3.1 (ISAC normative reference, section 3.1-3.2): a 58-byte HEADER ('FCS3.1', 4 spaces, six 8-byte
    right-justified ASCII offsets for TEXT begin/end, DATA begin/end, ANALYSIS begin/end), then the primary TEXT
    segment whose first byte is the delimiter and which holds /keyword/value/ pairs. Returns the keywords, the
    version string and the DATA segment length, so $TOT, $PAR and $PnN can be checked against the bytes."""
    try:
        with path.open("rb") as f:
            head = f.read(58)
            if len(head) < 58 or not head[:3] == b"FCS":
                raise DeviceFault(f"{path.name} is not an FCS file (no 'FCS' identifier)", {"transient": False, "recovery": "operator"})
            version = head[:6].decode("ascii", "replace")
            def off(a, b):
                s = head[a:b].decode("ascii", "replace").strip()
                return int(s) if s else 0
            t0, t1, d0, d1 = off(10, 18), off(18, 26), off(26, 34), off(34, 42)
            f.seek(t0)
            text = f.read(t1 - t0 + 1)
    except OSError as e:
        raise DeviceFault(f"cannot read {path.name}: {e}", {"transient": True, "recovery": "retry_after"}) from None
    if not text:
        raise DeviceFault(f"{path.name}: empty TEXT segment", {"transient": False, "recovery": "operator"})
    delim = text[:1]
    parts = text[1:].split(delim)
    if parts and parts[-1].strip() == b"":
        parts = parts[:-1]
    kw = {}
    for i in range(0, len(parts) - 1, 2):
        kw[parts[i].decode("utf-8", "replace").strip()] = parts[i + 1].decode("utf-8", "replace")
    if d0 == 0 and kw.get("$BEGINDATA"):                       # a DATA segment beyond 99,999,999 bytes: offsets in TEXT
        d0, d1 = int(kw["$BEGINDATA"]), int(kw["$ENDDATA"])
    return {"version": version, "keywords": kw, "data_bytes": (d1 - d0 + 1) if d1 >= d0 > 0 else 0,
            "data_end": d1, "size": path.stat().st_size}


def fcs_summary(path: pathlib.Path) -> dict:
    info = read_fcs_text(path)
    kw = info["keywords"]
    try:
        tot, par = int(kw["$TOT"]), int(kw["$PAR"])
    except (KeyError, ValueError):
        raise DeviceFault(f"{path.name}: $TOT or $PAR missing from the TEXT segment", {"transient": False, "recovery": "operator"}) from None
    channels = [kw.get(f"$P{n}N", f"P{n}") for n in range(1, par + 1)]
    if info["size"] <= info["data_end"]:
        raise DeviceFault(f"{path.name}: the file is {info['size']} bytes but its DATA segment is declared to end at byte "
                          f"{info['data_end']}; the export may be incomplete", {"transient": True, "recovery": "retry_after"})
    if kw.get("$DATATYPE") == "F" and info["data_bytes"] and info["data_bytes"] != tot * par * 4:
        raise DeviceFault(f"{path.name}: DATA segment is {info['data_bytes']} bytes, expected {tot * par * 4} for "
                          f"$TOT={tot} $PAR={par} floats; the export may be incomplete", {"transient": True, "recovery": "retry_after"})
    return {"events": tot, "parameters": par, "channels": channels, "version": info["version"]}


class SpectroFloBackend:
    """The only class that touches SpectroFlo's folders."""

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
        return sorted(self._dir("import_dir").glob("mhp_*.csv"))

    def queue_depth(self) -> int:
        return len(self.pending())

    def sheath_level_ok(self):
        """SpectroFlo shows sheath and waste indicators on screen and exports nothing. A lab that writes
        status.json ({"sheath_ok": true}) beside the exports gets it reported; otherwise null."""
        p = self._dir("results_dir") / "status.json"
        if not p.is_file():
            return None
        try:
            v = json.loads(p.read_text(encoding="utf-8")).get("sheath_ok")
        except (OSError, ValueError):
            return None
        return bool(v) if v is not None else None

    def write_worklist(self, token: str, params: dict) -> str:
        folder = self._dir("import_dir")
        tmp = folder / f"{token}.part"
        with tmp.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Position", "Sample Name", "Template", "Stop Events", "Stop Time (s)", "Flow Rate", "Export"])
            w.writerow([params["position"], f"{params['sample_name']} {token}", params.get("template") or "",
                        params["stop_events"], params.get("stop_time_s") or "", params["flow_rate"].capitalize(),
                        f"{token}.fcs"])
        final = folder / f"{token}.csv"
        tmp.replace(final)
        self.log.append(f"worklist {final.name}")
        return str(final)

    def find_result(self, token: str) -> pathlib.Path | None:
        hits = sorted(self._dir("results_dir").glob(f"*{token}*.fcs"))
        return hits[0] if hits else None

    def find_stats(self, token: str) -> pathlib.Path | None:
        hits = sorted(self._dir("results_dir").glob(f"*{token}*.csv"))
        return hits[0] if hits else None

    def read_result(self, path: pathlib.Path) -> dict:
        return fcs_summary(path)

    def withdraw(self, token: str | None = None) -> list[str]:
        gone = []
        for p in self.pending():
            if token is None or p.stem == token:
                try:
                    p.unlink(); gone.append(p.name)
                except OSError:
                    pass
        self.log.append(f"withdraw {gone}")
        return gone

    def poll(self) -> None:
        """Once per wait cycle; nothing to do on the real folders (the twin writes results here)."""


class Device(Driver):
    def setup(self) -> None:
        self.cfg = load_config()
        self.hw = None
        self.last_result = None
        self.withdrawn: set[str] = set()              # request tokens an e-stop took back

    def make_backend(self):
        return SpectroFloBackend(self.cfg)

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
                self._hw().open()
                return True
            except DeviceFault:
                return False
        if name == "queue_depth":
            return self._hw().queue_depth()
        if name == "sheath_level_ok":
            return self._hw().sheath_level_ok()
        if name == "last_result":
            return self.last_result
        raise InvalidValue(f"unknown signal {name}")

    def validate_params(self, action: str, params: dict) -> None:
        if action != "queue_acquisition":
            return
        if not isinstance(params.get("sample_name"), str) or not NAME_RE.match(params["sample_name"]):
            raise InvalidValue("queue_acquisition.sample_name must be 1-64 characters: letters, digits, space, '_', '.', '-'")
        if not isinstance(params.get("position"), str) or not POSITION_RE.match(params["position"]):
            raise InvalidValue("queue_acquisition.position must be a plate well A1..H12 or a tube rack slot T1..T40")
        t = params.get("template")
        if t is not None and (not isinstance(t, str) or not NAME_RE.match(t)):
            raise InvalidValue("queue_acquisition.template must be the experiment template name in SpectroFlo's library")
        allowed = self.cfg.get("allowed_templates") or []
        if allowed and t is not None and t not in allowed:
            raise InvalidValue(f"queue_acquisition.template {t!r} is not in allowed_templates", {"allowed": allowed})
        st = params.get("stop_time_s")
        if st is not None and st < 5:
            raise LimitViolation("queue_acquisition.stop_time_s below 5 s records nothing useful", {"min": 5})

    def on_invoke(self, job: Job):
        if job.action != "queue_acquisition":
            raise InvalidValue(f"unhandled action {job.action}")
        hw = self._hw()
        p = job.params
        token = f"mhp_{job.id}"
        started = time.time()
        req = hw.write_worklist(token, p)
        self.emit_signal("queue_depth", hw.queue_depth())
        poll = float(self.cfg.get("poll_s", 10)) * self.time_scale()
        limit = float(self.cfg.get("result_wait_s", 3600)) * self.time_scale()
        t0 = time.monotonic()
        try:
            while True:
                self.checkpoint(job, min(0.9, (time.monotonic() - t0) / limit), phase="waiting for FCS export")
                hw.poll()
                path = hw.find_result(token)
                if path is not None:
                    break
                if token in self.withdrawn:
                    raise DeviceFault(f"request {token} was withdrawn by an emergency stop before anyone acted on it",
                                      {"transient": False, "recovery": "operator"})
                if time.monotonic() - t0 > limit:
                    raise DeviceFault(f"no FCS file named *{token}*.fcs appeared within {self.cfg.get('result_wait_s', 3600)} s; "
                                      f"the worklist {pathlib.Path(req).name} is left in import_dir for a person to see",
                                      {"transient": True, "recovery": "retry_after", "request": req})
                time.sleep(poll)
        except JobCancelled:
            hw.withdraw(token)                            # not yet taken: nothing runs; taken: it finishes in the vendor software
            raise
        time.sleep(min(poll, 1.0))
        info = hw.read_result(path)
        stats = hw.find_stats(token)
        result = {"sample_name": p["sample_name"], "fcs_file": str(path), "events": info["events"],
                  "parameters": info["parameters"], "channels": info["channels"],
                  "stats_file": str(stats) if stats else None,
                  "duration_s": round((time.time() - started) / self.time_scale(), 1)}
        self.last_result = result
        self.emit_signal("last_result", result)
        self.emit_signal("queue_depth", hw.queue_depth())
        return result

    def on_estop(self) -> None:
        """SpectroFlo's Stop (and its fluidics shutdown) stop the cytometer; the package withdraws queued worklists."""
        if self.hw is not None:
            self.withdrawn.update(pathlib.Path(n).stem for n in self.hw.withdraw())

    @classmethod
    def probe(cls, cfg: dict) -> str:
        hw = SpectroFloBackend(cfg)
        hw.open()
        return (f"worklist folder {cfg.get('import_dir')} and export folder {cfg.get('results_dir')} are writable; "
                f"{hw.queue_depth()} worklist(s) waiting")
