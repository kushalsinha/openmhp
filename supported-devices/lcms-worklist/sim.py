"""Simulated twin of the LC-MS worklist builder: the same renderer and parser, writing into a temp folder."""
from __future__ import annotations

import importlib.util
import os
import pathlib
import sys
import tempfile

_spec = importlib.util.spec_from_file_location(__name__ + "_real", pathlib.Path(__file__).with_name("driver.py"))
real = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = real
_spec.loader.exec_module(real)


class SimBackend(real.WorklistBackend):
    """Every line of the real formats runs; only the folder is a fresh temp directory."""


class SimLCMSWorklist(real.LCMSWorklist):
    def setup(self) -> None:
        super().setup()
        base = os.environ.get("OPENMHP_HOME") or tempfile.gettempdir()
        pathlib.Path(base).mkdir(parents=True, exist_ok=True)
        out = tempfile.mkdtemp(prefix="lcms-worklist-", dir=base)
        self.cfg = {"vendor": os.environ.get("OPENMHP_SIM_LCMS_VENDOR", "masslynx"), "output_dir": out,
                    "tune_file": "", "data_path": "C:\\Xcalibur\\data\\sim", "bracket_type": 4,
                    "list_separator": ",", "max_rows": 384}

    def make_backend(self):
        return SimBackend(self.cfg)
