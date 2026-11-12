"""Simulated twin of a ZEISS SEM: a fake SmartSEM Remote API object with a 240 s pump, 120 s vent, 20 s EHT
run-up, a five-axis stage that takes time to arrive, and grabs that write real 8-bit TIFFs. Time scaled by
OPENMHP_SIM_TIME_SCALE."""
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

PUMP_S, VENT_S, RUNUP_S = 240, 120, 20
N = real.DEFAULT_NAMES


class SmartSemError(Exception):
    """What the COM object raises; the driver turns it into a DeviceFault at the backend boundary."""


class FakeSmartSEM:
    """The SmartSEM Remote API surface this package uses, answered by a scaled clock."""

    def __init__(self, scale: float, log: list):
        self.scale, self.log = scale, log
        self.vac, self.vac_next, self.vac_until = "At atmosphere", None, 0.0
        self.eht, self.eht_until, self.kv, self.manual_kv = False, 0.0, 0.0, 10.0
        self.pos, self.target, self.stage_until = [0.0, 0.0, 20.0, 0.0, 0.0], None, 0.0
        self.mag, self.scan_rate, self.detector = 1000.0, 5, "SE2"
        self.frozen = False

    def _tick(self):
        now = time.monotonic()
        if self.vac_next is not None and now >= self.vac_until:
            self.vac, self.vac_next = self.vac_next, None
        if self.target and now >= self.stage_until:
            self.pos, self.target = self.target, None

    def InitialiseRemoting(self):
        self.log.append("InitialiseRemoting")
        return 0

    def ClosingControl(self):
        self.log.append("ClosingControl")

    def Get(self, param):
        self._tick()
        if param == N["vac_status"]:
            return self.vac
        if param == N["runup_state"]:
            return "On" if self.eht and time.monotonic() >= self.eht_until else ("Run up" if self.eht else "Off")
        if param == N["actual_kv"]:
            return self.kv if self.eht else 0.0
        if param == N["stage_is"]:
            return "Busy" if self.target is not None else "Idle"
        axes = {N["stage_x"]: 0, N["stage_y"]: 1, N["stage_z"]: 2, N["stage_r"]: 3, N["stage_t"]: 4}
        if param in axes:
            return self.pos[axes[param]]
        if param == N["mag"]:
            return self.mag
        raise SmartSemError(f"unknown parameter {param}")

    def Set(self, param, value):
        self.log.append(f"Set {param} {value}")
        if param == N["manual_kv"]:
            self.manual_kv = float(value)
            if self.eht:
                self.kv = self.manual_kv
        elif param == N["mag"]:
            self.mag = max(5.0, min(1e6, float(value)))
        elif param == N["scan_rate"]:
            self.scan_rate = int(value)
        elif param == N["detector"]:
            self.detector = str(value)
        else:
            raise SmartSemError(f"unknown parameter {param}")

    def Execute(self, cmd):
        self.log.append(f"Execute {cmd}")
        self._tick()
        if cmd == N["cmd_pump"]:
            self.vac, self.vac_next, self.vac_until = "Pumping", "Ready", time.monotonic() + PUMP_S * self.scale
        elif cmd == N["cmd_vent"]:
            if self.eht:
                raise SmartSemError("cannot vent with the EHT on")
            self.vac, self.vac_next, self.vac_until = "Venting", "At atmosphere", time.monotonic() + VENT_S * self.scale
        elif cmd == N["cmd_eht_on"]:
            if self.vac != "Ready":
                raise SmartSemError("vacuum not ready")
            self.eht, self.kv, self.eht_until = True, self.manual_kv, time.monotonic() + RUNUP_S * self.scale
        elif cmd == N["cmd_eht_off"]:
            self.eht = False
        elif cmd == N["cmd_stage_stop"]:
            if self.target:
                self.pos, self.target = self.target, None
        elif cmd == N["cmd_auto_focus"]:
            time.sleep(min(0.2, 6 * self.scale))
        elif cmd == N["cmd_freeze"]:
            self.frozen = True
        else:
            raise SmartSemError(f"unknown command {cmd}")

    def MoveStage(self, x, y, z, t, r, m):
        self.log.append(f"MoveStage {x:.3f} {y:.3f} {z:.3f} {t:.2f} {r:.2f}")
        dist = max(abs(x - self.pos[0]), abs(y - self.pos[1]), abs(z - self.pos[2]))
        self.target = [float(x), float(y), float(z), float(r), float(t)]
        self.stage_until = time.monotonic() + (2 + dist / 5) * self.scale

    def Grab(self, x, y, w, h, reduction, filename):
        if not (self.eht and time.monotonic() >= self.eht_until):
            raise SmartSemError("EHT is off")
        self.log.append(f"Grab {w}x{h} {pathlib.Path(filename).name}")
        self.frozen = False
        time.sleep(min(0.5, w * h * self.scan_rate * 0.2e-6 * self.scale))
        rnd = random.Random(int(self.pos[0] * 1000 + self.pos[1]) + len(self.detector))
        real.write_tiff(filename, w, h, rnd.randbytes(w * h))


class SimBackend(real.ZeissBackend):
    def __init__(self, cfg, scale):
        super().__init__(cfg)
        self.scale, self.log = scale, []

    def open(self):
        self.api = FakeSmartSEM(self.scale, self.log)
        self.api.InitialiseRemoting()


class SimZeissSEM(real.ZeissSEM):
    def setup(self) -> None:
        super().setup()
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        self.cfg = {"image_dir": "", "pump_timeout_s": 900}

    def time_scale(self) -> float:
        return self.scale

    def make_backend(self):
        return SimBackend(self.cfg, self.scale)
