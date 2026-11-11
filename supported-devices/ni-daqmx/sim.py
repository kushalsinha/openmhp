"""Simulated twin of a USB-6009 under NI-DAQmx: ai0 carries a 1 Hz sine, ai1 is jumpered to ao0, ai2 sits at 0.5 V
and ai3 is noise; AO and DO writes are logged; hardware-timed reads run at the requested rate scaled by
OPENMHP_SIM_TIME_SCALE. No nidaqmx."""
from __future__ import annotations

import importlib.util
import math
import os
import pathlib
import random
import sys
import time

_spec = importlib.util.spec_from_file_location(__name__ + "_real", pathlib.Path(__file__).with_name("driver.py"))
real = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = real
_spec.loader.exec_module(real)


class SimBackend:
    def __init__(self, scale: float):
        self.scale = scale
        self.log: list[str] = []
        self.dev, self.product_type = "Dev1", "USB-6009"
        self.ao = {"ao0": 0.0, "ao1": 0.0}
        self.do = {line: False for line in real.LINES}
        self.t0 = time.monotonic()
        self.stream = None

    def open(self):
        self.log.append("System.local().devices -> Dev1 USB-6009")

    def close(self):
        self.stream_stop()

    def _t(self) -> float:
        return (time.monotonic() - self.t0) / self.scale

    def _ai(self, ch: str, t: float) -> float:
        v = {"ai0": 2.0 * math.sin(2 * math.pi * t), "ai1": self.ao["ao0"], "ai2": 0.5, "ai3": 0.0}[ch]
        return max(-10.0, min(10.0, v + random.gauss(0, 0.003)))

    def read_ai(self, channels):
        t = self._t()
        return [self._ai(c, t) for c in channels]

    def write_ao(self, channel, volts):
        self.log.append(f"write {channel} {volts}")
        if not 0.0 <= volts <= 5.0:
            raise real.DeviceFault(f"DaqError -200561: {volts} V is outside the USB-6009's 0-5 V AO range")   # unverified code
        self.ao[channel] = float(volts)

    def write_do(self, line, high):
        self.log.append(f"write {line} {'high' if high else 'low'}")
        self.do[line] = bool(high)

    def stream_start(self, channels, rate_hz, samples_per_read):
        self.log.append(f"cfg_samp_clk_timing {rate_hz} Hz {channels}; start")
        self.stream = {"channels": list(channels), "rate": float(rate_hz), "n": 0, "t0": time.monotonic()}
        return float(rate_hz)

    def stream_read(self, samples_per_read):
        s = self.stream
        due = s["t0"] + (s["n"] + samples_per_read) / s["rate"] * self.scale
        while time.monotonic() < due:
            time.sleep(min(0.01, due - time.monotonic()))
        rows = [[self._ai(c, (s["n"] + k) / s["rate"]) for c in s["channels"]] for k in range(samples_per_read)]
        s["n"] += samples_per_read
        return rows

    def stream_stop(self):
        if self.stream is not None:
            self.log.append("stop; close")
            self.stream = None


class SimNIDaqmx(real.NIDaqmx):
    def setup(self) -> None:
        super().setup()
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        home = pathlib.Path(os.environ.get("OPENMHP_HOME", pathlib.Path.home() / ".openmhp"))
        self.cfg = {"device": "Dev1", "data_dir": str(home / "sim-data" / "ni-daqmx")}

    def time_scale(self) -> float:
        return self.scale

    def make_backend(self):
        self.link = SimBackend(self.scale)
        return self.link
