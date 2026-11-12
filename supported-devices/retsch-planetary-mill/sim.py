"""Simulated twin of a Retsch planetary mill answering the template command set (references/protocol.md).

The sun wheel accelerates and brakes at about 150 rpm per simulated second, the grinding timer counts
down while it turns and the grind ends at zero; the lid lock only lets the lid open at standstill.
Time runs at OPENMHP_SIM_TIME_SCALE real seconds per simulated second (default 0.01). A test opens the
lid with `link.lid_open = True` (refused while the drive turns, as the lock would). An unknown command is
answered with the placeholder error text `ERR`.
"""
import os
import time

from openmhp.drivers.serial_ascii import SerialAsciiDriver


class _FakePort:
    is_open = True

    def __init__(self):
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        self.t = time.time()
        self.speed_sp, self.time_sp = 300, 600
        self.speed, self.remaining = 0.0, 0.0
        self.running = False
        self._lid_open = False
        self.sent: list[str] = []
        self._reply = b""

    @property
    def lid_open(self) -> bool:
        return self._lid_open

    @lid_open.setter
    def lid_open(self, value: bool) -> None:
        self._tick()
        if value and (self.running or self.speed > 0):
            return                                         # the lid lock holds while the sun wheel turns
        self._lid_open = bool(value)

    def _tick(self):
        now = time.time()
        dt = (now - self.t) / self.scale
        self.t = now
        if self.running:
            self.remaining = max(0.0, self.remaining - dt)
            if self.remaining <= 0:
                self.running = False
        target = float(self.speed_sp) if self.running else 0.0
        self.speed += max(-150.0 * dt, min(150.0 * dt, target - self.speed))

    def write(self, b: bytes):
        cmd = b.decode(errors="replace").strip()
        self.sent.append(cmd)
        self._tick()
        word, _, arg = cmd.partition(" ")
        word, arg = word.upper(), arg.strip()
        reply = "OK"
        if word == "SPEED?":
            reply = f"{self.speed:.0f}"
        elif word == "SPEEDSP?":
            reply = str(self.speed_sp)
        elif word == "REMAIN?":
            reply = f"{self.remaining:.0f}"
        elif word == "STATUS?":
            reply = "RUN" if self.running or self.speed > 0 else "STOP"
        elif word == "LID?":
            reply = "OPEN" if self._lid_open else "CLOSED"
        elif word == "SPEED" and arg.isdigit():
            self.speed_sp = int(arg)
        elif word == "TIME" and arg.isdigit():
            self.time_sp = int(arg)
        elif word == "START":
            if self._lid_open:
                reply = "ERR LID"
            else:
                self.running, self.remaining = True, float(self.time_sp)
        elif word == "STOP":
            self.running = False
        else:
            reply = "ERR"
        self._reply = (reply + "\r\n").encode()

    def readline(self) -> bytes:
        r, self._reply = self._reply, b""
        return r


class Sim(SerialAsciiDriver):
    link = _FakePort()
