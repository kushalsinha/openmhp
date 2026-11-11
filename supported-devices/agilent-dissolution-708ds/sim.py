"""Simulated twin of a 708-DS bath answering the PLACEHOLDER frames of descriptor.yaml.

The bath heats towards its setpoint with a 20-minute time constant (cooling 60 minutes), the spindles
reach speed in 5 s, the run timer counts down in minutes and the run ends by itself. Replies are
10-character frames: Comm ID, the four-character code echoed, four data digits (temperatures as
ttt.t * 10). Frames with an unknown code or another Comm ID get no reply, as a real 708-DS is
assumed to do. Time runs at OPENMHP_SIM_TIME_SCALE real seconds per simulated second (default 0.01).
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
        self.temp_sp, self.temp = 37.0, 22.0
        self.rpm_sp, self.rpm = 50, 0.0
        self.run_min, self.remaining = 60, 0.0
        self.running = False
        self.heater = True
        self.dropped = False
        self.sent: list[str] = []
        self._reply = b""

    def _tick(self):
        now = time.time()
        dt = (now - self.t) / self.scale
        self.t = now
        tsp = self.temp_sp if self.heater else 22.0
        tau = 1200.0 if tsp > self.temp else 3600.0
        self.temp += (tsp - self.temp) * (1 - math.exp(-dt / tau))
        if self.running:
            self.remaining = max(0.0, self.remaining - dt / 60.0)
            if self.remaining <= 0:
                self.running = False
        target = float(self.rpm_sp) if self.running else 0.0
        step = 10.0 * dt
        self.rpm += max(-step, min(step, target - self.rpm))

    def write(self, b: bytes):
        frame = b.decode(errors="replace").strip()
        self.sent.append(frame)
        self._tick()
        if len(frame) < 6 or frame[:2] != "01":
            self._reply = b""
            return
        code, data = frame[2:6], frame[6:]
        reply = None
        if code == "5293":
            reply = "5293DLO0710C000"
        elif code == "RBAT":
            reply = f"01RBAT{int(round(self.temp * 10)):04d}"
        elif code == "RVT1":
            reply = f"01RVT1{int(round((self.temp - 0.2) * 10)):04d}"
        elif code == "RRPM":
            reply = f"01RRPM{int(round(self.rpm)):04d}"
        elif code == "RRUN":
            reply = f"01RRUN000{1 if self.running else 0}"
        elif code == "RTIM":
            reply = f"01RTIM{int(math.ceil(self.remaining)):04d}"
        elif code == "RHTR":
            reply = f"01RHTR000{1 if self.heater else 0}"
        elif code == "WBAT":
            self.temp_sp = float(data)
            reply = frame
        elif code == "WRPM":
            self.rpm_sp = int(float(data))
            reply = frame
        elif code == "WTIM":
            self.run_min = int(float(data))
            reply = frame
        elif code == "WRUN":
            if data.endswith("1"):
                self.running, self.remaining = True, float(self.run_min)
            else:
                self.running = False
            reply = frame
        elif code == "WHTR":
            self.heater = data.endswith("1")
            reply = frame
        elif code == "WDDM":
            self.dropped = True
            reply = frame
        self._reply = (reply + "\r").encode() if reply is not None else b""

    def readline(self) -> bytes:
        r, self._reply = self._reply, b""
        return r


class Sim(SerialAsciiDriver):
    link = _FakePort()
