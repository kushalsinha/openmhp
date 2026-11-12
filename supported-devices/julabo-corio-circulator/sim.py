"""Simulated twin: answers the JULABO interface commands with a small bath model.

The bath temperature moves toward the setpoint at up to 0.5 degC per simulated second while tempering
is started and drifts toward 22 degC otherwise. Simulated time runs faster than the clock:
OPENMHP_SIM_TIME_SCALE is the number of real seconds per simulated second (default 0.01).
"""
import os
import time

from openmhp.drivers.serial_ascii import SerialAsciiDriver


class _FakePort:
    is_open = True

    def __init__(self):
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        self.sp, self.pv, self.ext, self.started = 20.0, 22.0, 22.0, False
        self.protective = 120.0
        self.t = time.time()
        self._reply = b""
        self.sent = []

    def _tick(self):
        now = time.time()
        dt = (now - self.t) / self.scale
        self.t = now
        target = self.sp if self.started else 22.0
        rate = 0.5 if self.started else 0.02
        self.pv += max(-rate * dt, min(rate * dt, target - self.pv))
        self.ext += max(-0.3 * dt, min(0.3 * dt, self.pv - self.ext))

    def _power(self):
        if not self.started:
            return 0.0
        return max(-100.0, min(100.0, (self.sp - self.pv) * 20.0))

    def write(self, b):
        cmd = b.decode().strip()
        self.sent.append(cmd)
        self._tick()
        if cmd == "in_pv_00": self._reply = f"{self.pv:.2f}\r\n".encode()
        elif cmd == "in_pv_01": self._reply = f"{self._power():.1f}\r\n".encode()
        elif cmd == "in_pv_02": self._reply = f"{self.ext:.2f}\r\n".encode()
        elif cmd == "in_pv_03": self._reply = f"{self.pv + 0.3:.2f}\r\n".encode()
        elif cmd == "in_pv_04": self._reply = f"{self.protective:.0f}\r\n".encode()
        elif cmd == "in_sp_00": self._reply = f"{self.sp:.2f}\r\n".encode()
        elif cmd == "in_mode_05": self._reply = b"1\r\n" if self.started else b"0\r\n"
        elif cmd == "version": self._reply = b"JULABO CORIO CD SIM 1.0\r\n"
        elif cmd == "status": self._reply = b"03 REMOTE START\r\n" if self.started else b"02 REMOTE STOP\r\n"
        elif cmd.startswith("out_sp_00 "):
            value = float(cmd.split()[1])
            if value > self.protective:
                self._reply = b"-13 VALUE EXCEEDS TEMPERATURE LIMITS\r\n"
            else:
                self.sp = value; self._reply = b""                 # out_ commands are not answered
        elif cmd == "out_mode_05 1": self.started = True; self._reply = b""
        elif cmd == "out_mode_05 0": self.started = False; self._reply = b""
        else: self._reply = b"-08 INVALID COMMAND\r\n"

    def readline(self):
        return self._reply


class Sim(SerialAsciiDriver):
    link = _FakePort()
