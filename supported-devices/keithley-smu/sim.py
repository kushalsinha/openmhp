"""Simulated Keithley 2400: answers the SCPI subset in descriptor.yaml against a 1 kOhm resistor.

The fake instrument keeps the source function, setpoints, compliance and output state. :READ? takes
a reading (refused with +803 while the output is off) and :FETC? hands back the last one; the
five-field reading line has the measured quantity clamped at compliance like the real source.
:MEAS? is modelled as turning the output on, the manual's description and the reason the
package does not use it. Unknown commands get no reply and push -113,"Undefined
header" onto the error queue, which :SYST:ERR? drains, as the instrument does. No time
behaviour, so OPENMHP_SIM_TIME_SCALE is not used.
"""
import time

from openmhp.drivers.scpi_visa import ScpiVisaDriver

_R_DUT = 1000.0                      # ohms, the simulated device under test


class _FakeInst:
    is_open = True

    def __init__(self):
        self.func, self.v, self.i = "VOLT", 0.0, 0.0
        self.comp_i, self.comp_v = 0.000105, 21.0
        self.out, self.beep = 0, 1
        self.errors, self.sent, self._r = [], [], b""
        self.t0 = time.time()
        self.last = f"{0.0:+.6E},{0.0:+.6E},+9.910000E+37,{0.0:+.6E},{0.0:+.6E}\n".encode()

    def _reading(self):
        if self.func == "VOLT":
            v = self.v
            i = max(-self.comp_i, min(self.comp_i, v / _R_DUT))
        else:
            i = self.i
            v = max(-self.comp_v, min(self.comp_v, i * _R_DUT))
        status = 0x4000 if (abs(i) >= self.comp_i or abs(v) >= self.comp_v) else 0
        return f"{v:+.6E},{i:+.6E},+9.910000E+37,{time.time() - self.t0:+.6E},{status:+.6E}\n".encode()

    def _set(self, text):
        return float(text.strip())

    def write(self, b):
        c = b.decode().strip()
        self.sent.append(c)
        self._r = b""
        up = c.upper()
        if up == "*IDN?":
            self._r = b"KEITHLEY INSTRUMENTS INC.,MODEL 2400,1234567,C32   Oct  4 2010 14:20:11/A02  /K/J\n"
        elif up == "*RST":
            self.func, self.v, self.i, self.comp_i, self.comp_v, self.out = "VOLT", 0.0, 0.0, 0.000105, 21.0, 0
        elif up == "*CLS":
            self.errors.clear()
        elif up == ":READ?":
            if self.out:
                self.last = self._reading()
                self._r = self.last
            else:
                self.errors.append('+803,"Not permitted with OUTPUT off"')
        elif up == ":FETC?":
            self._r = self.last
        elif up in (":MEAS:VOLT?", ":MEAS:CURR?", ":MEAS?"):
            self.out = 1                                    # the manual's :MEAS? includes :CONFigure, which turns the source on
            self.last = self._reading()
            self._r = self.last
        elif up == ":OUTP?":
            self._r = f"{self.out}\n".encode()
        elif up.startswith(":OUTP "):
            self.out = 1 if up.split()[1] in ("1", "ON") else 0
        elif up == ":SOUR:FUNC?":
            self._r = f"{self.func}\n".encode()
        elif up.startswith(":SOUR:FUNC "):
            self.func = up.split()[1][:4]
        elif up == ":SOUR:VOLT?":
            self._r = f"{self.v:+.6E}\n".encode()
        elif up == ":SOUR:CURR?":
            self._r = f"{self.i:+.6E}\n".encode()
        elif up.startswith(":SOUR:VOLT:MODE") or up.startswith(":SOUR:CURR:MODE"):
            pass
        elif up.startswith(":SOUR:VOLT "):
            self.v = self._set(c.split()[1])
        elif up.startswith(":SOUR:CURR "):
            self.i = self._set(c.split()[1])
        elif up == ":SENS:CURR:PROT?":
            self._r = f"{self.comp_i:+.6E}\n".encode()
        elif up == ":SENS:VOLT:PROT?":
            self._r = f"{self.comp_v:+.6E}\n".encode()
        elif up.startswith(":SENS:CURR:PROT "):
            self.comp_i = self._set(c.split()[1])
        elif up.startswith(":SENS:VOLT:PROT "):
            self.comp_v = self._set(c.split()[1])
        elif up.startswith(":SYST:BEEP:STAT "):
            self.beep = 1 if up.split()[1] in ("1", "ON") else 0
        elif up == ":SYST:ERR?":
            self._r = ((self.errors.pop(0) if self.errors else '0,"No error"') + "\n").encode()
        elif up == ":ABOR":
            pass
        else:
            self.errors.append('-113,"Undefined header"')

    def readline(self):
        return self._r


class Sim(ScpiVisaDriver):
    link = _FakeInst()
