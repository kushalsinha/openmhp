"""Simulated twin: an XLP 6000 answering the DT protocol with a moving-plunger model.

The plunger moves at the top velocity (increments per second) toward its target; Q reports busy
meanwhile and the error nibble carries the last error (7 before initialisation). Simulated time runs
faster than the clock: OPENMHP_SIM_TIME_SCALE is the number of real seconds per simulated second
(default 0.01).
"""
import os
import re
import time

from openmhp.driver import LimitViolation
from openmhp.drivers.serial_ascii import SerialAsciiDriver

_BUSY = re.compile(r"^/0[@A-O]")                   # status byte 0x40-0x4F: busy


class _FakePort:
    is_open = True

    def __init__(self):
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        self.full = 6000
        self.pos, self.target, self.velocity, self.speed_code = 0, 0, 1400.0, 11
        self.valve, self.initialised, self.error = "?", False, 0
        self.t = time.time()
        self._reply = b""
        self.sent = []

    def _tick(self):
        now = time.time()
        dt = (now - self.t) / self.scale
        self.t = now
        step = self.velocity * dt
        if self.pos < self.target: self.pos = min(self.target, int(self.pos + step))
        elif self.pos > self.target: self.pos = max(self.target, int(self.pos - step))

    def _status(self):
        busy = self.pos != self.target
        return chr((0x40 if busy else 0x60) + self.error)

    def _answer(self, data=""):
        return f"/0{self._status()}{data}\x03\r\n".encode()

    def _move(self, target):
        if not self.initialised: self.error = 7
        elif target < 0 or target > self.full: self.error = 3
        elif self.pos != self.target: self.error = 11
        else: self.error = 0; self.target = target

    def write(self, b):
        frame = b.decode().strip()
        self.sent.append(frame)
        self._tick()
        if not frame.startswith("/1"):
            self._reply = b""
            return
        body = frame[2:]
        m = re.fullmatch(r"([A-Za-z&?])(\d*)R?", body)
        if not m:
            self.error = 2; self._reply = self._answer(); return
        cmd, n = m.group(1), m.group(2)
        if cmd == "Q": self._reply = self._answer()
        elif cmd == "?" and n == "": self._reply = self._answer(str(self.pos))
        elif cmd == "?" and n == "6": self._reply = self._answer(self.valve)
        elif cmd == "&": self._reply = self._answer("XLP6000 SIM 1.0")
        elif cmd == "Z": self.initialised = True; self.error = 0; self.target = 0; self.valve = "o"; self._reply = self._answer()
        elif cmd == "A": self._move(int(n)); self._reply = self._answer()
        elif cmd == "P": self._move(self.pos + int(n)); self._reply = self._answer()
        elif cmd == "D": self._move(self.pos - int(n)); self._reply = self._answer()
        elif cmd in ("I", "O"): self.valve = cmd.lower(); self.error = 0; self._reply = self._answer()
        elif cmd == "S": self.speed_code = int(n); self.error = 0; self._reply = self._answer()
        elif cmd == "V": self.velocity = float(n); self.error = 0; self._reply = self._answer()
        elif cmd == "T": self.target = self.pos; self._reply = self._answer()
        else: self.error = 2; self._reply = self._answer()

    def readline(self):
        return self._reply


class Sim(SerialAsciiDriver):
    link = _FakePort()

    # the same overrides as driver.py (the twin cannot import the package's driver module by name)
    def _with_steps(self, params: dict) -> dict:
        if "volume_ul" not in params:
            return params
        cfg = self.config()
        full = int(cfg.get("steps_full_stroke", 6000))
        steps = int(round(float(params["volume_ul"]) * full / float(cfg.get("syringe_ul", 1000))))
        if steps > full:
            raise LimitViolation(f"volume_ul={params['volume_ul']} is {steps} increments, more than the "
                                 f"{full}-increment stroke of the configured {cfg.get('syringe_ul', 1000)} uL syringe")
        return {**params, "steps": steps}

    def validate_params(self, action: str, params: dict) -> None:
        super().validate_params(action, self._with_steps(params))

    def on_invoke(self, job):
        job.params = self._with_steps(job.params)
        out = super().on_invoke(job)
        while _BUSY.match(self.query("/1Q")):
            self.checkpoint(job)
            time.sleep(0.02)
        return out
