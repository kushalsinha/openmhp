"""MHP driver (template) for a Bruker Dektak XT under Vision64 through a TCP command channel.

Bruker documents Vision64's in-GUI automation (multi-site recipes, auto-save with a file-name macro, a database
CSV the analysis recipe appends results to) and, for its profilers, an optional "TCP/IP Runtime Control
Server" whose command set is not public. VisionBackend is therefore written against the shape such a channel
must have (a line-oriented text protocol: load a recipe, set a field, run, status, abort, tower up); every
command string is read from config.json `commands` and marked `# unverified`. What is verified: the .OPDx
12-byte header (Gwyddion's reader) and the database CSV mechanism. The twin runs the same driver against a
fake server. See references/vision64_files.md.
"""
from __future__ import annotations

import csv
import io
import json
import pathlib
import re
import socket
import time

from openmhp.driver import DeviceFault, Driver, InvalidValue, Job, JobCancelled, LimitViolation

HERE = pathlib.Path(__file__).parent
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
OPDX_MAGIC = b"VCA DATA\x01\x00\x00\x55"
COMMAND_DEFAULTS = {"status": "STATUS", "load_recipe": "LOAD_RECIPE {path}", "set": "SET {field} {value}", "run": "RUN",
                    "abort": "ABORT", "tower_up": "TOWER_HOME"}
COLUMN_DEFAULTS = {"sample": "Sample ID", "step_height": "ASH"}
STATUS_WORDS = {"idle": "idle", "ready": "idle", "scanning": "scanning", "running": "scanning", "measuring": "scanning",
                "tower": "tower_moving", "moving": "tower_moving", "error": "error", "fault": "error"}
RANGES = {"6.5um": 6.5, "65.5um": 65.5, "524um": 524.0, "1mm": 1000.0}
PROFILES = {"hills": "Hills", "valleys": "Valleys", "hills_and_valleys": "Hills and Valleys"}


def load_config() -> dict:
    p = HERE / "config.json"
    return json.loads(p.read_text(encoding="utf-8") or "{}") if p.is_file() else {}


def check_opdx(data: bytes) -> None:
    """A Vision64 dataset starts with `VCA DATA` 01 00 00 55 (Gwyddion's Dektak OPDx reader)."""
    if not data.startswith(OPDX_MAGIC):
        raise DeviceFault("the auto-saved file does not start with the OPDx header (VCA DATA)", {"transient": False, "recovery": "operator"})


def db_row(text: str, columns: dict, sample_name: str) -> dict | None:
    """The database CSV row whose sample column equals `sample_name` (the last such row), as {column: value}."""
    rows = [r for r in csv.reader(io.StringIO(text)) if any(c.strip() for c in r)]
    if not rows:
        return None
    names = [c.strip() for c in rows[0]]
    if columns["sample"] not in names:
        return None
    si = names.index(columns["sample"])
    hit = None
    for r in rows[1:]:
        if si < len(r) and r[si].strip() == sample_name:
            hit = dict(zip(names, (c.strip() for c in r)))
    return hit


class VisionBackend:
    """Every command to Vision64. The command strings are configuration because none could be verified."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.commands = {**COMMAND_DEFAULTS, **(cfg.get("commands") or {})}
        self.sock = None
        self.log: list[str] = []

    def open(self) -> None:
        if not self.cfg.get("host") or not self.cfg.get("data_dir"):
            raise DeviceFault("config.json is missing host/data_dir (copy config.example.json and fill it in)",
                              {"transient": False, "recovery": "operator"})
        try:
            self.sock = socket.create_connection((self.cfg["host"], int(self.cfg.get("port", 5000))), timeout=5)
        except OSError as e:
            raise DeviceFault(f"cannot reach Vision64's control server at {self.cfg['host']}:{self.cfg.get('port', 5000)}: {e}",
                              {"transient": True, "recovery": "retry_after"}) from None
        self.status()

    def send(self, line: str) -> str:
        self.sock.sendall((line + "\r\n").encode("ascii"))       # unverified: line-oriented ASCII, CRLF
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = self.sock.recv(4096)
            if not chunk:
                raise DeviceFault("Vision64's control server closed the connection", {"transient": True, "recovery": "retry_after"})
            buf += chunk
        reply = buf.decode("ascii", errors="replace").strip()
        self.log.append(f"{line} -> {reply}")
        if reply.upper().startswith(("ERR", "NAK")):            # unverified error reply
            raise DeviceFault(f"Vision64 refused {line.split()[0]}: {reply}", {"transient": False, "recovery": "operator"})
        return reply

    def status(self) -> str:
        reply = self.send(self.commands["status"]).lower()        # unverified
        for word, mapped in STATUS_WORDS.items():
            if word in reply:
                return mapped
        return "idle" if reply else "error"

    def set_field(self, field: str, value) -> None:
        self.send(self.commands["set"].format(field=field, value=value))   # unverified field names

    def start_scan(self, recipe: str, sample_id: str, p: dict, duration_s: float, out_file: str) -> None:
        self.send(self.commands["load_recipe"].format(path=str(pathlib.PureWindowsPath(self.cfg.get("recipes_dir") or "") / recipe)))  # unverified
        self.set_field("SampleID", sample_id)
        self.set_field("Length", f"{p['length_um']:.1f}")          # um
        self.set_field("Duration", f"{duration_s:.1f}")            # s
        self.set_field("Force", f"{p['force_mg']:.2f}")            # mg
        self.set_field("Range", f"{RANGES[p.get('range', '65.5um')]:.1f}")   # um
        self.set_field("Profile", PROFILES[p.get("profile", "hills_and_valleys")])
        self.set_field("AutoSaveFileName", out_file)
        self.send(self.commands["run"])                            # unverified

    def abort(self) -> None:
        self.send(self.commands["abort"])                          # unverified

    def tower_up(self) -> None:
        self.send(self.commands["tower_up"])                       # unverified

    def opdx_path(self, name: str) -> pathlib.Path | None:
        p = pathlib.Path(self.cfg["data_dir"]) / (name + ".OPDx")
        return p if p.is_file() else None

    def db_result(self, sample_name: str) -> tuple[pathlib.Path | None, dict | None]:
        f = self.cfg.get("db_csv")
        if not f or not pathlib.Path(f).is_file():
            return None, None
        cols = {**COLUMN_DEFAULTS, **(self.cfg.get("columns") or {})}
        return pathlib.Path(f), db_row(pathlib.Path(f).read_text(encoding="utf-8-sig", errors="replace"), cols, sample_name)

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass


class DektakVision(Driver):
    def setup(self) -> None:
        self.cfg = load_config()
        self.hw = None
        self.scanning = False
        self.last_result = None

    def make_backend(self):
        return VisionBackend(self.cfg)

    def time_scale(self) -> float:
        return 1.0

    def _hw(self) -> VisionBackend:
        if self.hw is None:
            hw = self.make_backend()
            try:
                hw.open()
            except DeviceFault:
                raise
            except Exception as e:                               # noqa: BLE001  vendor boundary
                raise DeviceFault(f"cannot open the Vision64 channel: {type(e).__name__}: {e}", {"transient": True, "recovery": "retry_after"}) from None
            self.hw = hw
        return self.hw

    def _vendor(self, what: str, fn):
        try:
            return fn()
        except (DeviceFault, InvalidValue, JobCancelled):
            raise
        except Exception as e:                                   # noqa: BLE001  vendor boundary
            raise DeviceFault(f"Vision64 {what} failed: {type(e).__name__}: {e}", {"transient": True, "recovery": "retry_after"}) from None

    def on_read(self, name: str):
        if name == "connected":
            try:
                self._hw()
                return True
            except DeviceFault:
                return False
        if name == "status":
            return self._vendor("status", self._hw().status)
        if name == "last_result":
            return self.last_result
        raise InvalidValue(f"unknown signal {name}")

    def validate_params(self, action: str, params: dict) -> None:
        if action != "scan":
            return
        r = str(params.get("recipe", ""))
        if not r.lower().endswith(".visrcp") or "/" in r or "\\" in r or ".." in r:
            raise InvalidValue("recipe must be a bare .visrcp file name in recipes_dir")
        if not _NAME.match(str(params.get("sample_id", ""))):
            raise InvalidValue("sample_id must be letters, digits, underscore, hyphen or dot (it names the dataset)")
        duration = params["length_um"] / params["speed_um_s"]
        max_d = float(self.cfg.get("max_duration_s", 600))
        if duration > max_d:
            raise LimitViolation(f"length / speed gives a {duration:.0f} s scan; max_duration_s is {max_d:.0f}", {"max": max_d})
        if duration < 3:
            raise InvalidValue(f"length / speed gives a {duration:.1f} s scan; a scan needs at least 3 s (slow down or lengthen it)")

    def on_invoke(self, job: Job):
        hw = self._hw()
        if job.action == "tower_up":
            self._vendor("tower_up", hw.tower_up)
            return {"tower": "home"}
        if job.action != "scan":
            raise InvalidValue(f"unhandled action {job.action}")
        p = job.params
        if self._vendor("status", hw.status) != "idle":
            raise DeviceFault(f"Vision64 is {hw.status()}, not idle", {"transient": True, "recovery": "retry_after"})
        token = f"mhp_{time.strftime('%Y%m%d')}_{job.id.replace('job_', '')}"
        name = f"{p['sample_id']}_{token}"
        out_file = str(pathlib.PureWindowsPath(self.cfg["data_dir"]) / (name + ".OPDx")) if "\\" in str(self.cfg["data_dir"]) \
            else str(pathlib.Path(self.cfg["data_dir"]) / (name + ".OPDx"))
        duration = p["length_um"] / p["speed_um_s"]
        started = time.time()
        self._vendor("start_scan", lambda: hw.start_scan(p["recipe"], name, p, duration, out_file))
        self.scanning = True
        scale = self.time_scale()
        poll = float(self.cfg.get("poll_s", 1)) * scale
        t0 = time.monotonic()
        try:
            time.sleep(min(0.5, 2 * scale))
            while self._vendor("status", hw.status) != "idle":
                try:
                    self.checkpoint(job, min(0.9, (time.monotonic() - t0) / max((duration + 10) * scale, 1e-6)), phase="scanning")
                except JobCancelled:
                    self._vendor("abort", hw.abort)
                    self._vendor("tower_up", hw.tower_up)
                    raise
                if time.monotonic() - t0 > (duration + 120) * scale:
                    self._vendor("abort", hw.abort)
                    raise DeviceFault(f"scan still running after {duration + 120:.0f} s; aborted", {"transient": False, "recovery": "operator"})
                time.sleep(poll)
        finally:
            self.scanning = False
        wait = float(self.cfg.get("result_wait_s", 120)) * scale
        deadline = time.monotonic() + wait
        path = None
        while path is None and time.monotonic() < deadline:
            path = hw.opdx_path(name)
            if path is None:
                time.sleep(min(poll, 0.5 * scale))
        if path is None:
            raise DeviceFault(f"no {name}.OPDx in {self.cfg['data_dir']} after {wait / scale:.0f} s: is the recipe's auto-save set?",
                              {"transient": True, "recovery": "retry_after"})
        check_opdx(path.read_bytes()[:16])
        db_path, row = hw.db_result(name)
        cols = {**COLUMN_DEFAULTS, **(self.cfg.get("columns") or {})}
        step = None
        if row is not None and row.get(cols["step_height"], "") not in ("", None):
            try:
                step = float(row[cols["step_height"]])
            except ValueError:
                step = None
            unit = str(self.cfg.get("step_height_unit", "nm")).lower()
            if step is not None and unit in ("um", "µm"):
                step *= 1000
            elif step is not None and unit in ("a", "angstrom"):
                step /= 10
        result = {"sample_id": p["sample_id"], "file": str(path), "db_file": str(db_path) if db_path else None,
                  "step_height_nm": round(step, 3) if step is not None else None, "scan_length_um": float(p["length_um"]),
                  "stylus_force_mg": float(p["force_mg"]), "duration_s": round((time.time() - started) / scale, 1)}
        self.last_result = result
        self.emit_signal("last_result", result)
        return result

    def on_estop(self) -> None:
        try:
            if self.hw is not None:
                self.hw.abort()
                self.hw.tower_up()
                self.hw.log.append("estop: abort, tower up")
        except Exception:                                        # noqa: BLE001  must not raise
            pass
        self.scanning = False

    @classmethod
    def discover(cls, cfg: dict, what: str) -> list:
        if what == "recipes" and cfg.get("recipes_dir") and pathlib.Path(cfg["recipes_dir"]).is_dir():
            return sorted(f.name for f in pathlib.Path(cfg["recipes_dir"]).glob("*.visrcp"))
        return []

    @classmethod
    def probe(cls, cfg: dict) -> str:
        hw = VisionBackend(cfg)
        hw.open()
        try:
            return f"Vision64 control server answers; status {hw.status()}"
        finally:
            hw.close()
