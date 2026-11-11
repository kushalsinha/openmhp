"""Simulated PM100D with an S121C photodiode head: answers the SCPI subset in descriptor.yaml.

The fake sees a 1.00 mW beam at 532 nm; the reported power follows the head's responsivity
curve, so a wrong wavelength setting gives a wrong reading as on the bench. A wavelength
outside the head's 400 to 1100 nm pushes -222,"Data out of range" onto the error queue and is
ignored. Unknown commands push -113,"Undefined header" and get no reply; :SYST:ERR? drains the
queue. No time behaviour, so OPENMHP_SIM_TIME_SCALE is not used.
"""
from openmhp.drivers.scpi_visa import ScpiVisaDriver

_HEAD_MIN, _HEAD_MAX = 400.0, 1100.0
_TRUE_POWER_W, _TRUE_WAVELENGTH_NM = 1.0e-3, 532.0


def _responsivity(nm: float) -> float:
    """Silicon photodiode, roughly: rises from 400 nm, peaks near 950 nm, falls to 1100 nm."""
    if nm < 950:
        return 0.1 + 0.5 * (nm - 400.0) / 550.0
    return 0.6 - 0.5 * (nm - 950.0) / 150.0


class _FakeInst:
    is_open = True

    def __init__(self):
        self.wav, self.aver, self.auto, self.lpas = 1064.0, 10, 1, 1
        self.rng = 2.5e-3
        self.dark = 2.0e-6
        self.errors, self.sent, self._r = [], [], b""

    def _power(self):
        p = _TRUE_POWER_W * _responsivity(_TRUE_WAVELENGTH_NM) / _responsivity(self.wav) + self.dark
        if self.auto:
            self.rng = next((r for r in (5e-6, 5e-5, 5e-4, 5e-3, 5e-2, 5e-1) if r >= p), 5e-1)
        return min(p, self.rng)

    def write(self, b):
        c = b.decode().strip()
        self.sent.append(c)
        self._r = b""
        up = c.upper()
        head, _, arg = up.partition(" ")
        if head == "*IDN?":
            self._r = b"Thorlabs,PM100D,P0012345,2.6.0\n"
        elif head == "*RST":
            self.wav, self.aver, self.auto, self.lpas, self.rng = 1064.0, 10, 1, 1, 2.5e-3
        elif head == "*CLS":
            self.errors.clear()
        elif head == ":MEAS:POW?":
            self._r = f"{self._power():.6E}\n".encode()
        elif head == ":MEAS:TEMP?":
            self._r = b"+2.3450000E+01\n"
        elif head == ":SENS:CORR:WAV?":
            self._r = f"{self.wav:.1f}\n".encode()
        elif head == ":SENS:CORR:WAV":
            v = float(arg)
            if _HEAD_MIN <= v <= _HEAD_MAX:
                self.wav = v
            else:
                self.errors.append('-222,"Data out of range"')
        elif head == ":SYST:SENS:IDN?":
            self._r = b"S121C,12345678,18-Mar-2025,3,18,1\n"
        elif head == ":SENS:AVER?":
            self._r = f"{self.aver}\n".encode()
        elif head == ":SENS:AVER":
            self.aver = int(float(arg))
        elif head == ":SENS:POW:RANG:AUTO?":
            self._r = f"{self.auto}\n".encode()
        elif head == ":SENS:POW:RANG:AUTO":
            self.auto = 1 if arg in ("1", "ON") else 0
        elif head == ":SENS:POW:RANG?":
            self._r = f"{self.rng:.6E}\n".encode()
        elif head == ":INP:PDIO:FILT:LPAS:STAT?":
            self._r = f"{self.lpas}\n".encode()
        elif head == ":INP:PDIO:FILT:LPAS:STAT":
            self.lpas = 1 if arg in ("1", "ON") else 0
        elif head == ":SENS:CORR:COLL:ZERO:INIT":
            self.dark = 0.0
        elif head == ":SYST:ERR?":
            self._r = ((self.errors.pop(0) if self.errors else '0,"No error"') + "\n").encode()
        else:
            self.errors.append('-113,"Undefined header"')

    def readline(self):
        return self._r


class Sim(ScpiVisaDriver):
    link = _FakeInst()
