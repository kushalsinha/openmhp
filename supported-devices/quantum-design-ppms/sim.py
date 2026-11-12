"""Simulated twin of the PPMS: a fake MultiPyVu client whose temperature and field ramp toward their setpoints
at the requested rates and whose chamber settles after a scaled delay. Status words are the ones MultiVu is
known to use. Time scaled by OPENMHP_SIM_TIME_SCALE."""
from __future__ import annotations

import importlib.util
import os
import pathlib
import sys
import time

_spec = importlib.util.spec_from_file_location(__name__ + "_real", pathlib.Path(__file__).with_name("driver.py"))
real = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = real
_spec.loader.exec_module(real)


class _Enum:
    def __init__(self, *names):
        for n in names:
            setattr(self, n, n)


class _Section:
    def __init__(self, **enums):
        for k, v in enums.items():
            setattr(self, k, v)


CHAMBER_WORDS = {"seal": ("Pumping", "Sealed"), "purge_seal": ("Pumping", "Purged and Sealed"),
                 "vent_seal": ("Flooding", "Vented and Sealed"), "pump_continuous": ("Pumping", "Pumping Continuously"),
                 "vent_continuous": ("Flooding", "Venting Continuously"), "high_vacuum": ("Pumping", "High Vacuum")}


class FakeMultiVu:
    """The MultiPyVu.Client surface this package uses, answered by a first-order ramp model."""

    def __init__(self, scale: float):
        self.scale, self.log = scale, []
        self.temperature = _Section(approach_mode=_Enum("fast_settle", "no_overshoot"))
        self.field = _Section(approach_mode=_Enum("linear", "no_overshoot", "oscillate"), driven_mode=_Enum("persistent", "driven"))
        self.chamber = _Section(mode=_Enum(*CHAMBER_WORDS))
        self.t, self.t_sp, self.t_rate, self.t_approach = 300.0, 300.0, 5.0, "fast_settle"
        self.h, self.h_sp, self.h_rate, self.h_approach, self.h_driven = 0.0, 0.0, 100.0, "linear", "persistent"
        self.chamber_word, self.chamber_until, self.chamber_next = "Purged and Sealed", 0.0, None
        self.last = time.monotonic()

    def _tick(self):
        now = time.monotonic()
        dt = (now - self.last) / self.scale                      # instrument seconds
        self.last = now
        step = self.t_rate / 60 * dt
        if abs(self.t_sp - self.t) <= step:
            self.t = self.t_sp
        else:
            self.t += step if self.t_sp > self.t else -step
        step = self.h_rate * dt
        if abs(self.h_sp - self.h) <= step:
            self.h = self.h_sp
        else:
            self.h += step if self.h_sp > self.h else -step
        if self.chamber_next and now >= self.chamber_until:
            self.chamber_word, self.chamber_next = self.chamber_next, None

    def open(self):
        self.log.append("open")

    def close_client(self):
        self.log.append("close_client")

    def get_temperature(self):
        self._tick()
        d = abs(self.t - self.t_sp)
        status = "Stable" if d < 0.01 else "Near" if d < 0.5 else "Tracking"
        return self.t, status

    def get_temperature_setpoints(self):
        return self.t_sp, self.t_rate, self.t_approach

    def set_temperature(self, set_point, rate_K_per_min, approach):
        self._tick()
        self.log.append(f"set_temperature {set_point} {rate_K_per_min} {approach}")
        self.t_sp, self.t_rate, self.t_approach = float(set_point), float(rate_K_per_min), approach

    def get_field(self):
        self._tick()
        if abs(self.h - self.h_sp) < 0.5:
            return self.h, "Stable Persistent" if self.h_driven == "persistent" else "Stable Driven"
        return self.h, "Charging" if abs(self.h_sp) > abs(self.h) else "Discharging"

    def get_field_setpoints(self):
        return self.h_sp, self.h_rate, self.h_approach, self.h_driven

    def set_field(self, set_point, rate_oe_per_sec, approach, driven=None):
        self._tick()
        self.log.append(f"set_field {set_point} {rate_oe_per_sec} {approach} {driven}")
        self.h_sp, self.h_rate, self.h_approach = float(set_point), float(rate_oe_per_sec), approach
        if driven is not None:
            self.h_driven = driven

    def get_chamber(self):
        self._tick()
        return self.chamber_word

    def set_chamber(self, mode):
        self.log.append(f"set_chamber {mode}")
        during, after = CHAMBER_WORDS[mode]
        self.chamber_word, self.chamber_next = during, after
        self.chamber_until = time.monotonic() + 120 * self.scale


class SimBackend(real.PpmsBackend):
    def __init__(self, cfg, scale):
        super().__init__(cfg)
        self.scale = scale
        self.fake = FakeMultiVu(scale)
        self.log = self.fake.log

    def open(self):
        self.client = self.fake
        self.client.open()


class SimPpmsCryostat(real.PpmsCryostat):
    def setup(self) -> None:
        super().setup()
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        self.cfg = {"host": "sim", "port": 27183, "platform": "ppms"}

    def time_scale(self) -> float:
        return self.scale

    def make_backend(self):
        return SimBackend(self.cfg, self.scale)
