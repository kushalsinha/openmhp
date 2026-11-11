"""Simulated Rigol DS1054Z: answers the SCPI subset in descriptor.yaml for a 1 kHz, 2 Vpp sine on CH1.

Measurements are computed from that signal and the channel scale: a trace that would leave the
8-division screen is clipped, so Vpp and Vrms go wrong the way they do on the bench, and a
hidden channel or a channel with no signal (CH2-4) answers 9.9E37. Scales snap to the 1-2-5
sequence. Unknown commands push -113,"Undefined header" and get no reply. No time behaviour
beyond the trigger state, so OPENMHP_SIM_TIME_SCALE is not used.
"""
import math

from openmhp.drivers.scpi_visa import ScpiVisaDriver

_INVALID = "9.9E37"
_SIGNAL = {"CHAN1": (1.0, 1000.0)}          # amplitude V, frequency Hz


def _snap125(v: float) -> float:
    exp = math.floor(math.log10(v))
    m = v / 10 ** exp
    step = 1 if m < 1.5 else 2 if m < 3.5 else 5 if m < 7.5 else 10
    return step * 10 ** exp


class _FakeInst:
    is_open = True

    def __init__(self):
        self.status = "AUTO"
        self.disp = {"CHAN1": 1, "CHAN2": 0, "CHAN3": 0, "CHAN4": 0}
        self.scale = {"CHAN1": 1.0, "CHAN2": 1.0, "CHAN3": 1.0, "CHAN4": 1.0}
        self.offs = {"CHAN1": 0.0, "CHAN2": 0.0, "CHAN3": 0.0, "CHAN4": 0.0}
        self.tim, self.tlev, self.tsrc = 1e-3, 0.0, "CHAN1"
        self.errors, self.sent, self._r = [], [], b""

    def _measure(self, item, chan):
        if chan not in _SIGNAL or not self.disp.get(chan):
            return _INVALID
        amp, freq = _SIGNAL[chan]
        top = 4 * self.scale[chan] - self.offs[chan]
        bot = -4 * self.scale[chan] - self.offs[chan]
        vmax, vmin = min(amp, top), max(-amp, bot)
        clipped = vmax < amp or vmin > -amp
        vrms = amp / math.sqrt(2) if not clipped else (vmax - vmin) / 2 / math.sqrt(2) * 1.1
        if 12 * self.tim * freq < 1:
            return _INVALID if item in ("FREQ", "PER") else None
        val = {"VPP": vmax - vmin, "VMAX": vmax, "VMIN": vmin, "VRMS": vrms, "VAVG": (vmax + vmin) / 2,
               "VTOP": vmax, "VBAS": vmin, "VAMP": vmax - vmin, "FREQ": freq, "PER": 1 / freq}.get(item)
        return _INVALID if val is None else f"{val:.6e}"

    def write(self, b):
        c = b.decode().strip()
        self.sent.append(c)
        self._r = b""
        head, _, arg = c.upper().partition(" ")
        args = [a.strip() for a in arg.split(",")] if arg else []
        if head == "*IDN?":
            self._r = b"RIGOL TECHNOLOGIES,DS1054Z,DS1ZA123456789,00.04.04.SP4\n"
        elif head == ":RUN":
            self.status = "AUTO"
        elif head == ":STOP":
            self.status = "STOP"
        elif head == ":SING":
            self.status = "TD"
        elif head == ":AUT":
            self.scale["CHAN1"], self.offs["CHAN1"], self.tim, self.tlev = 0.5, 0.0, 2e-4, 0.0
            self.status = "TD"
        elif head == ":TRIG:STAT?":
            self._r = f"{self.status}\n".encode()
        elif head == ":MEAS:ITEM?" and len(args) == 2:
            v = self._measure(args[0], args[1])
            self._r = f"{v}\n".encode()
        elif head == ":ACQ:SRAT?":
            self._r = f"{min(1e9, 12e6 / (12 * self.tim)):.6e}\n".encode()
        elif head.startswith(":CHAN") and len(head) > 5 and head[5].isdigit():
            chan = f"CHAN{head[5]}"
            sub = head[6:]
            if sub == ":DISP?":
                self._r = f"{self.disp[chan]}\n".encode()
            elif sub == ":DISP" and args:
                self.disp[chan] = 1 if args[0] in ("1", "ON") else 0
            elif sub == ":SCAL?":
                self._r = f"{self.scale[chan]:.6e}\n".encode()
            elif sub == ":SCAL" and args:
                self.scale[chan] = _snap125(max(1e-3, min(10.0, float(args[0]))))
            elif sub == ":OFFS?":
                self._r = f"{self.offs[chan]:.6e}\n".encode()
            elif sub == ":OFFS" and args:
                lim = 2.0 if self.scale[chan] < 0.5 else 100.0
                self.offs[chan] = max(-lim, min(lim, float(args[0])))
            else:
                self.errors.append('-113,"Undefined header"')
        elif head == ":TIM:SCAL?":
            self._r = f"{self.tim:.6e}\n".encode()
        elif head == ":TIM:SCAL" and args:
            self.tim = _snap125(max(5e-9, min(50.0, float(args[0]))))
        elif head == ":TRIG:EDG:LEV?":
            self._r = f"{self.tlev:.6e}\n".encode()
        elif head == ":TRIG:EDG:LEV" and args:
            lim = 5 * self.scale.get(self.tsrc, 1.0)
            self.tlev = max(-lim, min(lim, float(args[0])))
        elif head == ":TRIG:EDG:SOUR?":
            self._r = f"{self.tsrc}\n".encode()
        elif head == ":TRIG:EDG:SOUR" and args:
            self.tsrc = args[0]
        elif head == ":SYST:ERR?":
            self._r = ((self.errors.pop(0) if self.errors else '0,"No error"') + "\n").encode()
        else:
            self.errors.append('-113,"Undefined header"')

    def readline(self):
        return self._r


class Sim(ScpiVisaDriver):
    link = _FakeInst()
