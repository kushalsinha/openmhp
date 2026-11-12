"""Simulated twin of a LabJack T7: a register map where AIN0 carries a 1 Hz sine, AIN1 is jumpered to DAC0,
AIN2 sits at 0.5 V and AIN3 is noise; FIO writes show up in DIO_STATE; streams run at the requested rate
scaled by OPENMHP_SIM_TIME_SCALE. No labjack-ljm."""
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
        self.reg = {"DAC0": 0.0, "DAC1": 0.0, "FIO0": 0.0, "FIO1": 0.0, "FIO2": 0.0, "FIO3": 0.0, "AIN0_RANGE": 10.0,
                    "SERIAL_NUMBER": 470012345.0, "PRODUCT_ID": 7.0, "FIRMWARE_VERSION": 1.0292}
        self.info = {"device_type": "T7", "serial_number": "470012345", "ip": None}
        self.t0 = time.monotonic()
        self.stream = None

    def open(self):
        self.log.append("openS ANY ANY ANY")

    def close(self):
        self.log.append("close")

    def _t(self) -> float:
        return (time.monotonic() - self.t0) / self.scale

    def _ain(self, name: str, t: float) -> float:
        rng = self.reg["AIN0_RANGE"] if name == "AIN0" else 10.0
        v = {"AIN0": 2.0 * math.sin(2 * math.pi * 1.0 * t), "AIN1": self.reg["DAC0"], "AIN2": 0.5, "AIN3": 0.0}[name]
        return max(-rng, min(rng, v + random.gauss(0, 0.002)))

    def read(self, name: str) -> float:
        if name in real.AIN:
            return self._ain(name, self._t())
        if name == "DIO_STATE":
            return float(sum(int(self.reg[f"FIO{k}"] > 0.5) << k for k in range(4)) | 0xFF0)
        if name not in self.reg:
            raise real.DeviceFault(f"LJM_ERROR 1239 (LJME_INVALID_NAME): {name}")       # unverified error code
        return self.reg[name]

    def reads(self, names):
        return [self.read(n) for n in names]

    def write(self, name, value):
        self.log.append(f"eWriteName {name} {value}")
        if name not in self.reg:
            raise real.DeviceFault(f"LJM_ERROR 1239 (LJME_INVALID_NAME): {name}")
        self.reg[name] = float(value)

    def writes(self, names, values):
        self.log.append("eWriteNames " + " ".join(f"{n}={v}" for n, v in zip(names, values)))
        for n, v in zip(names, values):
            self.reg[n] = float(v)

    def stream_start(self, names, rate_hz, scans_per_read):
        self.log.append(f"eStreamStart {rate_hz} Hz {names}")
        self.stream = {"names": list(names), "rate": float(rate_hz), "per_read": scans_per_read, "n": 0, "t0": time.monotonic()}
        return float(rate_hz)

    def stream_read(self):
        s = self.stream
        due = s["t0"] + (s["n"] + s["per_read"]) / s["rate"] * self.scale
        while time.monotonic() < due:
            time.sleep(min(0.01, due - time.monotonic()))
        out = []
        for k in range(s["per_read"]):
            t = (s["n"] + k) / s["rate"]
            out += [self._ain(n, t) for n in s["names"]]
        s["n"] += s["per_read"]
        return out

    def stream_stop(self):
        self.log.append("eStreamStop")
        self.stream = None


class SimLabJackT(real.LabJackT):
    def setup(self) -> None:
        super().setup()
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        home = pathlib.Path(os.environ.get("OPENMHP_HOME", pathlib.Path.home() / ".openmhp"))
        self.cfg = {"identifier": "ANY", "data_dir": str(home / "sim-data" / "labjack-t-series")}

    def time_scale(self) -> float:
        return self.scale

    def make_backend(self):
        self.link = SimBackend(self.scale)
        return self.link
