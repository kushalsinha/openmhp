"""Simulated twin of an RGA200 ECU: ASCII commands in, `<value>\\n\\r` replies out, STATUS byte after hardware commands.

The filament takes about 3 simulated seconds to reach its emission setpoint; if the (simulated) chamber
pressure is above 1e-4 Torr the head's own protection shuts it off and sets FIL_ERR bit 6, as the real
firmware does. Time runs at OPENMHP_SIM_TIME_SCALE real seconds per simulated second (default 0.01).
Set `link.pressure_torr` from a test to rehearse the overpressure path.
"""
import os
import re
import time

from openmhp.drivers.serial_ascii import SerialAsciiDriver

_NUM = re.compile(r"[-+]?\d+(?:\.\d+)?")


class _FakePort:
    is_open = True

    def __init__(self):
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        self.t = time.time()
        self.pressure_torr = 1.0e-6
        self.fl_set = self.fl = 0.0          # setpoint and actual emission, mA
        self.ee, self.ie, self.vf, self.hv, self.nf = 70, 1, 90, 0, 4
        self.fil_err = self.rs_err = 0
        self.cdem = True
        self.sent: list[str] = []
        self._reply = b""

    def _tick(self):
        now = time.time()
        dt = (now - self.t) / self.scale
        self.t = now
        if self.fl_set > 0 and self.pressure_torr > 1.0e-4:   # background filament protection
            self.fl_set = self.fl = 0.0
            self.fil_err |= 0x40
            self.hv = 0
            return
        step = dt / 3.0
        self.fl += max(-step, min(step, self.fl_set - self.fl))

    def _status(self) -> int:
        s = 0
        if self.rs_err:
            s |= 0x01
        if self.fil_err:
            s |= 0x02
        return s

    def write(self, b: bytes):
        cmd = b.decode(errors="replace").strip().upper()
        self.sent.append(cmd)
        self._tick()
        mn, arg = cmd[:2], cmd[2:]
        q = arg == "?"
        reply = None
        if mn == "ID" and q:
            reply = "SRSRGA200VER0.24SN12345"
        elif mn == "FL":
            if q:
                reply = f"{self.fl:.2f}"
            else:
                v = float(arg) if arg not in ("", "*") else 1.0
                if v == 0 or 0.02 <= v <= 3.5:
                    self.fl_set = v
                    if v > 0:
                        self.fil_err = 0
                    self.t -= 3.0 * self.scale          # emission is established before STATUS comes back
                    self._tick()
                else:
                    self.rs_err |= 0x02
                reply = str(self._status())
        elif mn in ("EE", "IE", "VF", "HV"):
            attr = mn.lower()
            if q:
                reply = str(getattr(self, attr))
            else:
                v = int(float(arg)) if arg not in ("", "*") else {"ee": 70, "ie": 1, "vf": 90, "hv": 1400}[attr]
                lo, hi = {"ee": (25, 105), "ie": (0, 1), "vf": (0, 150), "hv": (0, 2490)}[attr]
                if mn == "HV" and not self.cdem:
                    self.rs_err |= 0x01
                elif lo <= v <= hi and not (mn == "HV" and 0 < v < 10):
                    setattr(self, attr, v)
                else:
                    self.rs_err |= 0x02
                reply = str(self._status())
        elif mn == "NF":
            if q:
                reply = str(self.nf)
            elif arg.isdigit() and 0 <= int(arg) <= 7:
                self.nf = int(arg)                       # no reply, as on the real head
        elif mn == "MO" and q:
            reply = "1" if self.cdem else "0"
        elif mn == "ER" and q:
            reply = str(self._status())
        elif mn == "EF" and q:
            reply = str(self.fil_err)
        elif mn == "EC" and q:
            reply, self.rs_err = str(self.rs_err), 0
        elif mn == "IN" and arg in ("0", "1", "2"):
            self.rs_err = 0
            if arg in ("1", "2"):
                self.ee, self.ie, self.vf, self.nf = 70, 1, 90, 4
            if arg == "2":
                self.fl_set = self.fl = 0.0
                self.hv = 0
            reply = str(self._status())
        elif mn == "CA" and arg == "":
            reply = str(self._status())
        elif mn in ("MR", "TP", "SC", "HS"):
            self._reply = b"\x00\x00\x00\x00"              # binary current: what this package refuses to parse
            return
        else:
            self.rs_err |= 0x01                             # bad command: no reply, error bit set
        self._reply = (reply + "\n\r").encode() if reply is not None else b""

    def readline(self) -> bytes:
        r, self._reply = self._reply, b""
        return r


class Sim(SerialAsciiDriver):
    link = _FakePort()
