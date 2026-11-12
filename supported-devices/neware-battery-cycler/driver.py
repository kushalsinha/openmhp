"""MHP driver for Neware CT-4008 / BTS 8.0 battery cyclers through the BTS server's TCP interface.

Neware's BTS 8.0 server (Windows) answers an XML command protocol on a TCP socket once the API is
enabled in the BTS client (Help > Mode settings; an activation key may be needed). Each request is
`<?xml version="1.0" encoding="UTF-8" ?><bts version="1.0"><cmd>NAME</cmd>...</bts>` followed by
the terminator `\\n\\n#\\r\\n`, and the reply uses the same envelope and terminator. The command names,
the channel addressing (devtype, devid, subdevid, chlid; a "pipeline" is `devid-subdevid-chlid`) and
the reply list layout are those an open-source (MIT) client for BTS 8.0 uses: connect, getdevinfo,
getchlstatus, inquire, inquiredf, start, stop, download, downloadlog, light, clearflag,
downloadStepLayer. The attribute names inside the inquire reply (workstatus, voltage, current,
capacity, step, cycle, time) and the step-file XML this package writes are marked unverified in
references/bts_api.md. Every socket exchange sits in NewareBackend; the twin replaces it.
"""
from __future__ import annotations

import json
import pathlib
import re
import socket
import time
import xml.etree.ElementTree as ET

from openmhp.driver import DeviceFault, Driver, InvalidValue, Job, JobCancelled, LimitViolation

HERE = pathlib.Path(__file__).parent
HEAD = '<?xml version="1.0" encoding="UTF-8" ?><bts version="1.0">'
TAIL = "</bts>"
TERM = "\n\n#\r\n"
MODES = ("cc_charge", "cc_discharge", "cv_charge", "rest")
BTS_MODE = {"cc_charge": "CC_Chg", "cc_discharge": "CC_DChg", "cv_charge": "CV_Chg", "rest": "Rest"}   # unverified
PIPE_RE = re.compile(r"^\d+-\d+-\d+$")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.\-]{0,63}$")
IDLE_STATES = ("finish", "stop", "protect")            # states the MIT client allows a start from
RUNNING_STATES = ("working", "pause")                   # unverified words


def load_config() -> dict:
    p = HERE / "config.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def records(xml_text: str, list_name: str = "list") -> list[dict]:
    """The elements inside <list> (or another container) as dicts of their attributes plus text."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise DeviceFault(f"BTS server answered something that is not XML: {e}", {"transient": True}) from None
    lst = root.find(list_name)
    if lst is None:
        return []
    out = []
    for el in lst:
        d = dict(el.attrib)
        if el.text and el.text.strip():
            d[el.tag] = el.text.strip()
        out.append(d)
    return out


def render_step_file(steps: list[dict], cycles: int, barcode: str) -> str:
    """The step (protocol) file the start command points at. FORMAT UNVERIFIED: BTS 8.0 saves its step
    files as XML, but the element and attribute names here are this package's own; compare with a file
    exported by the BTS client (references/bts_api.md) before the first hardware run."""
    lines = [HEAD, f'<config type="step" barcode="{barcode}" cycles="{int(cycles)}">']
    for i, s in enumerate(steps, 1):
        attrs = [f'id="{i}"', f'mode="{BTS_MODE[s["mode"]]}"']
        if s.get("current_a") is not None:
            attrs.append(f'current_mA="{float(s["current_a"]) * 1000:.3f}"')
        if s.get("voltage_v") is not None:
            attrs.append(f'volt_V="{float(s["voltage_v"]):.4f}"')
        if s.get("time_limit_s") is not None:
            attrs.append(f'time_s="{float(s["time_limit_s"]):.1f}"')
        if s.get("capacity_limit_ah") is not None:
            attrs.append(f'cap_mAh="{float(s["capacity_limit_ah"]) * 1000:.3f}"')
        lines.append("  <step " + " ".join(attrs) + "/>")
    lines += ["</config>", TAIL]
    return "\n".join(lines) + "\n"


def parse_step_file(text: str) -> tuple[list[dict], int]:
    """Inverse of render_step_file (used by the twin and to echo the protocol in records)."""
    root = ET.fromstring(text)
    cfg = root.find("config")
    inv = {v: k for k, v in BTS_MODE.items()}
    steps = []
    for el in cfg.findall("step"):
        a = el.attrib
        steps.append({"mode": inv[a["mode"]],
                      "current_a": float(a["current_mA"]) / 1000 if "current_mA" in a else None,
                      "voltage_v": float(a["volt_V"]) if "volt_V" in a else None,
                      "time_limit_s": float(a["time_s"]) if "time_s" in a else None,
                      "capacity_limit_ah": float(a["cap_mAh"]) / 1000 if "cap_mAh" in a else None})
    return steps, int(cfg.attrib.get("cycles", 1))


class NewareBackend:
    """One XML request, one XML reply, both terminated by TERM, on the BTS server's socket."""

    def __init__(self, cfg: dict):
        self.cfg, self.sock, self.buf = cfg, None, ""
        self.channels: dict[str, dict] = {}
        self.log: list[str] = []

    # ---- transport ---------------------------------------------------------------------------- #
    def open(self) -> None:
        if not self.cfg.get("host"):
            raise DeviceFault("config.json is missing (copy config.example.json and fill it in)")
        self.sock = socket.create_connection((self.cfg["host"], int(self.cfg.get("port", 502))), timeout=10)
        user, pw = self.cfg.get("user", "admin"), self.cfg.get("password", "")
        self.command(f"<cmd>connect</cmd><username>{user}</username><password>{pw}</password><type>bfgs</type>")
        self.channels = self.devinfo()
        if not self.channels:
            raise DeviceFault("the BTS server lists no channels (getdevinfo); check that devices are working in the BTS client")

    def command(self, body: str, timeout: float = 30) -> str:
        self.log.append(body.split("</cmd>")[0].replace("<cmd>", ""))
        self.sock.settimeout(timeout)
        self.sock.sendall((HEAD + body + TAIL + TERM).encode("utf-8"))
        while not self.buf.endswith(TERM):
            chunk = self.sock.recv(4096)
            if not chunk:
                raise DeviceFault("the BTS server closed the connection", {"transient": True})
            self.buf += chunk.decode("utf-8", errors="replace")
        reply, self.buf = self.buf[: -len(TERM)], ""
        return reply

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            finally:
                self.sock = None

    # ---- commands ----------------------------------------------------------------------------- #
    def devinfo(self) -> dict[str, dict]:
        recs = records(self.command("<cmd>getdevinfo</cmd>"), "middle")
        return {f"{r['devid']}-{r['subdevid']}-{r['Channelid']}": r for r in recs if "Channelid" in r}

    def _attrs(self, pipeline: str) -> str:
        c = self.channels.get(pipeline)
        if c is None:
            raise InvalidValue(f"channel {pipeline!r} is not one the BTS server lists", {"channels": sorted(self.channels)})
        return (f'ip="{c.get("ip", "")}" devtype="{c.get("devtype", "")}" devid="{c["devid"]}" '
                f'subdevid="{c["subdevid"]}" chlid="{c["Channelid"]}"')

    def inquire(self, pipeline: str) -> dict:
        body = f'<cmd>inquire</cmd><list count="1"><inquire {self._attrs(pipeline)} aux="0" barcode="1">true</inquire></list>'
        recs = records(self.command(body))
        return recs[0] if recs else {}

    def inquire_all(self) -> dict[str, dict]:
        pipes = sorted(self.channels)
        body = (f'<cmd>inquire</cmd><list count="{len(pipes)}">'
                + "".join(f'<inquire {self._attrs(p)} aux="0" barcode="1">true</inquire>' for p in pipes) + "</list>")
        recs = records(self.command(body))
        return {p: (recs[i] if i < len(recs) else {}) for i, p in enumerate(pipes)}

    def start(self, pipeline: str, barcode: str, server_step_path: str) -> dict:
        backup = self.cfg.get("backup_dir", "C:\\Neware data")
        body = (f'<cmd>start</cmd><list count="1"><start {self._attrs(pipeline)} barcode="{barcode}">{server_step_path}</start>'
                f'<backup backupdir="{backup}" remotedir="" filenametype="0" customfilename="" addtimewhenrepeat="0" '
                f'createdirbydate="0" filetype="0" backupontime="1" backupontimeinterval="720" backupfree="1" /></list>')
        recs = records(self.command(body, timeout=60))
        r = recs[0] if recs else {}
        if str(r.get("start", "")).lower() != "ok":
            raise DeviceFault(f"the BTS server refused to start channel {pipeline}: {r or 'no record in the reply'}")
        return r

    def stop(self, pipeline: str) -> dict:
        body = f'<cmd>stop</cmd><list count="1"><stop {self._attrs(pipeline)}>true</stop></list>'
        recs = records(self.command(body))
        return recs[0] if recs else {}

    def stop_all(self) -> list[str]:
        """Open every channel: one stop per listed channel (the MIT client also names a `broadcaststop`, unverified)."""
        stopped = []
        for p in sorted(self.channels):
            try:
                self.stop(p)
                stopped.append(p)
            except Exception:                                 # noqa: BLE001  keep stopping the rest
                pass
        return stopped

    # ---- the step file ------------------------------------------------------------------------ #
    def write_step_file(self, token: str, steps: list[dict], cycles: int, barcode: str) -> tuple[str, str]:
        local = pathlib.Path(self.cfg.get("step_dir") or (HERE / "steps"))
        local.mkdir(parents=True, exist_ok=True)
        path = local / f"{token}.xml"
        path.write_text(render_step_file(steps, cycles, barcode), encoding="utf-8")
        server_dir = self.cfg.get("step_dir_on_server") or str(local)
        server_path = str(pathlib.PureWindowsPath(server_dir) / path.name) if "\\" in server_dir or re.match(r"^[A-Za-z]:", server_dir) else str(pathlib.Path(server_dir) / path.name)
        return str(path), server_path


class Device(Driver):
    def setup(self) -> None:
        self.cfg = load_config()
        self.hw = None
        self.channel = self.cfg.get("default_channel")
        self.last_result = None
        self.running: set[str] = set()

    def make_backend(self):
        return NewareBackend(self.cfg)

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
                raise DeviceFault(f"cannot reach the BTS server at {self.cfg.get('host')}:{self.cfg.get('port', 502)}: "
                                  f"{type(e).__name__}: {e}", {"transient": True}) from None
            self.hw = hw
        return self.hw

    def _vendor(self, what: str, fn):
        try:
            return fn()
        except (DeviceFault, InvalidValue):
            raise
        except Exception as e:                               # noqa: BLE001  vendor boundary
            raise DeviceFault(f"BTS {what} failed: {type(e).__name__}: {e}", {"transient": True}) from None

    def _selected(self) -> str:
        hw = self._hw()
        if self.channel is None:
            self.channel = sorted(hw.channels)[0]
        return self.channel

    def _scaled(self, rec: dict) -> dict:
        """One inquire record in SI: V, A, Ah (the API reports mA and mAh like BTSDA exports; unverified)."""
        c = self.cfg
        v = _num(rec.get("voltage")); i = _num(rec.get("current")); q = _num(rec.get("capacity"))
        return {"workstatus": str(rec.get("workstatus", "unknown")).lower(),
                "voltage_v": None if v is None else v * float(c.get("voltage_scale", 1.0)),
                "current_a": None if i is None else i * float(c.get("current_scale", 0.001)),
                "capacity_ah": None if q is None else q * float(c.get("capacity_scale", 0.001)),
                "cycle": int(_num(rec.get("cycle")) or 0), "step": int(_num(rec.get("step")) or 0),
                "time_s": _num(rec.get("time"))}

    def on_read(self, name: str):
        if name == "connected":
            try:
                self._hw()
                return True
            except DeviceFault:
                return False
        if name == "channel":
            return self._selected()
        if name == "channels":
            return sorted(self._hw().channels)
        if name == "channel_states":
            allp = self._vendor("inquire", self._hw().inquire_all)
            return {p: str(r.get("workstatus", "unknown")).lower() for p, r in allp.items()}
        if name in ("channel_state", "voltage", "current", "capacity", "cycle", "step"):
            rec = self._scaled(self._vendor("inquire", lambda: self._hw().inquire(self._selected())))
            return {"channel_state": rec["workstatus"], "voltage": rec["voltage_v"], "current": rec["current_a"],
                    "capacity": rec["capacity_ah"], "cycle": rec["cycle"], "step": rec["step"]}[name]
        if name == "last_result":
            return self.last_result
        raise InvalidValue(f"unknown signal {name}")

    def on_write(self, name: str, value):
        if name != "channel":
            raise InvalidValue(f"unknown setting {name}")
        if not PIPE_RE.match(str(value)):
            raise InvalidValue("channel must be a pipeline id devid-subdevid-chlid, e.g. '1-1-3'")
        if self.hw is not None and value not in self.hw.channels:
            raise InvalidValue(f"channel {value!r} is not one the BTS server lists", {"channels": sorted(self.hw.channels)})
        self.channel = str(value)
        return None

    def validate_params(self, action: str, params: dict) -> None:
        ch = params.get("channel")
        if not isinstance(ch, str) or not PIPE_RE.match(ch):
            raise InvalidValue(f"{action}.channel must be a pipeline id devid-subdevid-chlid, e.g. '1-1-3'")
        if self.hw is not None and ch not in self.hw.channels:
            raise InvalidValue(f"channel {ch!r} is not one the BTS server lists", {"channels": sorted(self.hw.channels)})
        if action != "start_protocol":
            return
        if not isinstance(params.get("barcode"), str) or not NAME_RE.match(params["barcode"]):
            raise InvalidValue("start_protocol.barcode must be 1-64 characters: letters, digits, space, '_', '.', '-'")
        steps = params.get("steps")
        if not isinstance(steps, list) or not steps:
            raise InvalidValue("start_protocol.steps must be a non-empty list")
        if len(steps) > int(self.cfg.get("max_steps", 64)):
            raise LimitViolation(f"{len(steps)} steps; the BTS step file is limited to {self.cfg.get('max_steps', 64)} here")
        vmax, imax = float(self.cfg.get("voltage_max_v", 5.0)), float(self.cfg.get("current_max_a", 1.0))
        for i, s in enumerate(steps):
            mode, cur, volt = s.get("mode"), s.get("current_a"), s.get("voltage_v")
            tl, cl = s.get("time_limit_s"), s.get("capacity_limit_ah")
            where = f"steps[{i}] ({mode})"
            if mode in ("cc_charge", "cc_discharge") and (cur is None or cur <= 0):
                raise InvalidValue(f"{where}: current_a must be a positive current (the sign comes from the mode)")
            if mode == "cv_charge" and (volt is None or cur is None):
                raise InvalidValue(f"{where}: cv_charge needs voltage_v (the hold) and current_a (the cut-off current)")
            if mode == "rest" and tl is None:
                raise InvalidValue(f"{where}: rest needs time_limit_s")
            if mode != "rest" and volt is None and tl is None and cl is None:
                raise InvalidValue(f"{where}: needs an end condition: voltage_v, time_limit_s or capacity_limit_ah")
            if volt is not None and volt > vmax:
                raise LimitViolation(f"{where}: voltage_v {volt} exceeds voltage_max_v {vmax} from config.json", {"max": vmax})
            if cur is not None and cur > imax:
                raise LimitViolation(f"{where}: current_a {cur} exceeds current_max_a {imax} from config.json", {"max": imax})
            if mode == "cc_discharge" and volt is not None and volt < float(self.cfg.get("voltage_min_v", 0.0)):
                raise LimitViolation(f"{where}: voltage_v below voltage_min_v from config.json")

    def on_invoke(self, job: Job):
        hw = self._hw()
        p = job.params
        ch = p["channel"]
        if job.action == "stop_channel":
            self._vendor("stop", lambda: hw.stop(ch))
            self.running.discard(ch)
            rec = self._scaled(self._vendor("inquire", lambda: hw.inquire(ch)))
            return {"channel": ch, "channel_state": rec["workstatus"]}
        if job.action != "start_protocol":
            raise InvalidValue(f"unhandled action {job.action}")
        before = self._scaled(self._vendor("inquire", lambda: hw.inquire(ch)))
        if before["workstatus"] not in IDLE_STATES and before["workstatus"] != "unknown":
            raise DeviceFault(f"channel {ch} is {before['workstatus']}; a protocol can only start from "
                              f"{', '.join(IDLE_STATES)}", {"transient": True, "recovery": "retry_after"})
        token = f"mhp_{job.id}"
        local_path, server_path = hw.write_step_file(token, p["steps"], int(p["cycles"]), p["barcode"])
        scale = self.time_scale()
        started = time.time()
        self._vendor("start", lambda: hw.start(ch, p["barcode"], server_path))
        self.running.add(ch)
        poll = float(self.cfg.get("poll_s", 10)) * scale
        limit = float(self.cfg.get("max_run_hours", 240)) * 3600 * scale
        cycles = int(p["cycles"])
        rec, seen_working = before, False
        try:
            time.sleep(min(0.5, 2 * scale))
            while True:
                try:
                    self.checkpoint(job, min(0.99, rec["cycle"] / cycles if cycles else 0.0), phase=rec["workstatus"],
                                    cycle=rec["cycle"], step=rec["step"])
                except JobCancelled:
                    self._vendor("stop", lambda: hw.stop(ch))
                    raise
                rec = self._scaled(self._vendor("inquire", lambda: hw.inquire(ch)))
                if rec["workstatus"] in RUNNING_STATES:
                    seen_working = True
                elif seen_working or time.time() - started > 30 * scale:
                    break
                if rec["workstatus"] == "protect":
                    break
                if time.time() - started > limit:
                    raise DeviceFault(f"channel {ch} still working after {self.cfg.get('max_run_hours', 240)} h (max_run_hours); "
                                      f"stop it with stop_channel if that is wrong")
                time.sleep(min(1.0, poll))
        finally:
            self.running.discard(ch)
        result = {"channel": ch, "barcode": p["barcode"], "step_file": local_path, "cycles_completed": int(rec["cycle"]),
                  "last_capacity_ah": None if rec["capacity_ah"] is None else round(rec["capacity_ah"], 6),
                  "final_voltage_v": None if rec["voltage_v"] is None else round(rec["voltage_v"], 4),
                  "final_state": rec["workstatus"], "duration_s": round((time.time() - started) / scale, 1)}
        self.last_result = result
        self.emit_signal("last_result", result)
        if rec["workstatus"] == "protect":
            raise DeviceFault(f"channel {ch} tripped its protection (over-voltage, over-current or temperature) after "
                              f"{rec['cycle']} cycle(s); the data so far is in the BTS backup folder",
                              {"transient": False, "recovery": "operator", "result": result})
        return result

    def on_estop(self) -> None:
        """Open every channel: stop on each one the server lists."""
        try:
            if self.hw is not None:
                self.hw.stop_all()
        except Exception:                                    # noqa: BLE001  must not raise
            pass
        self.running.clear()

    @classmethod
    def probe(cls, cfg: dict) -> str:
        hw = NewareBackend(cfg)
        hw.open()
        try:
            return f"BTS server at {cfg.get('host')}:{cfg.get('port', 502)} lists {len(hw.channels)} channel(s): {', '.join(sorted(hw.channels)[:8])}"
        finally:
            hw.close()

    @classmethod
    def discover(cls, cfg: dict, what: str) -> list:
        if what != "default_channel" or not cfg.get("host"):
            return []
        hw = NewareBackend(cfg)
        hw.open()
        try:
            return sorted(hw.channels)
        finally:
            hw.close()
