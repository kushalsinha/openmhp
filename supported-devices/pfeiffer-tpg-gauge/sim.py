"""Simulated twin of a two-channel TPG 362: answers the mnemonic + ENQ/ACK protocol with a small vacuum model.

Channel 1 is a Pirani (TPR) on a chamber pumping down from 1e-2 mbar towards 5e-4 mbar; channel 2 is
a cold-cathode (IKR) that reads 5 (no sensor) until switched on and then follows the chamber below
1e-3 mbar. Time runs at OPENMHP_SIM_TIME_SCALE real seconds per simulated second (default 0.01).
"""
from __future__ import annotations

import importlib.util
import math
import os
import pathlib
import sys
import time

_spec = importlib.util.spec_from_file_location(__name__ + "_real", pathlib.Path(__file__).with_name("driver.py"))
real = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = real
_spec.loader.exec_module(real)

ACK, NAK = b"\x06\r\n", b"\x15\r\n"


class _FakePort:
    is_open = True

    def __init__(self):
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        self.t = time.time()
        self.p1 = 1.0e-2                      # chamber pressure, mbar
        self.sen = [2, 1]                     # SEN states: 2 on, 1 off
        self.unit = 0                         # UNI: 0 = mbar
        self.pending = None                   # mnemonic awaiting ENQ
        self.err = "0000"
        self.sent: list[str] = []
        self._reply = b""

    # -- physics -------------------------------------------------------- #
    def _tick(self):
        now = time.time()
        dt = (now - self.t) / self.scale
        self.t = now
        self.p1 = 5.0e-4 + (self.p1 - 5.0e-4) * math.exp(-dt / 600.0)

    def _pr(self, ch: int) -> str:
        self._tick()
        if ch == 1:
            return f"0,{self.p1:+.4E}"
        if ch == 2:
            if self.sen[1] != 2:
                return "4,+2.0000E-02"
            if self.p1 > 1.0e-3:
                return f"2,{self.p1:+.4E}"
            return f"0,{self.p1 * 0.98:+.4E}"
        return "5,+2.0000E-02"

    # -- protocol ------------------------------------------------------- #
    def write(self, b: bytes):
        if b == b"\x05":                                       # ENQ: deliver the data for the last mnemonic
            self._reply = (self._data() + "\r\n").encode()
            return
        cmd = b.decode(errors="replace").strip()
        self.sent.append(cmd)
        mn, _, params = cmd.partition(",")
        mn = mn.upper()
        known = {"PR1", "PR2", "PRX", "TID", "UNI", "SEN", "ERR", "AYT", "DGS", "PR3", "PR4", "PR5", "PR6"}
        if mn not in known:
            self.err, self.pending = "0001", "ERR"
            self._reply = NAK
            return
        if mn == "SEN" and params:
            vals = [int(x) for x in params.split(",") if x.strip()]
            if len(vals) != 2:
                self.err, self.pending = "0010", "ERR"
                self._reply = NAK
                return
            for i, v in enumerate(vals):
                if v in (1, 2):
                    self.sen[i] = v
        if mn == "UNI" and params:
            self.unit = int(params)
        self.pending = mn
        self._reply = ACK

    def _data(self) -> str:
        mn = self.pending or "ERR"
        if mn.startswith("PR") and mn[2:].isdigit():
            return self._pr(int(mn[2:]))
        if mn == "PRX":
            return ",".join(self._pr(ch) for ch in (1, 2))
        if mn == "TID":
            return "TPR/PCR,IKR"
        if mn == "UNI":
            return str(self.unit)
        if mn == "SEN":
            return f"{self.sen[0]},{self.sen[1]}"
        if mn == "ERR":
            e, self.err = self.err, "0000"
            return e
        if mn == "AYT":
            return "TPG362,PTG28290,44990000,010400,010100"
        if mn == "DGS":
            return "1,0"
        return "0001"

    def readline(self) -> bytes:
        r, self._reply = self._reply, b""
        return r


class Sim(real.Device):
    link = _FakePort()
