"""Simulated twin: an NE-1000 answering the Basic-mode pump network protocol with a volume model.

While running, the dispensed volume advances at the set rate until the target volume is reached and
the status returns to S. Simulated time runs faster than the clock: OPENMHP_SIM_TIME_SCALE is the
number of real seconds per simulated second (default 0.01).
"""
import os
import re
import time

from openmhp.driver import InvalidValue
from openmhp.drivers.serial_ascii import SerialAsciiDriver

_STATUS = re.compile(r"\x02?\d\d([A-Z?])")


class _FakePort:
    is_open = True

    def __init__(self):
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        self.address = "00"
        self.dia, self.rate, self.units, self.vol, self.direction = 14.5, 1.0, "UL", 0.0, "INF"
        self.rate_units = "MM"
        self.infused, self.withdrawn, self.moved = 0.0, 0.0, 0.0
        self.running, self.alarm = False, None
        self.t = time.time()
        self._reply = b""
        self.sent = []

    def _tick(self):
        now = time.time()
        dt = (now - self.t) / self.scale
        self.t = now
        if self.running:
            ml_per_s = {"MM": self.rate / 60.0, "UM": self.rate / 60000.0, "MH": self.rate / 3600.0, "UH": self.rate / 3.6e6}[self.rate_units]
            step = min(ml_per_s * dt, self.vol - self.moved)
            self.moved += step
            if self.direction == "INF": self.infused += step
            else: self.withdrawn += step
            if self.moved >= self.vol - 1e-9:
                self.running = False

    def _status(self):
        if self.alarm: return f"A?{self.alarm}"
        if self.running: return "I" if self.direction == "INF" else "W"
        return "S"

    def _packet(self, data=""):
        return f"\x02{self.address}{self._status()}{data}\x03".encode()

    def write(self, b):
        cmd = b.decode().strip()
        self.sent.append(cmd)
        self._tick()
        addr, body = cmd[:2], cmd[2:].strip().upper()
        if addr != self.address:
            self._reply = b""                                        # another pump's address: silence
            return
        if self.alarm and body:
            self.alarm = None                                        # any valid command acknowledges the alarm
        parts = body.split()
        if not parts: self._reply = self._packet()
        elif parts[0] == "DIA":
            if len(parts) == 1: self._reply = self._packet(f"{self.dia:.2f}")
            elif self.running: self._reply = self._packet("?NA")
            else: self.dia = float(parts[1]); self.units = "UL" if self.dia <= 14.0 else "ML"; self._reply = self._packet()
        elif parts[0] == "RAT":
            if len(parts) == 1: self._reply = self._packet(f"{self.rate:.3f}{self.rate_units}")
            elif float(parts[1]) > 40.0: self._reply = self._packet("?OOR")
            else:
                self.rate = float(parts[1])
                if len(parts) > 2: self.rate_units = parts[2]
                self._reply = self._packet()
        elif parts[0] == "VOL":
            if len(parts) == 1: self._reply = self._packet(f"{self.vol:.3f}{self.units}")
            elif parts[1] in ("UL", "ML"): self.units = parts[1]; self._reply = self._packet()
            else: self.vol = float(parts[1]); self._reply = self._packet()
        elif parts[0] == "DIR":
            if len(parts) == 1: self._reply = self._packet(self.direction)
            else: self.direction = parts[1]; self._reply = self._packet()
        elif parts[0] == "RUN":
            if self.vol <= 0: self._reply = self._packet("?NA")
            else: self.moved = 0.0; self.running = True; self._reply = self._packet()
        elif parts[0] == "STP": self.running = False; self._reply = self._packet()
        elif parts[0] == "DIS": self._reply = self._packet(f"I{self.infused:.3f}W{self.withdrawn:.3f}{self.units}")
        elif parts[0] == "CLD":
            if parts[1:] == ["INF"]: self.infused = 0.0
            else: self.withdrawn = 0.0
            self._reply = self._packet()
        elif parts[0] == "SAF": self._reply = self._packet()
        elif parts[0] == "VER": self._reply = self._packet("NE1000V3.923")
        else: self._reply = self._packet("?")

    def readline(self):
        return self._reply


class Sim(SerialAsciiDriver):
    link = _FakePort()

    # the same two overrides as driver.py (the twin cannot import the package's driver module by name)
    def _encode(self, cmd: str) -> bytes:
        return super()._encode(f"{int(self.config().get('address', 0)):02d}{cmd}")

    def on_invoke(self, job):
        cmds = self.cfg.get("actions", {}).get(job.action) or []
        replies = []
        for i, c in enumerate(cmds):
            self.checkpoint(job)
            replies.append(self.query(c.format(**job.params)))
            if "?" in replies[-1]:
                raise InvalidValue(f"{job.action}: pump refused {c.format(**job.params)!r}: {replies[-1]!r}")
            self.progress(job, (i + 1) / (len(cmds) + 1))
        if cmds and cmds[-1] == "RUN":
            while True:
                self.checkpoint(job)
                replies.append(self.query("DIS"))
                m = _STATUS.match(replies[-1])
                if not m or m.group(1) not in ("I", "W"):
                    break
                time.sleep(0.02)
        return {"replies": replies}
