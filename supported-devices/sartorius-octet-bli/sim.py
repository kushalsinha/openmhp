"""Simulated twin of the Octet: a scripted automation interface (the same command lines, the documented
status words) with a run clock per method and an experiment folder path. Time scaled by OPENMHP_SIM_TIME_SCALE."""
from __future__ import annotations

import importlib.util
import os
import pathlib
import re
import sys
import time

_spec = importlib.util.spec_from_file_location(__name__ + "_real", pathlib.Path(__file__).with_name("driver.py"))
real = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = real
_spec.loader.exec_module(real)

METHODS = {"mAb_kinetics_ProA.fmf": {"duration": 3600, "trays": 1, "wells": 96},
           "IgG_quant_ProA.fmf": {"duration": 1500, "trays": 1, "wells": 96},
           "epitope_binning_AHC.fmf": {"duration": 7200, "trays": 2, "wells": 96}}


class SimBackend(real.OctetBackend):
    """Answers the command protocol in software; the socket is never opened."""

    def __init__(self, cfg, scale):
        super().__init__(cfg)
        self.scale, self.log = scale, []
        self.run_until, self.move_until, self.experiment = 0.0, 0.0, None
        self.stopped, self.temp = False, 25

    def open(self):
        self.log.append("connect")

    def _running(self):
        return self.experiment is not None and time.monotonic() < self.run_until and not self.stopped

    def command(self, text, timeout=30):
        self.log.append(text)
        word = text.split()[0]
        if word == "Version":
            return "12.2.0.1 Octet 1.1"
        if word == "Status":
            if time.monotonic() < self.move_until:
                return "Busy"
            if self.stopped:
                return "Stopped"
            if self._running():
                frac = 1 - (self.run_until - time.monotonic()) / (self.spec["duration"] * self.scale)
                return f"Running ({int(100 * frac)}%)"
            return "OK"
        if word == "GetMethodInfo":
            name = pathlib.PureWindowsPath(re.search(r'-m"([^"]*)"', text).group(1)).name
            spec = METHODS.get(name)
            if not spec:
                return "Error: bad method"
            return f"OK -p{spec['wells']},{spec['wells']} -t{spec['trays']} -sProA -eKinetics -r0"
        if word == "Run":
            if self._running() or time.monotonic() < self.move_until:
                return "Error: not ready"
            name = pathlib.PureWindowsPath(re.search(r'-m"([^"]*)"', text).group(1)).name
            self.spec = METHODS.get(name)
            if not self.spec:
                return "Error: bad method"
            plate = re.search(r'-1"([^"]*)"', text).group(1)
            self.experiment = f"{plate}_{name[:-4]}_{time.strftime('%Y%m%d_%H%M%S')}"
            self.stopped = False
            self.run_until = time.monotonic() + self.spec["duration"] * self.scale
            return "OK"
        if word == "GetRunInfo":
            return f'OK -n"{self.experiment}" -p"\\\\octet-pc\\Data\\{self.experiment}"'
        if word == "Stop":
            if self._running():
                self.stopped = True
            self.run_until = 0.0
            return "OK"
        if word in ("Present", "Close"):
            self.move_until = time.monotonic() + 8 * self.scale
            return "OK"
        if word == "Resume":
            return "OK"
        if word == "SetValue":
            self.temp = int(text.split("-t")[1])
            return "OK"
        if word == "Reset":
            self.experiment, self.stopped = None, False
            return "OK"
        return "Error: unknown command"


class SimOctetBLI(real.OctetBLI):
    def setup(self) -> None:
        super().setup()
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        self.cfg = {"host": "sim", "port": 7000, "method_dir": "C:\\Octet\\Methods", "allowed_methods": [], "max_run_hours": 12}

    def time_scale(self) -> float:
        return self.scale

    def make_backend(self):
        return SimBackend(self.cfg, self.scale)
