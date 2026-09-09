"""A simulated PCR thermocycler: behaviour only. Its descriptor and operating
instructions live in the device package next to this file (thermocycler-01/)."""
from __future__ import annotations

import time
from pathlib import Path

from ..driver import Driver, Job
from ..package import load_package

PACKAGE = Path(__file__).parent / "thermocycler-01"
DESCRIPTOR = load_package(PACKAGE).descriptor


class SimThermocycler(Driver):
    package_dir = str(PACKAGE)

    def setup(self):
        self.block, self.lid, self.lid_closed, self.cycle = 22.0, 22.0, True, 0
        self.target, self.lid_heater = 22.0, False
        self.speed = 20.0                     # simulated degC per tick; keep demos fast

    def on_read(self, name):
        return {"block_temperature": round(self.block, 2), "lid_temperature": round(self.lid, 2),
                "lid_closed": self.lid_closed, "cycle": self.cycle}[name]

    def on_write(self, name, value):
        if name == "target_temperature":
            self.target = float(value)
            self._ramp(self.target)
        elif name == "lid_heater":
            self.lid_heater = bool(value)
            self.lid = 105.0 if value else 22.0

    def _ramp(self, target, job: Job | None = None):
        while abs(self.block - target) > 0.1:
            if job and job.cancel_requested:
                return
            self.block += max(-self.speed, min(self.speed, target - self.block))
            self.emit_signal("block_temperature", round(self.block, 2))
            time.sleep(0.05)
        self.block = target

    def on_invoke(self, job: Job):
        if job.action == "open_lid":
            self.lid_closed = False
            return {"lid_closed": False}
        if job.action == "run_protocol":
            steps, cycles = job.params.get("steps", []), int(job.params.get("cycles", 1))
            total = max(1, len(steps) * cycles)
            done = 0
            for c in range(1, cycles + 1):
                self.cycle = c
                for step in steps:
                    if job.cancel_requested:
                        return {"cycles_completed": c - 1, "cancelled": True}
                    if not (4 <= step["temp"] <= 105):   # defence in depth: params obey limits too
                        raise ValueError(f"step temp {step['temp']} outside block limits")
                    self._ramp(step["temp"], job)
                    time.sleep(min(step.get("hold_s", 0), 0.2))   # simulated hold
                    done += 1
                    self.progress(job, done / total, cycle=c, temp=step["temp"])
            self.cycle = 0
            return {"cycles_completed": cycles, "final_block_temperature": self.block}

    def on_estop(self):
        self.lid_heater, self.lid = False, 22.0
