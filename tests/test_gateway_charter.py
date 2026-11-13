"""Run charters: the format, its English summary, and how the gateway enforces it on every request a
run makes with its run token.

    PYTHONPATH=. python tests/test_gateway_charter.py
"""
import copy
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")
os.environ["OPENMHP_HOME"] = tempfile.mkdtemp(prefix="openmhp-charter-")
os.environ["OPENMHP_NO_UPDATE_CHECK"] = "1"

from openmhp import charter as C                                            # noqa: E402

CHARTER = {
    "version": 1, "run": "R-2611-0042", "owner": "alice",
    "objective": "Best capacity retention after 50 cycles over salt concentration and additive",
    "autonomy": "act",
    "instruments": {"tc": "bench/thermocycler-01", "ob1": "bench/ob1-01"},
    "envelope": {
        "tc": {"actions": {"run_protocol": {"cycles": {"min": 1, "max": 40}}, "open_lid": {}, "close_lid": {}},
               "settings": {"target_temperature": {"min": 4, "max": 99}, "lid_heater": {"in": [True, False]}}},
        "ob1": {"actions": {"vent": {}}, "settings": {"pressure_setpoint_ch1": {"min": 0, "max": 300}}},
    },
    "consumables": {"buffer_ml": {"limit": 1.0, "uses": [{"instrument": "tc", "action": "run_protocol",
                                                          "param": "cycles", "scale": 0.1}]}},
    "budgets": {"experiments": 3, "count": {"instrument": "tc", "action": "run_protocol"},
                "deadline": "2099-01-01T00:00:00"},
    "standing_approvals": [{"instrument": "tc", "action": "open_lid", "uses": 2}],
    "always_ask": [{"instrument": "ob1", "action": "vent"}],
    "stop_conditions": ["retention above 95 %"],
    "cleanup": "lid closed, block at 4 C",
}


class raises:
    def __init__(self, exc):
        self.exc, self.value = exc, None
    def __enter__(self):
        return self
    def __exit__(self, et, ev, tb):
        assert et is not None and issubclass(et, self.exc), f"expected {self.exc.__name__}, got {et}: {ev}"
        self.value = ev
        return True


def test_charter_format_digest_and_summary():
    assert C.problems(CHARTER) == []
    d = C.digest(CHARTER)
    assert d.startswith("sha256:") and C.digest(copy.deepcopy(CHARTER)) == d
    assert C.digest({**CHARTER, "approved_by": "alice", "approved_at": "now"}) == d        # approval records are not content
    widened = copy.deepcopy(CHARTER)
    widened["envelope"]["tc"]["settings"]["target_temperature"]["max"] = 105
    assert C.digest(widened) != d

    bad = copy.deepcopy(CHARTER)
    del bad["objective"]
    bad["autonomy"] = "yolo"
    bad["instruments"]["x"] = "no-slash"
    bad["envelope"]["ghost"] = {"actions": {}}
    bad["envelope"]["tc"]["settings"]["target_temperature"] = {"min": 50, "max": 10}
    bad["envelope"]["tc"]["actions"]["run_protocol"]["cycles"] = {"lo": 1}
    bad["budgets"]["deadline"] = "Friday"
    bad["consumables"]["buffer_ml"]["uses"][0]["instrument"] = "ghost"
    bad["standing_approvals"].append({"instrument": "ghost"})
    found = " | ".join(C.problems(bad))
    for words in ("missing 'objective'", "autonomy", "instruments.x", "envelope.ghost", "min is above max",
                  "unknown bound 'lo'", "budgets.deadline", "consumables.buffer_ml", "standing_approvals[1]"):
        assert words in found, (words, found)

    text = C.summary(CHARTER)
    for words in ("R-2611-0042", "tc: run run_protocol (cycles 1 to 40)", "tc: set target_temperature to 4 to 99",
                  "at most 3 experiments", "buffer_ml: at most 1.0", "Approved in advance", "tc: open_lid, at most 2 times",
                  "Always asks you first", "ob1: vent", "retention above 95 %", d):
        assert words in text, (words, text)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok ", name)
