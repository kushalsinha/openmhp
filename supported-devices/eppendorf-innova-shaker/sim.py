"""Simulated twin of an Innova 44R in Slave mode: echoes every command, then answers reports.

The platform ramps at 50 rpm per simulated second towards its setpoint; the chamber moves towards its
setpoint with a 15-minute time constant (heating) and the same cooling (R model). Time runs at
OPENMHP_SIM_TIME_SCALE real seconds per simulated second (default 0.01). As on the real shaker, a set
command produces nothing but the echo, and an unknown command is echoed and otherwise ignored.
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
        self.speed_sp, self.speed = 0.0, 0.0
        self.temp_sp, self.temp = 37.0, 22.0
        self.humidity = 0.0
        self.profile = (0, 0, 0)                 # running, profile, step
        self.sent: list[str] = []
        self._reply = b""

    def _tick(self):
        now = time.time()
        dt = (now - self.t) / self.scale
        self.t = now
        step = 50.0 * dt
        self.speed += max(-step, min(step, self.speed_sp - self.speed))
        self.temp += (self.temp_sp - self.temp) * (1 - math.exp(-dt / 900.0))

    def write(self, b: bytes):
        cmd = b.decode(errors="replace").rstrip("\r\n")
        self.sent.append(cmd)
        self._tick()
        echo = cmd + "\r"                        # the shaker echoes every character, CR included
        parts = cmd.split()
        mn = parts[0].upper() if parts else ""
        args = parts[1:]
        data = None
        if mn == "RV":
            data = f"{self.speed:.0f}\t{self.temp:.1f}\t{self.humidity:.0f}\t0.0\t0\t0"
        elif mn == "RS":
            data = f"{self.speed_sp:.0f}\t{self.temp_sp:.1f}\t0\t0.0\t0\t0"
        elif mn == "RI":
            data = "D\tH"
        elif mn == "PM":
            data = " ".join(str(x) for x in self.profile)
        elif mn == "CS" and args:
            self.speed_sp = max(0.0, min(400.0, float(args[0])))
        elif mn == "CT" and args:
            self.temp_sp = max(4.0, min(60.0, float(args[0])))
        elif mn == "PS":
            if args:
                self.profile = (1, int(args[0]), int(args[1]) if len(args) > 1 else 1)
                self.speed_sp, self.temp_sp = 200.0, 37.0
            else:
                self.profile = (0, 0, 0)
        self._reply = echo.encode() + ((data + "\r\n").encode() if data is not None else b"")

    def readline(self) -> bytes:
        r, self._reply = self._reply, b""
        return r


class Sim(SerialAsciiDriver):
    link = _FakePort()
