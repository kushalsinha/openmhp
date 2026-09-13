"""A simulated PCR thermocycler: behaviour only. Its descriptor and operating
instructions live in the device package next to this file (thermocycler-01/)."""
from __future__ import annotations

import time
from pathlib import Path

from ..driver import Driver, InvalidValue, Job, LimitViolation, is_finite_number
from ..package import load_package
from . import sim_cell

PACKAGE = Path(__file__).parent / "thermocycler-01"
DESCRIPTOR = load_package(PACKAGE).descriptor
BLOCK_MIN, BLOCK_MAX = 4, 105


class SimThermocycler(Driver):
    package_dir = str(PACKAGE)

    def setup(self):
        self.block, self.lid, self.lid_closed, self.cycle = 22.0, 22.0, True, 0
        self.target, self.lid_heater = 22.0, False
        self.speed = 20.0                     # simulated degC per tick; keep demos fast
        sim_cell.register(self.descriptor["device"]["id"], self)

    def on_read(self, name):
        return {"block_temperature": round(self.block, 2), "lid_temperature": round(self.lid, 2),
                "lid_closed": self.lid_closed, "lid_cool": self.lid < 60, "cycle": self.cycle}[name]

    def on_write(self, name, value):
        if name == "target_temperature":
            self.target = float(value)
            self._ramp(self.target)
        elif name == "lid_heater":
            self.lid_heater = bool(value)
            self.lid = 105.0 if value else 22.0

    def validate_params(self, action: str, params: dict) -> None:
        """The whole program is checked before the first step runs, in dry runs too."""
        if action != "run_protocol":
            return
        steps = params.get("steps")
        if not isinstance(steps, list) or not steps:
            raise InvalidValue("run_protocol.steps must be a non-empty list")
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                raise InvalidValue(f"run_protocol.steps[{i}] must be an object with temp and hold_s")
            extra = set(step) - {"temp", "hold_s"}
            if extra:
                raise InvalidValue(f"run_protocol.steps[{i}]: unknown keys {sorted(extra)}")
            temp, hold = step.get("temp"), step.get("hold_s", 0)
            if not is_finite_number(temp):
                raise InvalidValue(f"run_protocol.steps[{i}].temp must be a finite number")
            if not BLOCK_MIN <= temp <= BLOCK_MAX:
                raise LimitViolation(f"run_protocol.steps[{i}].temp={temp} outside block limits {BLOCK_MIN}..{BLOCK_MAX}",
                                     {"min": BLOCK_MIN, "max": BLOCK_MAX})
            if not is_finite_number(hold) or not 0 <= hold <= 3600:
                raise LimitViolation(f"run_protocol.steps[{i}].hold_s={hold!r} outside 0..3600", {"min": 0, "max": 3600})
        cycles = params.get("cycles")
        if not isinstance(cycles, int) or isinstance(cycles, bool):
            raise InvalidValue("run_protocol.cycles must be an integer")

    def _ramp(self, target, job: Job | None = None):
        while abs(self.block - target) > 0.1:
            if job:
                self.checkpoint(job)
            self.block += max(-self.speed, min(self.speed, target - self.block))
            self.emit_signal("block_temperature", round(self.block, 2))
            time.sleep(0.05)
        self.block = target

    def on_invoke(self, job: Job):
        if job.action == "open_lid":
            self.lid_closed = False
            return {"lid_closed": False}
        if job.action == "close_lid":
            self.lid_closed = True
            return {"lid_closed": True}
        if job.action == "run_protocol":
            steps, cycles = job.params["steps"], job.params["cycles"]
            total, done = len(steps) * cycles, 0
            for c in range(1, cycles + 1):
                self.cycle = c
                for step in steps:
                    self.checkpoint(job)                          # honours pause and cancel
                    self._ramp(step["temp"], job)
                    time.sleep(min(step.get("hold_s", 0), 0.2))   # simulated hold
                    done += 1
                    self.progress(job, done / total, cycle=c, temp=step["temp"])
            self.cycle = 0
            return {"cycles_completed": cycles, "final_block_temperature": self.block}
        raise InvalidValue(f"unhandled action {job.action}")

    def on_estop(self):
        self.lid_heater, self.lid = False, 22.0
