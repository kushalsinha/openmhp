"""Simulated twin: an XPR balance with a Quantos dosing head, answering MT-SICS plus the placeholder QD commands.

The pan settles over ~2 simulated seconds after any change; a dose adds powder toward the A10 target at
about 2 mg per simulated second and stops inside the tolerance (QDR reports the dispensed mass and OK, or
OUT when it overshot). Set `head` False on the fake port to unmount the head. Simulated time runs faster
than the clock: OPENMHP_SIM_TIME_SCALE is the number of real seconds per simulated second (default 0.01).
"""
from __future__ import annotations

import os
import random
import time

try:
    from .driver import Device
except ImportError:                                          # loaded by path (load_driver): driver.py sits beside this file
    import importlib.util as _ilu
    import pathlib as _pl
    import sys as _sys
    _spec = _ilu.spec_from_file_location(__name__ + "_real", _pl.Path(__file__).with_name("driver.py"))
    _real = _ilu.module_from_spec(_spec)
    _sys.modules[_spec.name] = _real
    _spec.loader.exec_module(_real)
    Device = _real.Device


class _FakePort:
    is_open = True

    def __init__(self):
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        self.load_g, self.tare_g, self.zero_g = 5.2000, 0.0, 0.0
        self.capacity_g = 220.0
        self.head = True
        self.target_mg, self.tol_plus, self.tol_minus = 0.0, 2.0, 2.0
        self.dosing, self.dosed_mg, self.last_result = False, 0.0, None
        self.changed = time.time()
        self._last_load = self.load_g
        self._reply = b""
        self.sent = []
        self.t = time.time()

    def _tick(self):
        now = time.time()
        dt = (now - self.t) / self.scale
        self.t = now
        if self.dosing:
            step = min(2.0 * dt, self.target_mg - self.dosed_mg + random.uniform(-0.02, 0.05) * self.target_mg / 100)
            if step > 0:
                self.dosed_mg += step; self.load_g += step / 1000.0
            if self.dosed_mg >= self.target_mg * (1 - self.tol_minus / 100):
                self.dosing = False
                ok = self.dosed_mg <= self.target_mg * (1 + self.tol_plus / 100)
                self.last_result = (self.dosed_mg, "OK" if ok else "OUT")

    def _stable(self):
        if self.load_g != self._last_load:
            self._last_load, self.changed = self.load_g, time.time()
        return (time.time() - self.changed) / self.scale > 2.0 and not self.dosing

    def _net(self):
        return self.load_g - self.zero_g - self.tare_g

    def _weight(self, status):
        return f"S {status} {self._net():10.4f} g\r\n".encode()

    def write(self, b):
        cmd = b.decode().strip()
        self.sent.append(cmd)
        self._tick()
        stable = self._stable()
        parts = cmd.split()
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
        elif cmd == "TAC": self.tare_g = 0.0; self._reply = b"TAC A\r\n"
        elif cmd == "I2": self._reply = b'I2 A "XPR205 220.00900 g"\r\n'
        elif cmd == "I3": self._reply = b'I3 A "2.3.0 10.28.0.600.145"\r\n'
        elif cmd == "I4": self._reply = b'I4 A "B250123456"\r\n'
        elif cmd == "C3": self._reply = b"C3 B\r\n"
        elif cmd == "@":
            self.dosing, self.tare_g = False, 0.0; self._reply = b'I4 A "B250123456"\r\n'
        elif parts[0] == "A10" and len(parts) == 4:                   # A10 <No> <Value> <Unit>
            no, value, unit = parts[1], parts[2], parts[3]
            try:
                v = float(value)
            except ValueError:
                self._reply = b"A10 L\r\n"; return
            if len(value.split(".")[-1]) > 2 and "." in value:
                self._reply = b"A10 L\r\n"; return
            if no == "0": self.target_mg = v * (1000.0 if unit == "g" else 1.0)
            elif no == "1": self.tol_plus = v
            elif no == "2": self.tol_minus = v
            else: self._reply = b"A10 L\r\n"; return
            self._reply = b"A10 A\r\n"
        elif cmd == "QDS":                                             # placeholder: start the dose (unverified)
            if not self.head: self._reply = b"QDS L\r\n"
            elif self.target_mg <= 0: self._reply = b"QDS L\r\n"
            else:
                self.dosing, self.dosed_mg, self.last_result = True, 0.0, None
                self._reply = b"QDS B\r\n"
        elif cmd == "QDR":                                             # placeholder: dose result (unverified)
            if self.dosing: self._reply = b"QDR I\r\n"
            elif self.last_result is None: self._reply = b"QDR L\r\n"
            else: self._reply = f"QDR A {self.last_result[0]:.2f} mg {self.last_result[1]}\r\n".encode()
        elif cmd == "QDH":                                             # placeholder: head data (unverified)
            self._reply = b'QDH A 1 "Caffeine" "L2411" 180\r\n' if self.head else b"QDH A 0\r\n"
        else: self._reply = b"ES\r\n"

    def readline(self):
        self._tick()
        if self.sent and self.sent[-1] == "QDR" and self.dosing:    # a real head answers only when done: the twin waits
            deadline = time.time() + 30 * self.scale * 60
            while self.dosing and time.time() < deadline:
                time.sleep(0.001); self._tick()
            self.write(b"QDR")
            self.sent.pop()
        return self._reply


class Sim(Device):
    link = _FakePort()
