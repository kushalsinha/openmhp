"""Simulated twin: answers the same NAMUR commands with a simple thermal model."""
import time
from openmhp.drivers.serial_ascii import SerialAsciiDriver


class _FakePort:
    def __init__(self):
        self.sp1, self.sp4, self.pv1, self.pv4 = 20.0, 0.0, 22.0, 0.0
        self.heat = self.stir = False
        self.t = time.time(); self._reply = b""

    def _tick(self):
        dt, self.t = time.time() - self.t, time.time()
        target = self.sp1 if self.heat else 22.0
        self.pv1 += max(-2.0 * dt * 10, min(2.0 * dt * 10, target - self.pv1))   # fast for demos
        self.pv4 = self.sp4 if self.stir else 0.0

    def write(self, b):
        cmd = b.decode().strip(); self._tick()
        if cmd == "IN_PV_1": self._reply = f"{self.pv1:.1f} 1\r\n".encode()
        elif cmd == "IN_SP_1": self._reply = f"{self.sp1:.1f} 1\r\n".encode()
        elif cmd == "IN_PV_4": self._reply = f"{self.pv4:.0f} 4\r\n".encode()
        elif cmd.startswith("OUT_SP_1"): self.sp1 = float(cmd.split()[1]); self._reply = b"\r\n"
        elif cmd.startswith("OUT_SP_4"): self.sp4 = float(cmd.split()[1]); self._reply = b"\r\n"
        elif cmd == "START_1": self.heat = True; self._reply = b"\r\n"
        elif cmd == "STOP_1": self.heat = False; self._reply = b"\r\n"
        elif cmd == "START_4": self.stir = True; self._reply = b"\r\n"
        elif cmd == "STOP_4": self.stir = False; self._reply = b"\r\n"
        else: self._reply = b"Er\r\n"

    def readline(self):
        return self._reply


class Sim(SerialAsciiDriver):
    link = _FakePort()
