"""Tecan Cavro XLP 6000 / XCalibur over RS-232 (DT protocol).

Two things the declarative serial driver cannot express: a volume in microlitres must become plunger
increments from the syringe size in config.json (`syringe_ul`, `steps_full_stroke`), and a move is only
done when the pump's Q report says ready. Both live here; the frames stay in descriptor.yaml.
"""
import re
import time

from openmhp.driver import LimitViolation
from openmhp.drivers.serial_ascii import SerialAsciiDriver

_BUSY = re.compile(r"^/0[@A-O]")                   # status byte 0x40-0x4F (bit 5 clear): busy


class Device(SerialAsciiDriver):
    def _with_steps(self, params: dict) -> dict:
        if "volume_ul" not in params:
            return params
        cfg = self.config()
        full = int(cfg.get("steps_full_stroke", 6000))
        steps = int(round(float(params["volume_ul"]) * full / float(cfg.get("syringe_ul", 1000))))
        if steps > full:
            raise LimitViolation(f"volume_ul={params['volume_ul']} is {steps} increments, more than the "
                                 f"{full}-increment stroke of the configured {cfg.get('syringe_ul', 1000)} uL syringe")
        return {**params, "steps": steps}

    def validate_params(self, action: str, params: dict) -> None:
        super().validate_params(action, self._with_steps(params))

    def on_invoke(self, job):
        job.params = self._with_steps(job.params)
        out = super().on_invoke(job)
        while _BUSY.match(self.query("/1Q")):
            self.checkpoint(job)
            time.sleep(0.2)
        return out
