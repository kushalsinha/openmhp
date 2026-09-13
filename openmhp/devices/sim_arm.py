"""A simulated 6-axis plate-handling robot arm: behaviour only. Descriptor and
instructions live in the device package next to this file (arm-01/).

Handoff locations (``handoffs`` in the descriptor) are bound to another device.
Before moving into one, the simulator checks that device's state through the
shared simulator cell, and refuses to load or unload through a closed lid or
into an instrument it cannot see."""
from __future__ import annotations

import math
import time
from pathlib import Path

from ..driver import Driver, InvalidValue, Job, LimitViolation
from ..package import load_package
from . import sim_cell

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
        sim_cell.register(self.descriptor["device"]["id"], self)

    def on_read(self, name):
        return {"position": self.pos, "gripper_closed": self.gripper_closed, "holding_plate": self.holding,
                "safe_zone_clear": self.safe, "homed": self.homed}[name]

    def on_write(self, name, value):
        setattr(self, {"speed": "speed", "gripper_force": "force"}[name], float(value))

    def _coords(self, location: str) -> tuple[float, float, float]:
        loc = self.descriptor.get("locations", {}).get(location)
        if loc is None:
            raise InvalidValue(f"unknown location {location!r}")
        x, y, z = loc["xyz"] if isinstance(loc, dict) else loc
        return float(x), float(y), float(z)

    def validate_params(self, action: str, params: dict) -> None:
        if action == "move_to":
            reach = self.descriptor["physical"]["reach_mm"] + 100
            if math.dist((params["x"], params["y"], params["z"]), (0, 0, 0)) > reach:
                raise LimitViolation(f"move_to target outside the reach envelope ({reach} mm)", {"max": reach})
        if action in ("pick_plate", "place_plate"):
            self._coords(params.get("location"))

    def _check_handoff(self, location: str) -> None:
        device_id = (self.descriptor.get("handoffs") or {}).get(location)
        if not device_id:
            return
        other = sim_cell.get(device_id)
        if other is None:
            raise RuntimeError(f"'{location}' belongs to {device_id}, which this simulator cannot see; refusing to move blind")
        if getattr(other, "lid_closed", False):
            raise RuntimeError(f"{device_id} lid is closed; open it before loading or unloading at '{location}'")

    def _goto(self, job: Job, target: dict):
        start, steps = dict(self.pos), 10
        for i in range(1, steps + 1):
            if not self.safe:
                raise RuntimeError("motion aborted: light curtain interlock opened")
            self.checkpoint(job)
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
        x, y, z = self._coords(p["location"])
        if a == "pick_plate":
            if self.holding:
                raise RuntimeError("already holding a plate")
            self._check_handoff(p["location"])
            self._goto(job, {"x": x, "y": y, "z": z + 60}); self._goto(job, {"x": x, "y": y, "z": z})
            self.gripper_closed = self.holding = True
            self._goto(job, {"x": x, "y": y, "z": z + 60})
            return {"holding_plate": True, "from": p["location"]}
        if a == "place_plate":
            if not self.holding:
                raise RuntimeError("no plate in gripper")
            self._check_handoff(p["location"])
            self._goto(job, {"x": x, "y": y, "z": z + 60}); self._goto(job, {"x": x, "y": y, "z": z})
            self.gripper_closed = self.holding = False
            self._goto(job, {"x": x, "y": y, "z": z + 60})
            return {"holding_plate": False, "to": p["location"]}
        raise InvalidValue(f"unhandled action {a}")

    def on_estop(self):
        pass  # brakes engage; gripper state retained (see safety.notes)
