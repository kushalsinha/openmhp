"""Simulated twin of a MethodSCRIPT potentiostat: a fake serial port that understands `t`, `Z` and the script
subset this package sends, and answers data packages for a cell with double-layer capacitance and one
reversible redox couple at +0.25 V. Timing scaled by OPENMHP_SIM_TIME_SCALE. No pyserial."""
from __future__ import annotations

import importlib.util
import math
import os
import pathlib
import random
import re
import sys
import time

_spec = importlib.util.spec_from_file_location(__name__ + "_real", pathlib.Path(__file__).with_name("driver.py"))
real = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = real
_spec.loader.exec_module(real)

E0, R_SOL, C_DL, I_PEAK = 0.25, 2000.0, 2e-5, 2e-5          # V, ohm, F, A at 100 mV/s
PREFIX = {"m": 1e-3, "u": 1e-6, "n": 1e-9, "p": 1e-12}


def parse_si(tok: str) -> float:
    m = re.fullmatch(r"(-?\d+)([munp]?)", tok)
    if not m:
        raise real.InvalidValue(f"bad MethodSCRIPT number {tok!r}")
    return int(m.group(1)) * (PREFIX[m.group(2)] if m.group(2) else 1.0)


def encode(code: str, value: float, prefix: str) -> str:
    n = int(round(value / PREFIX[prefix]))
    n = max(-2 ** 27 + 1, min(2 ** 27 - 1, n))
    return f"{code}{n + 2 ** 27:07X}{prefix},10"


class FakePort:
    """What pyserial's Serial would be: write(bytes), readline() -> bytes, close()."""

    def __init__(self, scale: float):
        self.scale, self.log, self.queue, self.buf, self.script = scale, [], [], "", None
        self.running, self.t0 = False, 0.0

    def close(self):
        self.log.append("<close>")

    def write(self, data: bytes) -> None:
        self.buf += data.decode("ascii")
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            self._command(line.rstrip("\r"))

    def _command(self, line: str) -> None:
        self.log.append(line)
        if self.script is not None:                       # collecting a script
            if line == "":
                self._run(self.script)
                self.script = None
            else:
                self.script.append(line)
            return
        if line == "":
            return
        if line == "e":
            self.script = []
            self.queue.append((0.0, "e\n"))
        elif line == "t":
            self.queue += [(0.0, "tespico1.3.0\n"), (0.0, "*\n")]
        elif line == "Z":
            if self.running:
                self.queue = [(0.0, "Z\n"), (0.0, "\n")]
                self.running = False
            else:
                self.queue.append((0.0, "Z!0006\n"))
        else:
            self.queue.append((0.0, "!0001\n"))            # unverified: the manual's code for an unknown command

    def _run(self, lines: list[str]) -> None:
        loop = next((ln.strip() for ln in lines if ln.strip().startswith("meas_loop_")), None)
        if loop is None:                                    # e.g. the e-stop's cell_off script
            self.queue.append((0.0, "\n"))
            return
        parts = loop.split()
        kind = parts[0][len("meas_loop_"):]
        now = time.monotonic()
        self.running, self.t0 = True, now
        self.queue.append((0.0, "M0000\n"))
        pts: list[tuple[float, float | None, float | None]] = []        # (t, E, i)
        if kind == "ca":
            e, dt, dur = parse_si(parts[3]), parse_si(parts[4]), parse_si(parts[5])
            n = int(dur / dt)
            for k in range(1, n + 1):
                t = k * dt
                i = e / R_SOL * (1 + 3 * math.exp(-t / 0.3)) + random.gauss(0, 2e-8)
                pts.append((t, e, i))
        elif kind == "ocp":
            dt, dur = parse_si(parts[2]), parse_si(parts[3])
            for k in range(1, int(dur / dt) + 1):
                t = k * dt
                pts.append((t, 0.35 + 0.05 * math.exp(-t / 5) + random.gauss(0, 2e-4), None))
        else:
            if kind == "cv":
                e_begin, v1, v2, step, rate = (parse_si(x) for x in parts[3:8])
                nscans = int(re.search(r"nscans\((\d+)\)", loop).group(1)) if "nscans(" in loop else 1
                legs = [(e_begin, v1), (v1, v2), (v2, e_begin)] * nscans
            else:
                e_begin, e_end, step, rate = (parse_si(x) for x in parts[3:7])
                legs = [(e_begin, e_end)]
            t = 0.0
            for a, b in legs:
                sign = 1 if b >= a else -1
                for k in range(int(round(abs(b - a) / step))):
                    e = a + sign * (k + 1) * step
                    t += step / rate
                    i = C_DL * rate * sign + sign * I_PEAK * math.sqrt(rate / 0.1) * math.exp(-((e - E0 - sign * 0.03) / 0.04) ** 2)
                    pts.append((t, e, i + random.gauss(0, 5e-8)))
        for t, e, i in pts:
            fields = [encode("eb", t, "m")]
            if e is not None:
                fields.append(encode("ab" if kind == "ocp" else "da", e, "u"))
            if i is not None:
                fields.append(encode("ba", i, "n"))
            self.queue.append((t, "P" + ";".join(fields) + "\n"))
        end = pts[-1][0] if pts else 0.0
        self.queue += [(end, "*\n"), (end, "\n")]

    def readline(self) -> bytes:
        if not self.queue:
            time.sleep(0.002)
            return b""
        due, line = self.queue[0]
        wait = self.t0 + due * self.scale - time.monotonic()
        if wait > 0:
            time.sleep(min(wait, 0.05))
            if wait > 0.05:
                return b""
        self.queue.pop(0)
        if line == "\n":
            self.running = False
        return line.encode("ascii")


class SimBackend(real.MethodScriptBackend):
    def __init__(self, cfg, scale):
        super().__init__(cfg)
        self.port = FakePort(scale)

    def open(self) -> None:
        self.port.log.append("<open>")


class SimPalmSensPotentiostat(real.PalmSensPotentiostat):
    def setup(self) -> None:
        super().setup()
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        home = pathlib.Path(os.environ.get("OPENMHP_HOME", pathlib.Path.home() / ".openmhp"))
        self.cfg = {"port": "SIM", "baud": 230400, "max_run_s": 7200,
                    "data_dir": str(home / "sim-data" / "palmsens-potentiostat")}

    def time_scale(self) -> float:
        return self.scale

    def make_backend(self):
        hw = SimBackend(self.cfg, self.scale)
        self.link = hw.port
        return hw
