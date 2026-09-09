"""A simulated 6-axis plate-handling robot arm: behaviour only. Descriptor and
instructions live in the device package next to this file (arm-01/)."""
from __future__ import annotations

import math
import time
from pathlib import Path

from ..driver import Driver, Job
from ..package import load_package

PACKAGE = Path(__file__).parent / "arm-01"
DESCRIPTOR = load_package(PACKAGE).descriptor


class SimArm(Driver):
    package_dir = str(PACKAGE)

    def setup(self):
        self.pos = {"x": 0.0, "y": 0.0, "z": 400.0}
        self.gripper_closed = self.holding = False
        self.safe = True
        self.homed = False
        self.speed, self.force = 50.0, 15.0

    def on_read(self, name):
        return {"position": self.pos, "gripper_closed": self.gripper_closed, "holding_plate": self.holding,
                "safe_zone_clear": self.safe, "homed": self.homed}[name]

    def on_write(self, name, value):
        setattr(self, {"speed": "speed", "gripper_force": "force"}[name], float(value))

    def _goto(self, job: Job, target: dict):
        if math.dist(target.values(), (0, 0, 0)) > self.descriptor["physical"]["reach_mm"] + 100:
            raise ValueError("target outside reach envelope")
        start, steps = dict(self.pos), 10
        for i in range(1, steps + 1):
            if job.cancel_requested or not self.safe:
                raise RuntimeError("motion aborted: cancel or interlock")
            f = i / steps
            self.pos = {k: round(start[k] + (target[k] - start[k]) * f, 1) for k in start}
            self.emit_signal("position", self.pos)
            self.progress(job, f)
            time.sleep(0.02 * (100 / self.speed))

    def on_invoke(self, job: Job):
        a, p = job.action, job.params
        if a == "home":
            self._goto(job, {"x": 0.0, "y": 0.0, "z": 400.0}); self.homed = True
            return {"homed": True}
        if not self.homed:
            raise RuntimeError("arm not homed; invoke 'home' first")
        if a == "move_to":
            self._goto(job, {k: float(p[k]) for k in ("x", "y", "z")})
            return {"position": self.pos}
        loc = self.descriptor["locations"].get(p.get("location"))
        if loc is None:
            raise ValueError(f"unknown location {p.get('location')!r}")
        x, y, z = loc
        if a == "pick_plate":
            if self.holding:
                raise RuntimeError("already holding a plate")
            self._goto(job, {"x": x, "y": y, "z": z + 60}); self._goto(job, {"x": x, "y": y, "z": z})
            self.gripper_closed = self.holding = True
            self._goto(job, {"x": x, "y": y, "z": z + 60})
            return {"holding_plate": True, "from": p["location"]}
        if a == "place_plate":
            if not self.holding:
                raise RuntimeError("no plate in gripper")
            self._goto(job, {"x": x, "y": y, "z": z + 60}); self._goto(job, {"x": x, "y": y, "z": z})
            self.gripper_closed = self.holding = False
            self._goto(job, {"x": x, "y": y, "z": z + 60})
            return {"holding_plate": False, "to": p["location"]}
        raise ValueError(f"unhandled action {a}")

    def on_estop(self):
        pass  # brakes engage; gripper state retained (see safety.notes)
