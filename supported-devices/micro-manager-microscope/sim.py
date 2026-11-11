"""Simulated twin of a Micro-Manager microscope in the shape of MMConfig_demo.cfg: a DemoCamera-like 16-bit camera,
an XY stage and a Z stage that take time to move (scaled by OPENMHP_SIM_TIME_SCALE), and a 'Channel' config group
with DAPI, FITC, Rhodamine and Cy5. Images are synthetic beads that blur away from focus. No pymmcore, no numpy."""
from __future__ import annotations

import importlib.util
import math
import os
import pathlib
import random
import sys
import time

_spec = importlib.util.spec_from_file_location(__name__ + "_real", pathlib.Path(__file__).with_name("driver.py"))
real = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = real
_spec.loader.exec_module(real)

W = H = 256
CHANNELS = {"DAPI": 0.6, "FITC": 1.0, "Rhodamine": 0.8, "Cy5": 0.4}
Z_FOCUS, STAGE_UM_PER_S = 0.0, 5000.0
BEADS = [(60, 70, 6.0), (150, 40, 4.0), (200, 180, 8.0), (90, 200, 5.0), (128, 128, 3.0)]


class SimBackend:
    def __init__(self, scale: float):
        self.scale = scale
        self.log: list[str] = []
        self.exp_ms, self.x, self.y, self.z_pos, self.channel = 10.0, 0.0, 0.0, 0.0, "DAPI"
        self.moving_until = 0.0

    def open(self):
        self.log.append("loadSystemConfiguration demo")

    def close(self):
        self.log.append("unloadAllDevices")

    def camera(self):
        return "Camera"

    def exposure(self):
        return self.exp_ms

    def set_exposure(self, ms):
        self.log.append(f"setExposure {ms}")
        self.exp_ms = float(ms)

    def xy(self):
        return self.x, self.y

    def _travel(self, distance: float):
        t = distance / STAGE_UM_PER_S * self.scale
        self.moving_until = time.monotonic() + t
        time.sleep(t)

    def move_xy(self, x, y):
        self.log.append(f"setXYPosition {x} {y}")
        self._travel(math.hypot(x - self.x, y - self.y))
        self.x, self.y = float(x), float(y)

    def z(self):
        return self.z_pos

    def move_z(self, z):
        self.log.append(f"setPosition {z}")
        self._travel(abs(z - self.z_pos))
        self.z_pos = float(z)

    def configs(self, group):
        return list(CHANNELS) if group == "Channel" else []

    def current_config(self, group):
        return self.channel if group == "Channel" else None

    def set_config(self, group, preset):
        self.log.append(f"setConfig {group} {preset}")
        self.channel = preset

    def snap(self):
        time.sleep(self.exp_ms / 1000 * self.scale)
        self.log.append("snapImage")
        gain = CHANNELS[self.channel] * self.exp_ms / 10.0
        blur = 1.0 + abs(self.z_pos - Z_FOCUS) / 2.0
        buf = bytearray(W * H * 2)
        for j in range(H):
            for i in range(W):
                v = 300.0 + random.gauss(0, 12)
                for bx, by, r in BEADS:
                    d2 = (i - bx) ** 2 + (j - by) ** 2
                    s2 = (r * blur) ** 2
                    if d2 < 9 * s2:
                        v += 20000.0 * gain / blur * math.exp(-d2 / (2 * s2))
                n = int(min(65535, max(0, v)))
                k = 2 * (j * W + i)
                buf[k], buf[k + 1] = n & 0xFF, n >> 8
        return W, H, 2, bytes(buf)

    def stop(self):
        self.log.append("stop XY; stop Z")
        self.moving_until = 0.0


class SimMicroManagerMicroscope(real.MicroManagerMicroscope):
    def setup(self) -> None:
        super().setup()
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        home = pathlib.Path(os.environ.get("OPENMHP_HOME", pathlib.Path.home() / ".openmhp"))
        self.cfg = {"config_file": "demo", "channel_group": "Channel", "soft_limits_um": {"x": [-10000, 10000], "y": [-10000, 10000], "z": [-500, 500]},
                    "data_dir": str(home / "sim-data" / "micro-manager-microscope")}
        self.group = "Channel"

    def time_scale(self) -> float:
        return self.scale

    def make_backend(self):
        self.link = SimBackend(self.scale)
        return self.link
