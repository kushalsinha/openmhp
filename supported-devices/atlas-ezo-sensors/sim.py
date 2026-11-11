"""Simulated twin: one EZO-pH circuit answering the EZO UART grammar.

The reading drifts slowly around 7.0 (set `true_ph` on the fake port to move it); calibration points
accumulate in `cal_points`; `*OK` response codes and continuous mode start on, as on a new circuit, so
the first thing a session does is configure_for_polling. Replies are queued line by line as the real
circuit sends them. Simulated time runs faster than the clock: OPENMHP_SIM_TIME_SCALE is the number of
real seconds per simulated second (default 0.01).
"""
import collections
import math
import os
import time

from openmhp.drivers.serial_ascii import SerialAsciiDriver


class _FakePort:
    is_open = True

    def __init__(self):
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        self.true_ph, self.temp_comp, self.cal_points, self.led = 7.0, 25.0, 0, True
        self.ok_codes, self.continuous = True, False                  # a fresh circuit answers *OK after everything
        self.t0 = time.time()
        self.lines = collections.deque()
        self.sent = []

    def _reading(self):
        sim_t = (time.time() - self.t0) / self.scale
        error = 0.0 if self.cal_points else 0.4                        # an uncalibrated circuit reads off
        return self.true_ph + error + 0.01 * math.sin(sim_t / 30.0)

    def _ok(self):
        if self.ok_codes:
            self.lines.append(b"*OK\r")

    def write(self, b):
        cmd = b.decode().strip()
        self.sent.append(cmd)
        low = cmd.lower()
        if low == "r": self.lines.append(f"{self._reading():.3f}\r".encode()); self._ok()
        elif low == "cal,?": self.lines.append(f"?Cal,{self.cal_points}\r".encode()); self._ok()
        elif low == "cal,clear": self.cal_points = 0; self._ok()
        elif low.startswith("cal,mid,"): self.cal_points = 1; self._ok()
        elif low.startswith("cal,low,"): self.cal_points = max(self.cal_points, 2); self._ok()
        elif low.startswith("cal,high,"): self.cal_points = 3; self._ok()
        elif low == "t,?": self.lines.append(f"?T,{self.temp_comp:.1f}\r".encode()); self._ok()
        elif low.startswith("t,"): self.temp_comp = float(cmd[2:]); self._ok()
        elif low == "i": self.lines.append(b"?i,pH,1.98\r"); self._ok()
        elif low == "status": self.lines.append(b"?Status,P,5.038\r"); self._ok()
        elif low in ("l,1", "l,0"): self.led = low.endswith("1"); self._ok()
        elif low == "l,?": self.lines.append(f"?L,{int(self.led)}\r".encode()); self._ok()
        elif low.startswith("c,"): self.continuous = not low.endswith(",0"); self._ok()
        elif low == "*ok,0": self.ok_codes = False
        elif low == "*ok,1": self.ok_codes = True; self._ok()
        else: self.lines.append(b"*ER\r")

    def readline(self):
        return self.lines.popleft() if self.lines else b""


class Sim(SerialAsciiDriver):
    link = _FakePort()
