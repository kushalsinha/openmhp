"""MHP driver for a microplate reader with one of three vendor automation routes, chosen in config.json:

  backend: bmg      BMG LABTECH CLARIOstar / PHERAstar / Omega / VANTAstar through the Reader Control
                    software's "BMG LABTECH Remote Control" ActiveX (ProgID BMG_ActiveX.BMGRemoteControl,
                    32-bit COM, comtypes): Init, PlateIn, PlateOut, Temp, Run; GetInfo("Status"/"Temp1"/"Error").
  backend: softmax  Molecular Devices SpectraMax under SoftMax Pro 7.x through the Automation API
                    (.NET "SoftMax Pro AutomationClient.dll", WCF on port 9000, pythonnet): OpenFile,
                    OpenDrawer/CloseDrawer, GetDrawerStatus, StartRead/StopRead, GetInstrumentStatus,
                    GetTemperature/SetTemperature, ExportAs.
  backend: spark    Tecan Spark through its SiLA 2 server (sila2 client): a Reader Service feature with
                    door open/close and ExecuteMethod(MethodName); identifiers unverified, see references.

Each backend holds every vendor call behind the same small interface; the driver validates, runs the
read as a job, parses the exported plate table, and the twin swaps in SimBackend.
"""
from __future__ import annotations

import csv
import json
import pathlib
import re
import threading
import time

from openmhp.driver import DeviceFault, Driver, InvalidValue, Job, JobCancelled

HERE = pathlib.Path(__file__).parent
BACKENDS = ("bmg", "softmax", "spark")
WELL = re.compile(r"^[A-P](?:[1-9]|1[0-9]|2[0-4])$")


def load_config() -> dict:
    p = HERE / "config.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def parse_plate_export(text: str) -> dict:
    """Well -> value from an ASCII export: either rows 'A1<sep>value' or a grid (row letter, then one
    value per column under a header of column numbers). Best effort; unparsed cells are skipped."""
    wells: dict = {}
    rows = [[c.strip().strip('"') for c in re.split(r"[\t,;]", line)] for line in text.splitlines() if line.strip()]
    for cells in rows:
        if not cells:
            continue
        if WELL.match(cells[0]) and len(cells) >= 2:
            try:
                wells[cells[0]] = float(cells[1])
            except ValueError:
                pass
        elif re.fullmatch(r"[A-P]", cells[0]) and len(cells) >= 2:
            for i, c in enumerate(cells[1:], start=1):
                try:
                    wells[f"{cells[0]}{i}"] = float(c)
                except ValueError:
                    pass
    return wells


def text_name(s: str, what: str) -> str:
    if not isinstance(s, str) or not s.strip() or re.search(r"[\\/\x00-\x1f]", s) or ".." in s:
        raise InvalidValue(f"{what} must be a plain name without folders, got {s!r}")
    return s.strip()


# ------------------------------------------------------------------------------- backends ---- #
class BmgBackend:
    """BMG LABTECH Remote Control ActiveX, as used by the open-source AD-SDL bmg_module (MIT)."""

    def __init__(self, cfg: dict):
        self.cfg, self.rc = cfg, None

    def open(self) -> None:
        import comtypes.client                                   # 32-bit Python on the reader PC
        self.rc = comtypes.client.CreateObject("BMG_ActiveX.BMGRemoteControl")
        rc = self.rc.OpenConnection(self.cfg.get("control", "CLARIOstar"))
        if rc:
            raise DeviceFault(f"BMG OpenConnection({self.cfg.get('control', 'CLARIOstar')}) returned error {rc}")
        self._exec(["Init"])

    def _exec(self, args: list) -> None:
        rc = self.rc.ExecuteAndWait([str(a) for a in args])
        if rc:
            raise DeviceFault(f"BMG {args[0]} returned error {rc}: {self.rc.GetInfo('Error')}")

    def status(self) -> str:
        return str(self.rc.GetInfo("Status"))

    def reading(self) -> bool:
        return self.status().lower().startswith("busy")

    def plate_in(self) -> bool:
        return str(self.rc.GetInfo("PlateOut")).strip() in ("0", "False", "false")      # unverified GetInfo item

    def temperature(self):
        v = self.rc.GetInfo("Temp1")                              # tenths of a degree, bottom plate
        return float(v) / 10 if v not in (None, "") else None

    def set_temperature(self, c) -> None:
        self._exec(["Temp", "0.0" if c is None else f"{float(c):.1f}"])

    def tray_in(self) -> None:
        self._exec(["PlateIn"])

    def tray_out(self) -> None:
        self._exec(["PlateOut"])

    def start_read(self, protocol: str, plate_id: str, export_path: pathlib.Path) -> None:
        # argument order as bmg_module sends it; the BMG ActiveX manual (0415N0006J) defines it: unverified
        self._exec(["Run", protocol, self.cfg.get("protocol_dir", ""), self.cfg.get("data_dir", ""),
                    plate_id, "", "", str(export_path.parent), export_path.name])

    def abort(self) -> None:
        self._exec(["Terminate"])                                 # unverified command name


class SoftMaxBackend:
    """SoftMax Pro 7.x Automation API (doc 5049094 C): SMPAutomationClient over WCF, commands queued,
    results on the CommandCompleted event."""

    def __init__(self, cfg: dict):
        self.cfg, self.c, self.results, self.done = cfg, None, {}, {}

    def open(self) -> None:
        import clr                                               # pythonnet
        clr.AddReference(self.cfg.get("client_dll", "SoftMax Pro AutomationClient"))
        from SoftMaxPro.AutomationClient import SMPAutomationClient
        self.c = SMPAutomationClient()
        self.c.CommandCompleted += self._on_done                 # unverified: event wiring from pythonnet
        if not self.c.Initialize(self.cfg.get("host", "localhost"), int(self.cfg.get("port", 9000))):
            raise DeviceFault("SoftMax Pro automation server did not accept the connection (is automation enabled?)")

    def _on_done(self, sender, e):
        self.results[e.QueueId] = (e.StringResult, e.IntResult, e.DoubleResult)
        ev = self.done.get(e.QueueId)
        if ev:
            ev.set()

    def _call(self, name: str, *args, timeout: float = 60):
        qid = getattr(self.c, name)(*args)
        ev = self.done.setdefault(qid, threading.Event())
        if not ev.wait(timeout):
            raise DeviceFault(f"SoftMax Pro {name} did not complete within {timeout} s")
        return self.results.pop(qid, (None, None, None))

    def status(self) -> str:
        return str(self._call("GetInstrumentStatus")[0])

    def reading(self) -> bool:
        return self.status().upper() in ("BUSY", "INITIALIZING", "STOPPING")

    def plate_in(self) -> bool:
        return str(self._call("GetDrawerStatus")[0]).lower().startswith("closed")        # unverified string values

    def temperature(self):
        return self._call("GetTemperature")[2]

    def set_temperature(self, c) -> None:
        self._call("SetTemperature", 0.0 if c is None else float(c))

    def tray_in(self) -> None:
        self._call("CloseDrawer")

    def tray_out(self) -> None:
        self._call("OpenDrawer")

    def start_read(self, protocol: str, plate_id: str, export_path: pathlib.Path) -> None:
        folder = pathlib.Path(self.cfg.get("protocol_dir", ""))
        self._call("OpenFile", str(folder / protocol))
        self._call("SetTitle", plate_id)                          # unverified: SetTitle argument
        self._export = export_path
        self.c.StartRead()                                        # completes when the read ends

    def finish(self, export_path: pathlib.Path) -> None:
        from SoftMaxPro.AutomationClient import SMPAutomationClient
        self._call("ExportAs", str(export_path), SMPAutomationClient.ExportAsFormat.PLATE, timeout=120)   # unverified enum path

    def abort(self) -> None:
        self.c.StopRead()


class SparkBackend:
    """Tecan Spark SiLA 2 server through the sila2 client; feature and command identifiers unverified."""

    def __init__(self, cfg: dict):
        self.cfg, self.client, self.cmd = cfg, None, None

    def open(self) -> None:
        from sila2.client import SilaClient
        self.client = SilaClient(self.cfg.get("host", "localhost"), int(self.cfg.get("port", 50052)), insecure=True)
        self.feature = getattr(self.client, self.cfg.get("feature", "ReaderService"))    # unverified feature name

    def status(self) -> str:
        if self.cmd is not None and not self.cmd.done:
            return "Running"
        return "Ready"

    def reading(self) -> bool:
        return self.cmd is not None and not self.cmd.done

    def plate_in(self) -> bool:
        return not bool(self.feature.DoorOpen.get())             # unverified property

    def temperature(self):
        return None                                              # not read through the Spark SiLA feature

    def set_temperature(self, c) -> None:
        raise InvalidValue("the Spark SiLA 2 route exposes no temperature command; set it in the SparkControl method")

    def tray_in(self) -> None:
        self.feature.CloseDoor()                                 # unverified command name

    def tray_out(self) -> None:
        self.feature.OpenDoor()                                  # unverified command name

    def start_read(self, protocol: str, plate_id: str, export_path: pathlib.Path) -> None:
        self.cmd = self.feature.ExecuteMethod(MethodName=protocol)   # observable command (Hinkel et al. 2023)

    def finish(self, export_path: pathlib.Path) -> None:
        self.cmd.get_responses()
        self.cmd = None

    def abort(self) -> None:
        if self.cmd is not None:
            self.cmd.cancel()                                    # SiLA CancelController


# --------------------------------------------------------------------------------- driver ---- #
class PlateReader(Driver):
    def setup(self) -> None:
        self.cfg = load_config()
        self.hw = None
        self.reading = False
        self.last_result = None
        self.setpoint = None

    def make_backend(self):
        kind = self.cfg.get("backend")
        if kind not in BACKENDS:
            raise DeviceFault("config.json is missing or names no backend (bmg | softmax | spark); copy config.example.json")
        return {"bmg": BmgBackend, "softmax": SoftMaxBackend, "spark": SparkBackend}[kind](self.cfg)

    def time_scale(self) -> float:
        return 1.0

    def _hw(self):
        if self.hw is None:
            try:
                hw = self.make_backend()
                hw.open()
            except DeviceFault:
                raise
            except ImportError as e:
                raise DeviceFault(f"the {self.cfg.get('backend')} route needs its client library: {e}") from None
            except Exception as e:                               # noqa: BLE001  vendor boundary
                raise DeviceFault(f"cannot reach the reader through {self.cfg.get('backend')}: {type(e).__name__}: {e}",
                                  {"transient": True}) from None
            self.hw = hw
        return self.hw

    def _vendor(self, what, fn):
        try:
            return fn()
        except (DeviceFault, InvalidValue):
            raise
        except Exception as e:                                   # noqa: BLE001  vendor boundary
            raise DeviceFault(f"{what} failed: {type(e).__name__}: {e}", {"transient": True}) from None

    def on_read(self, name: str):
        if name == "connected":
            try:
                self._hw()
                return True
            except DeviceFault:
                return False
        if name == "status":
            return self._vendor("status", self._hw().status)
        if name == "plate_in":
            return bool(self._vendor("plate_in", self._hw().plate_in))
        if name == "temperature":
            v = self._vendor("temperature", self._hw().temperature)
            return round(float(v), 1) if v is not None else None
        if name == "temperature_setpoint":
            return self.setpoint
        if name == "robot_access_ready":
            hw = self._hw()
            return (not self.reading) and (not self._vendor("status", hw.reading)) and (not self._vendor("plate_in", hw.plate_in))
        if name == "last_result":
            return self.last_result
        raise InvalidValue(f"unknown signal {name}")

    def on_write(self, name: str, value):
        if name != "temperature_setpoint":
            raise InvalidValue(f"unknown setting {name}")
        self._vendor("set_temperature", lambda: self._hw().set_temperature(value))
        self.setpoint = value
        return None

    def validate_params(self, action: str, params: dict) -> None:
        if action != "read":
            return
        text_name(params.get("protocol"), "read.protocol")
        text_name(params.get("plate_id"), "read.plate_id")
        allowed = self.cfg.get("allowed_protocols") or []
        if allowed and params["protocol"] not in allowed:
            raise InvalidValue(f"protocol {params['protocol']!r} is not in allowed_protocols")
        ep = params.get("export_path")
        if ep is not None and (not isinstance(ep, str) or ".." in ep):
            raise InvalidValue("read.export_path must be a plain file name or null")

    def on_invoke(self, job: Job):
        hw = self._hw()
        if job.action == "plate_in":
            self._vendor("PlateIn", hw.tray_in)
            return {"plate_in": bool(self._vendor("plate_in", hw.plate_in))}
        if job.action == "plate_out":
            if self._vendor("status", hw.reading):
                raise DeviceFault("a read is running on the instrument (started outside this package); wait for it")
            self._vendor("PlateOut", hw.tray_out)
            return {"plate_in": bool(self._vendor("plate_in", hw.plate_in))}
        if job.action != "read":
            raise InvalidValue(f"unhandled action {job.action}")
        p = job.params
        export_dir = pathlib.Path(self.cfg.get("export_dir") or (pathlib.Path.home() / ".openmhp" / "sim-data" / "plate-reader"))
        export_dir.mkdir(parents=True, exist_ok=True)
        name = p.get("export_path") or f"{time.strftime('%Y%m%d_%H%M%S')}_{p['plate_id']}_{p['protocol']}.csv"
        export = export_dir / name
        started = time.time()
        self._vendor("Run", lambda: hw.start_read(p["protocol"], p["plate_id"], export))
        self.reading = True
        scale = self.time_scale()
        limit = float(self.cfg.get("max_read_minutes", 240)) * 60 * scale
        try:
            time.sleep(min(1.0, 2 * scale))
            while self._vendor("status", hw.reading):
                if time.time() - started > limit:
                    raise DeviceFault(f"the read is still running after {limit / scale / 60:.0f} min (max_read_minutes)")
                try:
                    self.checkpoint(job, phase="reading")
                except JobCancelled:
                    self._vendor("abort", hw.abort)
                    raise
                time.sleep(min(1.0, 5 * scale))
            if hasattr(hw, "finish"):
                self._vendor("export", lambda: hw.finish(export))
        finally:
            self.reading = False
        wells = parse_plate_export(export.read_text(encoding="utf-8", errors="replace")) if export.is_file() else {}
        result = {"protocol": p["protocol"], "plate_id": p["plate_id"], "file": str(export), "wells": wells,
                  "duration_s": round((time.time() - started) / scale, 1)}
        if not wells:
            result["warning"] = "no plate table could be parsed from the export; check the protocol's ASCII export settings"
        self.last_result = result
        self.emit_signal("last_result", result)
        return result

    def on_estop(self) -> None:
        try:
            if self.hw is not None:
                if self.reading or self.hw.reading():
                    self.hw.abort()
                self.hw.tray_in()
        except Exception:                                        # noqa: BLE001  must not raise
            pass
        self.reading = False

    # ---- setup-time check (`mhp node setup`) ---------------------------------------------- #
    @classmethod
    def probe(cls, cfg: dict) -> str:
        kind = cfg.get("backend")
        if kind not in BACKENDS:
            raise DeviceFault("backend must be one of bmg, softmax, spark")
        hw = {"bmg": BmgBackend, "softmax": SoftMaxBackend, "spark": SparkBackend}[kind](cfg)
        try:
            hw.open()
        except ImportError as e:
            raise DeviceFault(f"client library missing for the {kind} route: {e}") from None
        return f"{kind}: reader answers, status {hw.status()}"
