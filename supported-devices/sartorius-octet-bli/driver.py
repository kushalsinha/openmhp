"""MHP driver for a Sartorius (ForteBio) Octet RH16 / RH96 (and, unverified, R8) bio-layer interferometry
system through the Octet automation interface: a line-oriented ASCII command protocol served by Octet BLI
Discovery (formerly Data Acquisition) over a TCP/IP socket or RS-232, defined in ForteBio's
AutomationAPI.h (API 1.1): Version, Status, GetMethodInfo, Run, GetRunInfo, Stop, Present, Close, Resume,
SetValue, Reset. Documented in the Octet System Data Acquisition User Guide, Appendix A, and confirmed for
Octet BLI Discovery 10 by Sartorius's datasheet. Every socket exchange sits in OctetBackend; the twin
replaces the socket with a scripted link.

The vendor also names a .NET/COM "Octet Automation" library for scheduler vendors; no public reference
for it was found, so this package uses the documented socket protocol (any OS; the Octet PC is Windows).
"""
from __future__ import annotations

import json
import pathlib
import re
import socket
import time

from openmhp.driver import DeviceFault, Driver, InvalidValue, Job, JobCancelled

HERE = pathlib.Path(__file__).parent
RUNNING = re.compile(r"^Running\s*\((\d+)%\)", re.I)


def load_config() -> dict:
    p = HERE / "config.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def plain_name(s, what: str) -> str:
    if not isinstance(s, str) or not s.strip() or re.search(r'[\\/"\x00-\x1f]', s) or ".." in s:
        raise InvalidValue(f"{what} must be a plain name without folders or quotes, got {s!r}")
    return s.strip()


class OctetBackend:
    """One command per line, '\\r\\n' terminated; the reply's first token is the status word."""

    def __init__(self, cfg: dict):
        self.cfg, self.sock, self.buf = cfg, None, b""

    def open(self) -> None:
        if not self.cfg.get("host"):
            raise DeviceFault("config.json is missing (copy config.example.json and fill it in)")
        self.sock = socket.create_connection((self.cfg["host"], int(self.cfg.get("port", 7000))), timeout=10)
        v = self.command("Version")
        if v.lower().startswith("error"):
            raise DeviceFault(f"Octet automation interface answered {v!r} to Version")

    def command(self, text: str, timeout: float = 30) -> str:
        self.sock.settimeout(timeout)
        self.sock.sendall((text + "\r\n").encode("ascii"))
        while b"\n" not in self.buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise DeviceFault("the Octet automation interface closed the connection", {"transient": True})
            self.buf += chunk
        line, _, self.buf = self.buf.partition(b"\n")
        return line.decode("ascii", errors="replace").strip()

    def status(self) -> str:
        return self.command("Status")

    def method_info(self, method: str) -> dict:
        r = self.command(f'GetMethodInfo -m"{self._method_path(method)}"')
        if r.lower().startswith("error"):
            raise InvalidValue(f"Octet rejected method {method!r}: {r}")
        return {"trays": int(m.group(1)) if (m := re.search(r"-t(\d+)", r)) else 0, "raw": r}

    def run(self, method: str, sample_plate_id: str, sensor_tray_id: str) -> str:
        r = self.command(f'Run -m"{self._method_path(method)}" -1"{sample_plate_id}" -l"{sensor_tray_id}" -s', timeout=60)
        if r.lower().startswith("error"):
            raise DeviceFault(f"Octet refused to start {method}: {r}")
        return r

    def run_info(self) -> dict:
        r = self.command("GetRunInfo")
        name = m.group(1) if (m := re.search(r'-n"([^"]*)"', r)) else None
        path = m.group(1) if (m := re.search(r'-p"([^"]*)"', r)) else None
        return {"experiment": name, "path": path, "raw": r}

    def stop(self) -> None:
        self.command("Stop")

    def present(self) -> None:
        self.command("Present")

    def close(self) -> None:
        self.command("Close")

    def set_temperature(self, c: float) -> None:
        r = self.command(f"SetValue -t{int(round(c))}")
        if r.lower().startswith("error"):
            raise DeviceFault(f"SetValue -t{int(round(c))} refused: {r}")

    def _method_path(self, method: str) -> str:
        return str(pathlib.PureWindowsPath(self.cfg.get("method_dir", "")) / method)


class OctetBLI(Driver):
    def setup(self) -> None:
        self.cfg = load_config()
        self.hw = None
        self.running = False
        self.presented = False
        self.setpoint = None
        self.last_result = None

    def make_backend(self):
        return OctetBackend(self.cfg)

    def time_scale(self) -> float:
        return 1.0

    def _hw(self):
        if self.hw is None:
            hw = self.make_backend()
            try:
                hw.open()
            except DeviceFault:
                raise
            except Exception as e:                               # noqa: BLE001  vendor boundary
                raise DeviceFault(f"cannot reach the Octet automation interface at {self.cfg.get('host')}:{self.cfg.get('port', 7000)}: "
                                  f"{type(e).__name__}: {e}", {"transient": True}) from None
            self.hw = hw
        return self.hw

    def _vendor(self, what, fn):
        try:
            return fn()
        except (DeviceFault, InvalidValue):
            raise
        except Exception as e:                                   # noqa: BLE001  vendor boundary
            raise DeviceFault(f"Octet {what} failed: {type(e).__name__}: {e}", {"transient": True}) from None

    def _status(self) -> str:
        return self._vendor("Status", self._hw().status)

    def _busy_word(self, st: str) -> bool:
        return bool(RUNNING.match(st)) or st.lower().startswith(("busy", "waiting", "loadsensors"))

    def on_read(self, name: str):
        if name == "connected":
            try:
                self._hw()
                return True
            except DeviceFault:
                return False
        if name == "status":
            return self._status()
        if name == "temperature":
            return None                                          # the automation API has no temperature query
        if name == "temperature_setpoint":
            return self.setpoint
        if name == "plate_in":
            return not self.presented
        if name == "robot_access_ready":
            return self.presented and not self.running and not self._busy_word(self._status())
        if name == "last_result":
            return self.last_result
        raise InvalidValue(f"unknown signal {name}")

    def on_write(self, name: str, value):
        if name != "temperature_setpoint":
            raise InvalidValue(f"unknown setting {name}")
        self._vendor("SetValue", lambda: self._hw().set_temperature(value))
        self.setpoint = value
        return None

    def validate_params(self, action: str, params: dict) -> None:
        if action != "run_experiment":
            return
        plain_name(params.get("method"), "run_experiment.method")
        plain_name(params.get("sample_plate_id"), "run_experiment.sample_plate_id")
        plain_name(params.get("sensor_tray_id"), "run_experiment.sensor_tray_id")
        if not params["method"].lower().endswith(".fmf"):
            raise InvalidValue("run_experiment.method must be an Octet method file name ending in .fmf")
        allowed = self.cfg.get("allowed_methods") or []
        if allowed and params["method"] not in allowed:
            raise InvalidValue(f"method {params['method']!r} is not in allowed_methods")

    def on_invoke(self, job: Job):
        hw = self._hw()
        if job.action == "plate_out":
            if self._busy_word(self._status()):
                raise DeviceFault("the Octet is busy (started outside this package); wait for Status OK")
            self._vendor("Present", hw.present)
            self._settle(job, hw)
            self.presented = True
            return {"plate_in": False}
        if job.action == "plate_in":
            self._vendor("Close", hw.close)
            self._settle(job, hw)
            self.presented = False
            return {"plate_in": True}
        if job.action != "run_experiment":
            raise InvalidValue(f"unhandled action {job.action}")
        p = job.params
        info = self._vendor("GetMethodInfo", lambda: hw.method_info(p["method"]))
        scale = self.time_scale()
        started = time.time()
        self._vendor("Run", lambda: hw.run(p["method"], p["sample_plate_id"], p["sensor_tray_id"]))
        self.running = True
        limit = float(self.cfg.get("max_run_hours", 12)) * 3600 * scale
        st, seen = "", False
        try:
            time.sleep(min(1.0, 2 * scale))
            while True:
                try:
                    self.checkpoint(job, phase=st or "starting")
                except JobCancelled:
                    self._vendor("Stop", hw.stop)
                    raise
                st = self._status()
                if st.lower().startswith("error"):
                    raise DeviceFault(f"Octet reports {st} during {p['method']}")
                if st.lower().startswith("loadsensors"):
                    raise DeviceFault("the method needs another sensor tray (LoadSensors); multi-tray runs need a person or a robot sequence")
                if m := RUNNING.match(st):
                    seen = True
                    self.progress(job, int(m.group(1)) / 100)
                elif self._busy_word(st):
                    seen = True
                elif seen or time.time() - started > 60 * scale:
                    if st.lower().startswith("stopped"):
                        raise DeviceFault(f"the run stopped before completing (Status {st})")
                    break
                if time.time() - started > limit:
                    raise DeviceFault(f"run still going after {limit / scale / 3600:.0f} h (max_run_hours)")
                time.sleep(min(1.0, 5 * scale))
            info_run = self._vendor("GetRunInfo", hw.run_info)
        finally:
            self.running = False
        result = {"method": p["method"], "file": info_run.get("path") or "", "sensors": int(info.get("trays", 0)),
                  "duration_s": round((time.time() - started) / scale, 1),
                  "summary": {"experiment": info_run.get("experiment"), "sample_plate_id": p["sample_plate_id"],
                              "sensor_tray_id": p["sensor_tray_id"], "final_status": st}}
        self.last_result = result
        self.emit_signal("last_result", result)
        return result

    def _settle(self, job: Job, hw) -> None:
        """Present and Close are asynchronous: poll Status until it is no longer Busy."""
        deadline = time.time() + 120 * self.time_scale()
        while self._busy_word(self._status()):
            self.checkpoint(job)
            if time.time() > deadline:
                raise DeviceFault("the stage did not finish moving within 2 minutes")
            time.sleep(min(0.5, 2 * self.time_scale()))

    def on_estop(self) -> None:
        try:
            if self.hw is not None:
                self.hw.stop()
        except Exception:                                        # noqa: BLE001  must not raise
            pass
        self.running = False

    @classmethod
    def probe(cls, cfg: dict) -> str:
        hw = OctetBackend(cfg)
        hw.open()
        return f"Octet automation interface at {cfg.get('host')}:{cfg.get('port', 7000)}: Version {hw.command('Version')}, Status {hw.status()}"
