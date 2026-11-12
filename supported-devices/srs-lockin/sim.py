"""Simulated SR830: answers the command subset in descriptor.yaml with a fixed test signal.

The fake instrument sees 1 mV rms at the reference frequency, 30 degrees behind the
reference, scaled by the sine amplitude (as a sample driven by the sine out would be). X, Y, R
and theta follow from that and the phase setting; a value larger than the sensitivity full scale
is clamped to it, which is what overload looks like. Unknown commands get no reply, as on the
instrument (it sets an error bit instead). No time behaviour, so OPENMHP_SIM_TIME_SCALE is unused.
"""
import math

from openmhp.drivers.scpi_visa import ScpiVisaDriver

SENS_V = [2e-9, 5e-9, 1e-8, 2e-8, 5e-8, 1e-7, 2e-7, 5e-7, 1e-6, 2e-6, 5e-6, 1e-5, 2e-5, 5e-5,
          1e-4, 2e-4, 5e-4, 1e-3, 2e-3, 5e-3, 1e-2, 2e-2, 5e-2, 1e-1, 2e-1, 5e-1, 1.0]


class _FakeInst:
    is_open = True

    def __init__(self):
        self.outx = 1
        self.freq, self.slvl, self.sens, self.oflt = 1000.0, 1.0, 20, 8
        self.phas, self.fmod = 0.0, 1
        self.auxv = {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0}
        self.oaux = {1: 0.123, 2: -0.456, 3: 0.0, 4: 2.5}
        self.sent, self._r = [], b""

    def _xy(self):
        r = 1e-3 * self.slvl
        full = SENS_V[self.sens]
        r = min(r, full)
        ang = math.radians(-30.0 - self.phas)
        return r * math.cos(ang), r * math.sin(ang), r, math.degrees(ang)

    def _val(self, n):
        return self._xy()[n - 1]

    def write(self, b):
        c = b.decode().strip()
        self.sent.append(c)
        self._r = b""
        head, _, arg = c.partition(" ")
        head = head.upper()
        args = [a.strip() for a in arg.split(",")] if arg else []
        if head == "*IDN?":
            self._r = b"Stanford_Research_Systems,SR830,s/n12345,ver1.07\n"
        elif head == "*CLS":
            pass
        elif head == "OUTX" and args:
            self.outx = int(args[0])
        elif head == "OUTP?" and args:
            self._r = f"{self._val(int(args[0])):.6e}\n".encode()
        elif head == "SNAP?" and args:
            self._r = (",".join(f"{self._val(int(a)):.6e}" for a in args) + "\n").encode()
        elif head == "FREQ?":
            self._r = f"{self.freq:.3f}\n".encode()
        elif head == "FREQ" and args:
            self.freq = float(args[0])
        elif head == "SLVL?":
            self._r = f"{self.slvl:.3f}\n".encode()
        elif head == "SLVL" and args:
            self.slvl = max(0.004, min(5.0, float(args[0])))
        elif head == "SENS?":
            self._r = f"{self.sens}\n".encode()
        elif head == "SENS" and args:
            self.sens = int(args[0])
        elif head == "OFLT?":
            self._r = f"{self.oflt}\n".encode()
        elif head == "OFLT" and args:
            self.oflt = int(args[0])
        elif head == "PHAS?":
            self._r = f"{self.phas:.2f}\n".encode()
        elif head == "PHAS" and args:
            self.phas = float(args[0])
        elif head == "FMOD?":
            self._r = f"{self.fmod}\n".encode()
        elif head == "FMOD" and args:
            self.fmod = int(args[0])
        elif head == "AUXV?" and args:
            self._r = f"{self.auxv[int(args[0])]:.3f}\n".encode()
        elif head == "AUXV" and len(args) == 2:
            self.auxv[int(args[0])] = max(-10.5, min(10.5, float(args[1])))
        elif head == "OAUX?" and args:
            self._r = f"{self.oaux[int(args[0])]:.3f}\n".encode()
        elif head == "AGAN":
            r = 1e-3 * self.slvl
            self.sens = next((i for i, s in enumerate(SENS_V) if s >= r), 26)
        elif head == "APHS":
            self.phas = -30.0
        # anything else: no reply, as on the instrument

    def readline(self):
        return self._r


class Sim(ScpiVisaDriver):
    link = _FakeInst()
