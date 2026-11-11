"""Simulated twin: answers the EUROSTAR NAMUR commands with a small motor model.

The shaft speed ramps toward the setpoint at about 250 rpm per simulated second and the torque rises
with speed (a viscous load). Simulated time runs faster than the clock: OPENMHP_SIM_TIME_SCALE is the
number of real seconds per simulated second (default 0.01).
"""
import os
import time

from openmhp.drivers.serial_ascii import SerialAsciiDriver


class _FakePort:
    is_open = True

    def __init__(self):
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        self.sp4, self.pv4, self.running = 0.0, 0.0, False
        self.speed_limit, self.torque_limit, self.safety_speed = 2000.0, 60.0, 100.0
        self.t = time.time()
        self._reply = b""
        self.sent = []

    def _tick(self):
        now = time.time()
        dt = (now - self.t) / self.scale
        self.t = now
        target = min(self.sp4, self.speed_limit) if self.running else 0.0
        step = 250.0 * dt
        self.pv4 += max(-step, min(step, target - self.pv4))
        if abs(self.pv4 - target) < 1.0:
            self.pv4 = target

    def _torque(self):
        return min(self.torque_limit, self.pv4 / 25.0)           # a viscous load: torque rises with speed

    def write(self, b):
        cmd = b.decode().strip()
        self.sent.append(cmd)
        self._tick()
        if cmd == "IN_PV_4": self._reply = f"{self.pv4:.0f} 4\r\n".encode()
        elif cmd == "IN_PV_5": self._reply = f"{self._torque():.1f} 5\r\n".encode()
        elif cmd == "IN_SP_4": self._reply = f"{self.sp4:.0f} 4\r\n".encode()
        elif cmd == "IN_SP_5": self._reply = f"{self.torque_limit:.0f} 5\r\n".encode()
        elif cmd == "IN_SP_6": self._reply = f"{self.speed_limit:.0f} 6\r\n".encode()
        elif cmd == "IN_SP_8": self._reply = f"{self.safety_speed:.0f} 8\r\n".encode()
        elif cmd == "IN_NAME": self._reply = b"EUROSTAR 60 control\r\n"
        elif cmd.startswith("OUT_SP_4 "): self.sp4 = float(cmd.split()[1]); self._reply = b"\r\n"
        elif cmd.startswith("OUT_SP_5 "): self.torque_limit = float(cmd.split()[1]); self._reply = b"\r\n"
        elif cmd.startswith("OUT_SP_6 "): self.speed_limit = float(cmd.split()[1]); self._reply = b"\r\n"
        elif cmd == "START_4": self.running = True; self._reply = b"\r\n"
        elif cmd == "STOP_4": self.running = False; self._reply = b"\r\n"
        elif cmd == "RESET": self.running = False; self._reply = b"\r\n"
        else: self._reply = b"Er\r\n"                             # the real reply to an unknown command is unverified

    def readline(self):
        return self._reply


class Sim(SerialAsciiDriver):
    link = _FakePort()
