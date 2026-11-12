"""Simulated twin: answers SBI commands with a settling-pan model.

Set `load_g` on the fake port to put a mass on the pan; for about 2 simulated seconds after a change
the print frame carries no unit (unstable). Simulated time runs faster than the clock:
OPENMHP_SIM_TIME_SCALE is the number of real seconds per simulated second (default 0.01).
"""
import os
import re
import time

from openmhp.drivers.serial_ascii import SerialAsciiDriver


class _FakePort:
    is_open = True
    ESC = b"\x1b"

    def __init__(self):
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        self.load_g, self.tare_g, self.zero_g = 12.3456, 0.0, 0.0
        self.locked = False
        self.changed = time.time()
        self._last_load = self.load_g
        self._reply = b""
        self.sent = []

    def _stable(self):
        if self.load_g != self._last_load:
            self._last_load, self.changed = self.load_g, time.time()
        return (time.time() - self.changed) / self.scale > 2.0

    def _frame(self):
        net = self.load_g - self.zero_g - self.tare_g
        sign = "-" if net < 0 else "+"
        unit = "g  " if self._stable() else "   "
        return f"N     {sign}{abs(net):9.4f} {unit}\r\n".encode()        # 22-character frame with id "N"

    def write(self, b):
        self.sent.append(b)
        if not b.startswith(self.ESC):
            self._reply = b""
            return
        cmd = b[1:].decode().strip()
        if cmd == "P": self._reply = self._frame()
        elif cmd == "T": self.tare_g = self.load_g - self.zero_g; self._reply = b""
        elif cmd == "V": self.zero_g, self.tare_g = self.load_g, 0.0; self._reply = b""
        elif cmd == "O": self.locked = True; self._reply = b""
        elif cmd == "R": self.locked = False; self._reply = b""
        elif cmd == "S": self.tare_g = 0.0; self._reply = b""
        elif cmd == "Z": self._reply = b""
        elif cmd == "x1_": self._reply = b"Model    ENTRIS224I-1S\r\n"
        elif cmd == "x2_": self._reply = b"Ser. no. 0036512345\r\n"
        elif cmd == "x3_": self._reply = b"Version  01-70-01\r\n"
        else: self._reply = b""                                       # SBI control commands are not answered

    def readline(self):
        return self._reply


class Sim(SerialAsciiDriver):
    link = _FakePort()

    # the same two overrides as driver.py (the twin cannot import the package's driver module by name)
    def _encode(self, cmd: str) -> bytes:
        prefix = str(self.cfg.get("prefix", "")).encode().decode("unicode_escape")
        return prefix.encode() + super()._encode(cmd)

    @staticmethod
    def _text(raw) -> str:
        return re.sub(r"([-+])\s+(?=\d)", r"\1", SerialAsciiDriver._text(raw))
