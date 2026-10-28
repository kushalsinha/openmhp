"""Simulated twin of the FloPro Sampler: a fake FloZF running the mhp_server sequence against the real protocol."""
from __future__ import annotations

import importlib.util
import os
import pathlib
import sys
import threading
import time

_spec = importlib.util.spec_from_file_location(__name__ + "_real", pathlib.Path(__file__).with_name("driver.py"))
real = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = real
_spec.loader.exec_module(real)

SEQUENCE_S = 360          # a FloPro sampling sequence takes 5-8 minutes
CHECK_EVERY_S = 30        # CHECK steps the owner places between fluidic steps


class FakeFloZF:
    """Runs the mhp_server loop from references/flozf_server_sequence.md, calling the driver's protocol."""

    def __init__(self, cfg, handle, scale):
        self.cfg, self.handle, self.scale = cfg, handle, scale
        self.log: list[str] = []

    def open(self):
        threading.Thread(target=self._server, daemon=True).start()

    def _ask(self, line):
        reply = self.handle(line)
        self.log.append(f"{line} -> {reply}")
        return reply

    def _server(self):
        """FloZF aborts a sequence when a serial step gets no answer (manual 1.4.8) and runs its stop sequence."""
        run = 1
        while run == 1:
            reply = self._ask("POLL")
            if reply is None:
                return self._abort()
            job = float(reply)
            if job == -1:
                run = 0
            elif job > 0:
                if job != 9:
                    for k in ("probe", "dil1", "dil2", "vial"):
                        if self._ask(f"GET {k}") is None:
                            return self._abort()
                for _ in range(SEQUENCE_S // CHECK_EVERY_S):    # the owner's sequence with CHECK steps between fluidic steps
                    time.sleep(CHECK_EVERY_S * self.scale)
                    if self._ask("CHECK") is None:
                        return self._abort()
                self._ask("DONE")
            time.sleep(float(self.cfg.get("poll_s", 2)) * self.scale)

    def _abort(self):
        self.log.append("ABORTED: no answer; stop sequence ran (pumps off)")


class SimFloProSampler(real.FloProSampler):
    def setup(self) -> None:
        super().setup()
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        self.cfg = {"port": "SIM", "poll_s": 2, "sequence_codes": {"archive": 1, "inject": 2, "detector": 3, "rinse": 9},
                    "pickup_timeout_s": 60, "sequence_timeout_s": 900}

    def time_scale(self) -> float:
        return self.scale

    def make_transport(self):
        return FakeFloZF(self.cfg, self.handle_line, self.scale)
