"""Quantos / XPR powder dosing over MT-SICS: the declarative serial driver plus one thing its grammar cannot
say. The `dose` action's result must carry the dispensed mass as a number (dispenser class convention), so
the last reply (the placeholder QDR result line) is parsed for its first number and returned beside the
replies list; a reply with no number (ES on a balance that lacks the command) gives null."""
from __future__ import annotations

import re

from openmhp.driver import Job
from openmhp.drivers.serial_ascii import SerialAsciiDriver

_NUM = re.compile(r"[-+]?\d+(?:\.\d+)?")


class Device(SerialAsciiDriver):
    def on_invoke(self, job: Job):
        result = super().on_invoke(job)
        if job.action == "dose":
            last = result["replies"][-1] if result.get("replies") else ""
            m = _NUM.search(last[3:]) if last.startswith("QDR") else None
            result["dispensed_mg"] = float(m.group()) if m else None
        return result
