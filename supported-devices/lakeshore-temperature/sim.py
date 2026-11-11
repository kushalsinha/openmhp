"""Simulated Lake Shore 335: answers the command subset in descriptor.yaml with a small cryostat model.

Input A is the controlled stage, input B a colder sensor nearby. With the heater range off the
stage cools toward 4.2 K; with it on, the stage moves toward the (possibly ramping) setpoint at
a speed that grows with the range. Simulated time runs at 1/OPENMHP_SIM_TIME_SCALE real time
(default 0.01: a real second is 100 simulated seconds). Unknown commands get no reply, which
is what the instrument does (it has no error text).
"""
import os
import time

from openmhp.drivers.scpi_visa import ScpiVisaDriver


class _FakeInst:
    is_open = True

    def __init__(self):
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        self.t = time.time()
        self.temp = {"A": 4.2, "B": 4.0}
        self.setp = {1: 4.2, 2: 4.2}          # written setpoints
        self.held = {1: 4.2, 2: 4.2}          # what the ramp has reached
        self.range = {1: 0, 2: 0}
        self.htr = {1: 0.0, 2: 0.0}
        self.ramp = {1: (0, 1.0), 2: (0, 1.0)}
        self.sent, self._r = [], b""

    def _tick(self):
        now = time.time()
        dt = (now - self.t) / self.scale            # simulated seconds
        self.t = now
        on, rate = self.ramp[1]
        if on:
            step = rate / 60.0 * dt
            diff = self.setp[1] - self.held[1]
            self.held[1] += max(-step, min(step, diff))
        else:
            self.held[1] = self.setp[1]
        self.held[2] = self.setp[2]
        if self.range[1]:
            target = self.held[1]
            speed = 0.02 * (10 ** (self.range[1] - 1))   # K/s per K of error
            self.temp["A"] += (target - self.temp["A"]) * min(1.0, speed * dt)
            self.htr[1] = max(0.0, min(100.0, 10.0 * (target - self.temp["A"]) + 20.0))
        else:
            self.temp["A"] += (4.2 - self.temp["A"]) * min(1.0, 0.005 * dt)
            self.htr[1] = 0.0
        self.temp["B"] = 4.0 + 0.1 * (self.temp["A"] - 4.2)
        self.htr[2] = 0.0 if not self.range[2] else 5.0

    def write(self, b):
        c = b.decode().strip()
        self.sent.append(c)
        self._tick()
        self._r = b""
        head, _, arg = c.partition(" ")
        head = head.upper()
        args = [a.strip() for a in arg.split(",")] if arg else []
        if head == "*IDN?":
            self._r = b"LSCI,MODEL335,LSA1234,2.5\r\n"
        elif head == "KRDG?" and args:
            self._r = f"+{self.temp.get(args[0].upper(), 0.0):.3f}\r\n".encode()
        elif head == "CRDG?" and args:
            self._r = f"{self.temp.get(args[0].upper(), 273.15) - 273.15:+.3f}\r\n".encode()
        elif head == "SETP?" and args:
            self._r = f"+{self.held[int(args[0])]:.3f}\r\n".encode()
        elif head == "SETP" and len(args) == 2:
            self.setp[int(args[0])] = float(args[1])
        elif head == "RANGE?" and args:
            self._r = f"{self.range[int(args[0])]}\r\n".encode()
        elif head == "RANGE" and len(args) == 2:
            self.range[int(args[0])] = int(args[1])
        elif head == "HTR?" and args:
            self._r = f"+{self.htr[int(args[0])]:.2f}\r\n".encode()
        elif head == "RAMP?" and args:
            on, rate = self.ramp[int(args[0])]
            self._r = f"{on},{rate:.1f}\r\n".encode()
        elif head == "RAMP" and len(args) == 3:
            self.ramp[int(args[0])] = (int(args[1]), float(args[2]))
        elif head == "OUTMODE?" and args:
            self._r = b"1,1,1\r\n"
        # anything else: the instrument answers nothing

    def readline(self):
        return self._r


class Sim(ScpiVisaDriver):
    link = _FakeInst()
