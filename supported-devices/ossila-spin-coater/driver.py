"""Ossila Spin Coater over a USB serial placeholder protocol: the declarative driver plus what its grammar
cannot say. `run_recipe` unrolls the typed steps into one write per step before the select and start
commands, and `robot_access_ready` is derived from the lid and speed readings. Every frame is a placeholder
(template package); the shapes live here so they stay once Ossila's command set is known."""
from __future__ import annotations

from openmhp.driver import InvalidValue, Job
from openmhp.drivers.serial_ascii import SerialAsciiDriver

MAX_STEPS = 50
STEP_FRAME = "STEP {slot} {n} {speed} {acc} {dur}"           # placeholder, unverified


class Device(SerialAsciiDriver):
    def on_read(self, name):
        if name == "robot_access_ready":
            lid = self._parse("lid_closed", self.query(self.cfg["read"]["lid_closed"]))
            speed = self._parse("speed_rpm", self.query(self.cfg["read"]["speed_rpm"]))
            return (not lid) and speed == 0
        return super().on_read(name)

    def validate_params(self, action: str, params: dict) -> None:
        super().validate_params(action, params)
        if action == "run_recipe":
            steps = params.get("steps") or []
            if not steps:
                raise InvalidValue("run_recipe: steps must hold at least one step")
            if len(steps) > MAX_STEPS:
                raise InvalidValue(f"run_recipe: {len(steps)} steps; the unit stores {MAX_STEPS} per program")
            for i, s in enumerate(steps):
                if 0 < float(s["speed_rpm"]) < 120:
                    raise InvalidValue(f"run_recipe: step {i + 1} asks {s['speed_rpm']} rpm; the L2001A3 holds 120 rpm or more (0 stops the chuck)")

    def on_invoke(self, job: Job):
        if job.action != "run_recipe":
            return super().on_invoke(job)
        slot = int(job.params["slot"])
        frames = [STEP_FRAME.format(slot=slot, n=i + 1, speed=int(round(s["speed_rpm"])), acc=int(round(s["acceleration_rpm_s"])),
                                    dur=int(round(s["duration_s"]))) for i, s in enumerate(job.params["steps"])]
        frames += [f"PRG {slot}", *self.cfg["actions"]["run_recipe"]]
        replies = []
        for i, c in enumerate(frames):
            self.checkpoint(job, i / len(frames))
            replies.append(self.query(c))
        self.progress(job, 1.0)
        return {"replies": replies}
