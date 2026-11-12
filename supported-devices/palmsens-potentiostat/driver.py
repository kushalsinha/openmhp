"""MHP driver for PalmSens MethodSCRIPT potentiostats (EmStat Pico, EmStat4, Sensit) over a USB virtual COM port.

MethodSCRIPT is a text language: the host sends `e` followed by script lines and a blank line, the instrument
echoes, streams data packages (`P` lines) and ends with a blank line; `t` asks for the firmware string and
`Z` aborts a running script. The grammar used here is the one in PalmSens' MethodSCRIPT_Examples repository
(MIT) and the MethodSCRIPT manual; see references/methodscript.md. Every pyserial call lives in
MethodScriptBackend so the simulated twin can replace it with a fake port.
"""
from __future__ import annotations

import csv
import json
import math
import pathlib
import re
import time

from openmhp.driver import DeviceFault, Driver, InvalidValue, Job, JobCancelled, LimitViolation

HERE = pathlib.Path(__file__).parent
ERROR_LINE = re.compile(r".*!([0-9A-Fa-f]{4})(:.*)?$")
SI_FACTOR = {"a": 1e-18, "f": 1e-15, "p": 1e-12, "n": 1e-9, "u": 1e-6, "m": 1e-3, " ": 1.0, "k": 1e3,
             "M": 1e6, "G": 1e9, "T": 1e12, "P": 1e15, "E": 1e18, "i": 1.0}
# MethodSCRIPT variable types used here (the examples' mscript.py table): ab WE vs RE potential, ba WE current,
# da applied potential, eb time
VAR_UNITS = {"ab": "V", "ba": "A", "da": "V", "eb": "s"}
DEVICE_TYPES = [("senswb", "Sensit Wearable"), ("espico", "EmStat Pico"), ("es4_hr", "EmStat4 HR"),
                ("es4_lr", "EmStat4 LR"), ("mes4hr", "MultiEmStat4 HR"), ("mes4lr", "MultiEmStat4 LR"),
                ("espbl", "EmStat Pico bootloader"), ("nexus1", "Nexus")]
PGSTAT_MODE = {"ca": 2, "cv": 3, "lsv": 3, "ocp": 3}       # as in PalmSens' loop examples 008, 004, 001, 011


def load_config() -> dict:
    p = HERE / "config.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


# ---- MethodSCRIPT text --------------------------------------------------------------------- #
def si(value: float, unit_prefixes=("", "m", "u", "n", "p")) -> str:
    """A MethodSCRIPT number: an integer with an SI prefix (0.0125 -> 12500u), never a decimal point."""
    if value == 0:
        return "0"
    for prefix, factor in zip(unit_prefixes, (1.0, 1e-3, 1e-6, 1e-9, 1e-12)):
        scaled = value / factor
        if abs(scaled - round(scaled)) < 1e-6 and abs(round(scaled)) >= 1:
            return f"{int(round(scaled))}{prefix}"
    return f"{int(round(value / 1e-12))}p"


def decode_value(token: str) -> tuple[str, float]:
    """One variable of a data package: 2-char type, 7 hex digits offset by 2^27, 1 SI prefix char."""
    if len(token) < 10:
        raise InvalidValue(f"short MethodSCRIPT variable {token!r}")
    code, body, prefix = token[0:2], token[2:9], token[9]
    if token[2:10] == "     nan":
        return code, math.nan
    if prefix not in SI_FACTOR:
        raise InvalidValue(f"unknown SI prefix {prefix!r} in {token!r}")
    return code, (int(body, 16) - 2 ** 27) * SI_FACTOR[prefix]


def parse_package(line: str) -> dict:
    """'Pxx...;yy...' -> {var type: value}; metadata after ',' (status, current range) is dropped."""
    out: dict[str, float] = {}
    for var in line[1:].rstrip("\r\n").split(";"):
        var = var.strip()
        if not var:
            continue
        code, value = decode_value(var.split(",")[0])
        out[code] = value
    return out


def build_script(technique: str, p: dict, current_max_a: float) -> list[str]:
    """Script lines for one technique, after the examples in PalmSens' MethodSCRIPT_Examples (loop examples)."""
    lines = ["e", "var p", "var c", "var t", "set_pgstat_chan 0", f"set_pgstat_mode {PGSTAT_MODE[technique]}",
             "set_max_bandwidth 40"]
    if technique == "ocp":
        lines += ["set_range ab 4", "set_autoranging ab 4 4",                   # unverified: copied from example 011
                  "set_range ba 2m", "set_autoranging ba 2m 2m", "cell_off", "timer_start",
                  f"meas_loop_ocp p {si(p['interval_s'])} {si(p['duration_s'])}",
                  "    timer_get t", "    pck_start", "    pck_add t", "    pck_add p", "    pck_end", "endloop"]
    else:
        if technique == "ca":
            lo = hi = p["e_V"]
        elif technique == "cv":
            lo, hi = min(p["e_begin_V"], p["e_vertex1_V"], p["e_vertex2_V"]), max(p["e_begin_V"], p["e_vertex1_V"], p["e_vertex2_V"])
        else:
            lo, hi = min(p["e_begin_V"], p["e_end_V"]), max(p["e_begin_V"], p["e_end_V"])
        lines += [f"set_range_minmax da {si(lo)} {si(hi)}", f"set_range ba {si(current_max_a)}",
                  f"set_autoranging ba 1n {si(current_max_a)}"]
        start = p["e_V"] if technique == "ca" else p["e_begin_V"]
        lines += [f"set_e {si(start)}", "cell_on", "timer_start"]
        if technique == "ca":
            lines.append(f"meas_loop_ca p c {si(p['e_V'])} {si(p['interval_s'])} {si(p['duration_s'])}")
        elif technique == "cv":
            rate = p["scan_rate_mV_s"] / 1000
            lines.append(f"meas_loop_cv p c {si(p['e_begin_V'])} {si(p['e_vertex1_V'])} {si(p['e_vertex2_V'])} "
                         f"{si(p['e_step_V'])} {si(rate)} nscans({int(p['n_scans'])})")
        else:
            rate = p["scan_rate_mV_s"] / 1000
            lines.append(f"meas_loop_lsv p c {si(p['e_begin_V'])} {si(p['e_end_V'])} {si(p['e_step_V'])} {si(rate)}")
        lines += ["    timer_get t", "    pck_start", "    pck_add t", "    pck_add p", "    pck_add c", "    pck_end", "endloop"]
    lines += ["on_finished:", "    cell_off"]
    return lines


def expected_seconds(technique: str, p: dict) -> float:
    if technique in ("ca", "ocp"):
        return float(p["duration_s"])
    rate = p["scan_rate_mV_s"] / 1000
    if technique == "lsv":
        return abs(p["e_end_V"] - p["e_begin_V"]) / rate
    one = (abs(p["e_vertex1_V"] - p["e_begin_V"]) + abs(p["e_vertex2_V"] - p["e_vertex1_V"])
           + abs(p["e_begin_V"] - p["e_vertex2_V"])) / rate
    return one * int(p["n_scans"])


class MethodScriptBackend:
    """The serial link: pyserial, line I/O, the three commands this package uses (t, e..., Z)."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.port = None

    def open(self) -> None:
        if not self.cfg.get("port"):
            raise DeviceFault("config.json is missing or has no port (copy config.example.json and fill it in)")
        import serial
        self.port = serial.Serial(self.cfg["port"], int(self.cfg.get("baud", 230400)), timeout=float(self.cfg.get("timeout_s", 2)))

    def close(self) -> None:
        if self.port is not None:
            self.port.close()

    def write(self, text: str) -> None:
        self.port.write(text.encode("ascii"))

    def readline(self) -> str:
        """One line, '' on timeout."""
        return self.port.readline().decode("ascii", errors="replace")

    def firmware(self) -> str:
        self.write("t\n")
        first, second = self.readline(), self.readline()
        if not first.startswith("t") or not second.rstrip("\r\n").endswith("*"):
            raise DeviceFault(f"unexpected answer to 't': {first!r} {second!r}")
        return (first.rstrip("\r\n")[1:] + " " + second.rstrip("\r\n")[:-1]).strip()

    def send_script(self, lines: list[str]) -> None:
        self.write("".join(line + "\n" for line in lines) + "\n")

    def abort(self) -> None:
        """'\\n' flushes the command buffer, 'Z' aborts; the reply starts with 'Z' ('Z!0006' = nothing was running)."""
        self.write("\nZ\n")


class PalmSensPotentiostat(Driver):
    TECHNIQUES = ("ca", "cv", "lsv", "ocp")

    def setup(self) -> None:
        self.cfg = load_config()
        self.hw = None
        self.fw = ""
        self.values = {"current_range_max_A": 0.002}
        self.cell_on = False
        self.running = False
        self.last_result = None

    def make_backend(self):
        return MethodScriptBackend(self.cfg)

    def time_scale(self) -> float:
        return 1.0

    def _hw(self):
        if self.hw is None:
            hw = self.make_backend()
            try:
                hw.open()
                self.fw = hw.firmware()
            except DeviceFault:
                raise
            except Exception as e:                       # noqa: BLE001  pyserial / decode errors
                raise DeviceFault(f"cannot open the potentiostat on {self.cfg.get('port')}: {type(e).__name__}: {e}") from None
            self.hw = hw
        return self.hw

    def device_type(self) -> str:
        fw = self.fw.lower()
        return next((name for prefix, name in DEVICE_TYPES if fw.startswith(prefix)), "unknown device")

    def on_read(self, name: str):
        if name == "connected":
            try:
                self._hw()
                return True
            except DeviceFault:
                return False
        if name == "firmware":
            self._hw()
            return self.fw
        if name == "device_type":
            self._hw()
            return self.device_type()
        if name == "running":
            return self.running
        if name == "cell_on":
            return self.cell_on
        if name == "last_result":
            return self.last_result
        if name in self.values:
            return self.values[name]
        raise InvalidValue(f"unknown signal {name}")

    def on_write(self, name: str, value) -> None:
        self.values[name] = value                        # used by the next script; nothing is sent now

    def validate_params(self, action: str, params: dict) -> None:
        if action == "cv":
            lo, hi = sorted((params["e_vertex1_V"], params["e_vertex2_V"]))
            if not lo <= params["e_begin_V"] <= hi:
                raise InvalidValue("cv: e_begin_V must lie between the two vertices")
            if params["e_step_V"] > abs(params["e_vertex1_V"] - params["e_vertex2_V"]):
                raise InvalidValue("cv: e_step_V is larger than the sweep")
        if action == "lsv" and params["e_begin_V"] == params["e_end_V"]:
            raise InvalidValue("lsv: e_begin_V and e_end_V are equal")
        if action in ("ca", "ocp") and params["interval_s"] > params["duration_s"]:
            raise InvalidValue(f"{action}: interval_s is longer than duration_s")
        if action in ("cv", "lsv", "ca", "ocp") and expected_seconds(action, params) > float(self.cfg.get("max_run_s", 7200)):
            raise LimitViolation(f"{action}: expected run of {expected_seconds(action, params):.0f} s exceeds max_run_s",
                                 {"max": self.cfg.get("max_run_s", 7200)})

    # ---- the run ---------------------------------------------------------------------------- #
    def _collect(self, job: Job, hw, expect_s: float) -> tuple[list[dict], bool]:
        """Read lines until the blank end line. Returns (points, aborted)."""
        points, aborted = [], False
        scale = self.time_scale()
        deadline = time.monotonic() + (expect_s * 1.5 + 30) * scale
        while True:
            if not aborted:
                t_last = (points[-1].get("t_s") or 0.0) if points else 0.0
                try:
                    self.checkpoint(job, min(0.98, t_last / max(expect_s, 1e-9)), phase="measuring")
                except JobCancelled:
                    hw.abort()                           # keep reading: the instrument answers 'Z' then the end line
                    aborted = True
            line = hw.readline()
            if line == "":
                if time.monotonic() > deadline:
                    hw.abort()
                    raise DeviceFault(f"no end of script after {expect_s * 1.5 + 30:.0f} s; script aborted")
                continue
            if line in ("\n", "\r\n"):
                break
            if line.startswith("P"):
                v = parse_package(line)
                points.append({"t_s": v.get("eb"), "e_V": v.get("ab", v.get("da")), "i_A": v.get("ba")})
                continue
            m = ERROR_LINE.match(line.rstrip("\r\n"))
            if m and not line.startswith("Z"):
                raise DeviceFault(f"MethodSCRIPT error !{m.group(1)}{m.group(2) or ''}; the cell is off (on_finished)")
            # 'e' echo, 'M'/'*'/'+'/'Z' loop and abort markers: ignored
        if aborted:
            raise JobCancelled(job.id)
        return points, aborted

    def _csv(self, job: Job, technique: str, points: list[dict]) -> str:
        root = pathlib.Path(self.cfg.get("data_dir") or HERE / "data")
        root.mkdir(parents=True, exist_ok=True)
        file = root / f"{time.strftime('%Y%m%d-%H%M%S')}_{technique}_{job.id}.csv"
        with file.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(("t_s", "e_V", "i_A"))
            for pt in points:
                w.writerow((pt["t_s"], pt["e_V"], pt["i_A"]))
        return str(file)

    def on_invoke(self, job: Job):
        technique = job.action
        if technique not in self.TECHNIQUES:
            raise InvalidValue(f"unhandled action {technique}")
        hw = self._hw()
        p = job.params
        script = build_script(technique, p, float(self.values["current_range_max_A"]))
        expect = expected_seconds(technique, p)
        self.running, self.cell_on = True, technique != "ocp"
        try:
            try:
                hw.send_script(script)
            except Exception as e:                       # noqa: BLE001
                raise DeviceFault(f"could not send the script: {type(e).__name__}: {e}") from None
            try:
                points, _ = self._collect(job, hw, expect)
            except JobCancelled:
                self._drain(hw)
                raise
        finally:
            self.running, self.cell_on = False, False
        last = points[-1] if points else {}
        result = {"technique": technique, "points": len(points), "csv": self._csv(job, technique, points),
                  "duration_s": round(float(last.get("t_s") or 0.0), 4),
                  "e_final_V": last.get("e_V"), "i_final_A": last.get("i_A"),
                  "script": script, "firmware": self.fw}
        self.last_result = {k: v for k, v in result.items() if k != "script"}
        self.emit_signal("last_result", self.last_result)
        return result

    def _drain(self, hw) -> None:
        """After an abort: read until the end line so the next script starts on a clean link."""
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            line = hw.readline()
            if line in ("", "\n", "\r\n"):
                break

    def on_estop(self) -> None:
        try:
            if self.hw is not None:
                self.hw.abort()
                self._drain(self.hw)
                self.hw.send_script(["e", "set_pgstat_chan 0", "cell_off"])
                self._drain(self.hw)
        except Exception:                                # noqa: BLE001  must not raise
            pass
        self.running, self.cell_on = False, False

    # ---- setup-time check (`mhp node setup`) ------------------------------------------------ #
    @classmethod
    def probe(cls, cfg: dict) -> str:
        hw = MethodScriptBackend(cfg)
        try:
            hw.open()
            fw = hw.firmware()
        except ImportError:
            raise DeviceFault("pyserial is not installed (pip install pyserial)") from None
        except DeviceFault:
            raise
        except Exception as e:                           # noqa: BLE001
            raise DeviceFault(f"no MethodSCRIPT device on {cfg.get('port')}: {type(e).__name__}: {e}") from None
        finally:
            hw.close()
        return f"{cfg.get('port')} answers 't': {fw}"
