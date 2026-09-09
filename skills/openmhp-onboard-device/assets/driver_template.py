"""MHP driver template. Vendor code lives only in the five hooks below."""
from __future__ import annotations

import json
import pathlib

from openmhp.driver import Driver, Job

DESCRIPTOR = json.loads(pathlib.Path(__file__).with_suffix(".json").read_text()) \
    if pathlib.Path(__file__).with_suffix(".json").exists() else {
        # or inline the descriptor here
    }


class MyDevice(Driver):
    descriptor = DESCRIPTOR

    def setup(self) -> None:
        """Open the serial port / SDK session. Called once."""
        # self.dev = serial.Serial("/dev/ttyUSB0", 9600, timeout=1)

    def on_read(self, name: str):
        """Return the current value of a signal (or a readable setting)."""
        raise NotImplementedError(name)

    def on_write(self, name: str, value) -> None:
        """Apply a setting. Limits and approval were already checked by the base class."""
        raise NotImplementedError(name)

    def on_invoke(self, job: Job):
        """Run an action synchronously (a worker thread calls this). Validate params against
        physical limits, report progress, honour cancellation, return a JSON-able result."""
        if job.action == "example_run":
            minutes = float(job.params["minutes"])
            if not 1 <= minutes <= 600:
                raise ValueError("minutes outside 1..600")
            for i in range(10):
                if job.cancel_requested:
                    return {"cancelled": True}
                self.progress(job, (i + 1) / 10)
            return {"ok": True}
        raise ValueError(f"unhandled action {job.action}")

    def on_estop(self) -> None:
        """Cut motion / energy as fast as the hardware allows. Must not raise."""
