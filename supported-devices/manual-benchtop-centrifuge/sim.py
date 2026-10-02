"""Simulated twin: a simulated operator who balances tubes, runs the spin at the requested speed and
reports back at once. The real package waits for a person to acknowledge each step."""
import time

from openmhp.drivers.manual import ManualDriver


class Sim(ManualDriver):
    def setup(self):
        super().setup()
        now = time.time()
        self.observed.update({"balanced": (True, now), "door_open": (False, now), "actual_speed": (0, now)})

    def on_invoke(self, job):
        if job.action == "spin":
            speed = self.requested.get("speed", (0, 0))[0]
            self.observed["actual_speed"] = (speed, time.time())
            return {"spun": True, "at_rpm": speed, "completed_by": "simulated operator"}
        return super().on_invoke(job)
