"""Simulated twin: answers MT-SICS level 0/1 commands with a settling-pan model.

Set `load_g` on the fake port to put a mass on the pan; the reading settles over about 2 simulated
seconds (SI answers S D while it settles, S S afterwards). Simulated time runs faster than the clock:
OPENMHP_SIM_TIME_SCALE is the number of real seconds per simulated second (default 0.01).
"""
import os
import time

from openmhp.drivers.serial_ascii import SerialAsciiDriver


class _FakePort:
    is_open = True

    def __init__(self):
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        self.load_g, self.tare_g, self.zero_g = 12.3456, 0.0, 0.0
        self.capacity_g = 220.0
        self.changed = time.time()
        self._last_load = self.load_g
        self._reply = b""
        self.sent = []

    def _stable(self):
        if self.load_g != self._last_load:
            self._last_load, self.changed = self.load_g, time.time()
        return (time.time() - self.changed) / self.scale > 2.0

    def _net(self):
        return self.load_g - self.zero_g - self.tare_g

    def _weight(self, status):
        return f"S {status} {self._net():10.4f} g\r\n".encode()

    def write(self, b):
        cmd = b.decode().strip()
        self.sent.append(cmd)
        stable = self._stable()
        if cmd == "S":
            if self.load_g - self.zero_g > self.capacity_g: self._reply = b"S +\r\n"
            else: self._reply = self._weight("S") if stable else b"S I\r\n"
        elif cmd == "SI": self._reply = self._weight("S" if stable else "D")
        elif cmd == "T":
            if stable: self.tare_g = self.load_g - self.zero_g; self._reply = f"T S {self.tare_g:10.4f} g\r\n".encode()
            else: self._reply = b"T I\r\n"
        elif cmd == "Z":
            if stable: self.zero_g, self.tare_g = self.load_g, 0.0; self._reply = b"Z A\r\n"
            else: self._reply = b"Z I\r\n"
        elif cmd == "TA": self._reply = f"TA A {self.tare_g:10.4f} g\r\n".encode()
        elif cmd.startswith("TA "):
            self.tare_g = float(cmd.split()[1]); self._reply = f"TA A {self.tare_g:10.4f} g\r\n".encode()
        elif cmd == "TAC": self.tare_g = 0.0; self._reply = b"TAC A\r\n"
        elif cmd == "I2": self._reply = b'I2 A "XS205 Excellence 220.00900 g"\r\n'
        elif cmd == "I3": self._reply = b'I3 A "4.10 10.28.0.493.142"\r\n'
        elif cmd == "I4": self._reply = b'I4 A "1114350697"\r\n'
        elif cmd.startswith('D "'): self._reply = b"D A\r\n"
        elif cmd == "DW": self._reply = b"DW A\r\n"
        elif cmd == "@": self.tare_g = 0.0; self._reply = b'I4 A "1114350697"\r\n'
        elif cmd == "C3": self._reply = b"C3 B\r\n"
        else: self._reply = b"ES\r\n"

    def readline(self):
        return self._reply


class Sim(SerialAsciiDriver):
    link = _FakePort()
