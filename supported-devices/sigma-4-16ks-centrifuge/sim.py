"""Simulated twin of a Sigma 4-16KS with the Spincontrol serial interface (echo off).

The rotor accelerates and brakes at 300 rpm per simulated second (fstop: 600), the run timer counts
down once the rotor turns and the run ends at zero; the chamber follows its setpoint with a 5-minute
time constant while spinning. The lid can be opened with `door` only at standstill; `start` with the
lid open is refused (nothing is sent back with echo off, as on the real unit; status stays 2). Time runs
at OPENMHP_SIM_TIME_SCALE real seconds per simulated second (default 0.01). Set `link.lid_open` from a
test to open or close the lid by hand.
"""
import math
import os
import time

from openmhp.drivers.serial_ascii import SerialAsciiDriver


class _FakePort:
    is_open = True

    def __init__(self):
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        self.t = time.time()
        self.speed_sp, self.temp_sp, self.time_sp = 1000, 20, 600
        self.speed, self.temp = 0.0, 22.0
        self.remaining = 0.0
        self.running = False
        self.lid_open = False
        self.error = 0
        self.decel = 300.0
        self.sent: list[str] = []
        self._reply = b""

    def _tick(self):
        now = time.time()
        dt = (now - self.t) / self.scale
        self.t = now
        if self.running:
            self.remaining = max(0.0, self.remaining - dt)
            if self.remaining <= 0 and self.time_sp > 0:
                self.running = False
            target = float(self.speed_sp) if self.running else 0.0
        else:
            target = 0.0
        rate = 300.0 if target > self.speed else self.decel
        self.speed += max(-rate * dt, min(rate * dt, target - self.speed))
        if self.speed <= 0:
            self.decel = 300.0
        tsp = float(self.temp_sp) if (self.running or self.speed > 0) else 22.0
        self.temp += (tsp - self.temp) * (1 - math.exp(-dt / 300.0))

    def _status(self) -> int:
        if self.error:
            return 3
        if self.lid_open:
            return 2
        return 0 if self.speed > 0 else 1

    def write(self, b: bytes):
        cmd = b.decode(errors="replace").strip()
        self.sent.append(cmd)
        self._tick()
        word, _, arg = cmd.partition(" ")
        word, arg = word.lower(), arg.strip()
        reply = None
        if word == "speed":
            reply = f"{self.speed:.0f}"
        elif word == "temp":
            reply = f"{self.temp:.0f}"
        elif word == "time":
            reply = f"{self.remaining:.0f}"
        elif word == "getsetspeed":
            reply = str(self.speed_sp)
        elif word == "getsettemp":
            reply = str(self.temp_sp)
        elif word == "getsettime":
            reply = str(self.time_sp)
        elif word == "status":
            reply = str(self._status())
        elif word == "status1":
            v = (1 if self.lid_open else 2) | ((1 if not self.lid_open and self.speed == 0 else 0) << 2) \
                | ((1 if self.speed > 0 else 0) << 5) | ((1 if self.error else 0) << 6)
            reply = f"{v:04X}"
        elif word == "syserror":
            reply = str(self.error)
        elif word == "setspeed" and arg.lstrip("-").isdigit():
            self.speed_sp = int(arg)
        elif word == "settemp" and arg.lstrip("-").isdigit():
            self.temp_sp = int(arg)
        elif word == "settime" and arg.isdigit():
            self.time_sp = int(arg)
        elif word == "start":
            if not self.lid_open and not self.error:
                self.running, self.remaining = True, float(self.time_sp)
        elif word == "stop":
            self.running = False
        elif word == "fstop":
            self.running, self.decel = False, 600.0
        elif word == "door":
            if self.speed == 0 and not self.running:
                self.lid_open = True
        elif word == "reseterr":
            self.error = 0
        elif word in ("reset", "echoon", "echooff", "cmderror", "info"):
            reply = "1" if word == "cmderror" else None
        else:
            reply = "CNF"
        self._reply = (reply + "\r\n").encode() if reply is not None else b""

    def readline(self) -> bytes:
        r, self._reply = self._reply, b""
        return r


class Sim(SerialAsciiDriver):
    link = _FakePort()
