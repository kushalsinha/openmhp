"""Simulated Rigol DP832: answers the SCPI subset in descriptor.yaml with a 10 ohm load on each channel.

With an output on, the measured voltage is the setpoint unless the load would draw more than
the current limit, in which case the channel sits in constant-current mode at V = I_limit * R.
A measured voltage above the OVP value or a current above the OCP value trips the output off
(and the trip is recorded on the error queue). Unknown commands push -113,"Undefined header"
and get no reply. No time behaviour, so OPENMHP_SIM_TIME_SCALE is not used.
"""
from openmhp.drivers.scpi_visa import ScpiVisaDriver

_R_LOAD = 10.0
_RATING = {1: (30.0, 3.0), 2: (30.0, 3.0), 3: (5.0, 3.0)}


class _Channel:
    def __init__(self, vmax, imax):
        self.vmax, self.imax = vmax, imax
        self.v, self.i = 0.0, 0.1
        self.ovp, self.ocp = vmax + 1.0, imax + 0.1
        self.ovp_on = self.ocp_on = 0
        self.on = 0

    def measured(self):
        if not self.on:
            return 0.0, 0.0
        i = self.v / _R_LOAD
        if i > self.i:
            return self.i * _R_LOAD, self.i
        return self.v, i


class _FakeInst:
    is_open = True

    def __init__(self):
        self.ch = {n: _Channel(*r) for n, r in _RATING.items()}
        self.errors, self.sent, self._r = [], [], b""

    def _protect(self, n):
        c = self.ch[n]
        v, i = c.measured()
        if c.on and ((c.ovp_on and v > c.ovp) or (c.ocp_on and i > c.ocp)):
            c.on = 0
            self.errors.append(f'-224,"Protection tripped on CH{n}"')

    @staticmethod
    def _chan(arg):
        return int(arg.strip().upper().replace("CH", "")[:1])

    def write(self, b):
        c = b.decode().strip()
        self.sent.append(c)
        self._r = b""
        head, _, arg = c.upper().partition(" ")
        args = [a.strip() for a in arg.split(",")] if arg else []
        if head == "*IDN?":
            self._r = b"RIGOL TECHNOLOGIES,DP832,DP8C123456789,00.01.14\n"
        elif head in (":MEAS:VOLT?", ":MEAS:CURR?", ":MEAS:POWE?") and args:
            n = self._chan(args[0])
            self._protect(n)
            v, i = self.ch[n].measured()
            val = {":MEAS:VOLT?": v, ":MEAS:CURR?": i, ":MEAS:POWE?": v * i}[head]
            self._r = f"{val:.3f}\n".encode()
        elif head == ":OUTP?" and args:
            n = self._chan(args[0])
            self._protect(n)
            self._r = b"ON\n" if self.ch[n].on else b"OFF\n"
        elif head == ":OUTP" and len(args) == 2:
            self.ch[self._chan(args[0])].on = 1 if args[1] == "ON" else 0
        elif head.startswith(":SOUR") and head.endswith(":VOLT") and args:
            n = int(head[5]); v = float(args[0])
            if 0 <= v <= self.ch[n].vmax:
                self.ch[n].v = v
            else:
                self.errors.append('-222,"Data out of range"')
        elif head.startswith(":SOUR") and head.endswith(":CURR") and args:
            n = int(head[5]); i = float(args[0])
            if 0 <= i <= self.ch[n].imax:
                self.ch[n].i = i
            else:
                self.errors.append('-222,"Data out of range"')
        elif head == ":OUTP:OVP:VAL" and len(args) == 2:
            self.ch[self._chan(args[0])].ovp = float(args[1])
        elif head == ":OUTP:OCP:VAL" and len(args) == 2:
            self.ch[self._chan(args[0])].ocp = float(args[1])
        elif head == ":OUTP:OVP" and len(args) == 2:
            self.ch[self._chan(args[0])].ovp_on = 1 if args[1] == "ON" else 0
        elif head == ":OUTP:OCP" and len(args) == 2:
            self.ch[self._chan(args[0])].ocp_on = 1 if args[1] == "ON" else 0
        elif head == ":SYST:ERR?":
            self._r = ((self.errors.pop(0) if self.errors else '0,"No error"') + "\n").encode()
        else:
            self.errors.append('-113,"Undefined header"')

    def readline(self):
        return self._r


class Sim(ScpiVisaDriver):
    link = _FakeInst()
