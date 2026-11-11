"""Simulated twin of an 870 KF Titrino plus: a fake serial port answering the `plus` dialect with a Karl Fischer
cell model (drift that settles during conditioning, a titration that consumes titrant in proportion to the water
in the sample). Time is scaled by OPENMHP_SIM_TIME_SCALE (default 0.01)."""
from __future__ import annotations

import importlib.util
import os
import pathlib
import random
import sys
import time

_spec = importlib.util.spec_from_file_location(__name__ + "_real", pathlib.Path(__file__).with_name("driver.py"))
real = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = real
_spec.loader.exec_module(real)

METHODS = {"KF-STD": {"ppm": 1200.0}, "KF-SOLID": {"ppm": 5200.0}, "KF-OIL": {"ppm": 85.0}}
TITER_MG_ML = 5.0                          # mg water per mL titrant
TITRATION_RATE_ML_MIN = 0.6
COND_S = 120.0                             # conditioning to a stable drift takes about two minutes


class FakeTitrino:
    """write()/readline() like a pyserial port; one answer line per command."""
    is_open = True

    def __init__(self, scale: float):
        self.scale, self.log, self.online = scale, [], True
        self.state = "Cond"                   # the cell is being conditioned at power-up
        self.message = 0
        self.method = "KF-STD"
        self.sample_g = 0.5
        self.cond_until = time.monotonic() + COND_S * scale
        self.titr_until = 0.0
        self.last = {"R1": 0.0, "MCV": 0.0, "DD": 0.0, "C00": self.sample_g}
        self._answer = b""

    def _tick(self) -> None:
        now = time.monotonic()
        if self.state == "Busy" and now >= self.titr_until:
            ppm = METHODS[self.method]["ppm"] * random.gauss(1, 0.01)
            water_mg = ppm * self.sample_g / 1000
            self.last = {"R1": round(ppm, 1), "MCV": round(water_mg / TITER_MG_ML, 4),
                         "DD": round((self.titr_until - self.titr_at) / self.scale, 1), "C00": self.sample_g}
            self.state = "Cond"
            self.cond_until = now + 60 * self.scale

    def write(self, data: bytes) -> None:
        cmd = data.decode("ascii", errors="replace").strip()
        self.log.append(cmd)
        self._tick()
        if cmd == "$G":
            if self.state == "Busy":
                self._answer = b"OK\r\n"
                return
            if self.state in ("Ready", "Hold"):           # start from Ready begins conditioning of the cell
                self.state = "Cond"
                self.cond_until = time.monotonic() + COND_S * self.scale
                self._answer = b"OK\r\n"
                return
            self.state = "Busy"
            self.titr_at = time.monotonic()
            water_mg = METHODS[self.method]["ppm"] * self.sample_g / 1000
            self.titr_until = self.titr_at + (30 + water_mg / TITER_MG_ML / TITRATION_RATE_ML_MIN * 60) * self.scale
            self._answer = b"OK\r\n"
        elif cmd == "$S":
            self.state = "Ready"
            self._answer = b"OK\r\n"
        elif cmd == "$H":
            self.state = "Hold"
            self._answer = b"OK\r\n"
        elif cmd == "$D":
            # while the drift is still being titrated down the instrument is Busy; Cond once the endpoint holds
            word = "Busy" if self.state == "Cond" and time.monotonic() < self.cond_until else self.state
            self._answer = f"{word};{self.message}\r\n".encode()
        elif cmd.startswith("$L(") and cmd.endswith(")"):
            name = cmd[3:-1]
            if name in METHODS:
                self.method = name
                self._answer = b"OK\r\n"
            else:
                self._answer = b"E1\r\n"
        elif cmd.startswith("$Q(") and cmd.endswith(")"):
            var = cmd[3:-1]
            self._answer = (f"{self.last[var]}\r\n".encode() if var in self.last else b"E2\r\n")
        else:
            self._answer = b"E3\r\n"

    def readline(self) -> bytes:
        a, self._answer = self._answer, b""
        return a

    def reset_input_buffer(self) -> None: pass
    def close(self) -> None: pass


class SimLink(real.TitrinoLink):
    def __init__(self, cfg, scale):
        super().__init__(cfg)
        self.port = FakeTitrino(scale)

    def open(self) -> None:
        if not self.port.online:
            raise real.DeviceFault("twin offline", {"transient": True})


class Sim(real.Device):
    def setup(self) -> None:
        super().setup()
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        self.cfg = {"port": "SIM", "dialect": "plus", "baud": 19200, "timeout_s": 2, "titer_mg_ml": TITER_MG_ML}

    def time_scale(self) -> float:
        return self.scale

    def make_link(self):
        return SimLink(self.cfg, self.scale)
