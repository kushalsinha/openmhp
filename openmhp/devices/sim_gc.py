"""A simulated gas chromatograph: behaviour only. Its descriptor and operating
instructions live in the device package next to this file (gc-01/).

The point of this simulator is the closed loop: every run is one *method* (an oven
program, an injection volume, optionally a carrier flow), and the result it pushes
back (peaks, resolution) is what an agent adapts the next run on. The physics is a
caricature with the right signs: lower flow and slower ramps separate close peaks
better and take longer; bigger injections overload the inlet and broaden peaks.
"""
from __future__ import annotations

import math
import os
import time
from pathlib import Path

from ..driver import Driver, InvalidValue, Job, LimitViolation, is_finite_number
from ..package import load_package

PACKAGE = Path(__file__).parent / "gc-01"
DESCRIPTOR = load_package(PACKAGE).descriptor
OVEN_MIN, OVEN_MAX = 40, 320
RAMP_MIN, RAMP_MAX = 1, 50
MAX_PROGRAM_S = 3600

# name -> boiling point (degC); retention on this column follows boiling point
COMPOUNDS = {"methanol": 65, "acetone": 56, "ethanol": 78, "isopropanol": 82, "hexane": 69,
             "benzene": 80, "toluene": 111, "butanol": 118, "xylene": 139}
DEFAULT_SAMPLE = ("acetone", "ethanol", "isopropanol", "toluene")


def _program_seconds(program: list[dict]) -> float:
    total, prev = 0.0, None
    for step in program:
        if prev is not None:
            total += abs(step["temp"] - prev) / step.get("ramp_c_min", 20) * 60
        total += step.get("hold_s", 0)
        prev = step["temp"]
    return total


class SimGC(Driver):
    package_dir = str(PACKAGE)

    def setup(self):
        self.oven, self.flow_sp, self.inlet, self.detector = 40.0, 1.5, 250.0, 300.0
        self.detector_ready, self.injections, self.last_result = True, 0, None
        self.pressure = 80.0
        # simulated seconds per real second; a 3-minute method takes about 2 s by default
        self.time_scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))

    # ---- signals and settings -------------------------------------------------------------
    def on_read(self, name):
        return {"oven_temperature": round(self.oven, 1), "carrier_flow": round(self.flow_sp, 2),
                "column_pressure": round(self.pressure, 1), "detector_ready": self.detector_ready,
                "injections_today": self.injections, "last_result": self.last_result}[name]

    def on_write(self, name, value):
        if name == "carrier_flow_setpoint":
            self.flow_sp = float(value)
            self.pressure = 40 + 27 * self.flow_sp
            self.emit_signal("carrier_flow", round(self.flow_sp, 2))
        elif name == "inlet_temperature":
            self.inlet = float(value)
        elif name == "detector_temperature":
            self.detector = float(value)

    # ---- the whole method is checked before the injection, in dry runs too ----------------
    def validate_params(self, action: str, params: dict) -> None:
        if action != "run_method":
            return
        prog = params.get("oven_program")
        if not isinstance(prog, list) or not prog:
            raise InvalidValue("run_method.oven_program must be a non-empty list of steps")
        for i, step in enumerate(prog):
            if not isinstance(step, dict):
                raise InvalidValue(f"run_method.oven_program[{i}] must be an object with temp, hold_s and ramp_c_min")
            extra = set(step) - {"temp", "hold_s", "ramp_c_min"}
            if extra:
                raise InvalidValue(f"run_method.oven_program[{i}]: unknown keys {sorted(extra)}")
            temp, hold, ramp = step.get("temp"), step.get("hold_s", 0), step.get("ramp_c_min", 20)
            if not is_finite_number(temp):
                raise InvalidValue(f"run_method.oven_program[{i}].temp must be a finite number")
            if not OVEN_MIN <= temp <= OVEN_MAX:
                raise LimitViolation(f"run_method.oven_program[{i}].temp={temp} outside oven limits {OVEN_MIN}..{OVEN_MAX}",
                                     {"min": OVEN_MIN, "max": OVEN_MAX})
            if not is_finite_number(hold) or not 0 <= hold <= MAX_PROGRAM_S:
                raise LimitViolation(f"run_method.oven_program[{i}].hold_s={hold!r} outside 0..{MAX_PROGRAM_S}")
            if not is_finite_number(ramp) or not RAMP_MIN <= ramp <= RAMP_MAX:
                raise LimitViolation(f"run_method.oven_program[{i}].ramp_c_min={ramp!r} outside {RAMP_MIN}..{RAMP_MAX}",
                                     {"min": RAMP_MIN, "max": RAMP_MAX})
        if _program_seconds(prog) > MAX_PROGRAM_S:
            raise LimitViolation(f"run_method.oven_program lasts {_program_seconds(prog):.0f} s; the maximum is {MAX_PROGRAM_S}")
        sample = params.get("sample")
        if sample is not None and not isinstance(sample, str):
            raise InvalidValue("run_method.sample must be a string")

    # ---- the run ---------------------------------------------------------------------------
    def _peaks(self, prog: list[dict], flow: float, inj: float, names: list[str]) -> list[dict]:
        start_hold = prog[0].get("hold_s", 0)
        ramp = prog[1].get("ramp_c_min", 20) if len(prog) > 1 else 20
        flow_k = (1.5 / flow) ** 0.7
        ramp_k = (20 / max(ramp, 1)) ** 0.3
        overload = 1 + max(0.0, inj - 2) * 0.5
        peaks = []
        for n in names:
            bp = COMPOUNDS[n]
            rt = ((bp - 20) * 1.5 * flow_k * ramp_k) + start_hold * 0.3
            width = (3 + 0.02 * rt * (flow / 1.5) ** 0.3) * overload
            peaks.append({"name": n, "rt_s": round(rt, 1), "width_s": round(width, 2), "area": round(1000 * inj * (bp / 80), 0)})
        return sorted(peaks, key=lambda p: p["rt_s"])

    @staticmethod
    def _resolution(peaks: list[dict]) -> tuple[list[dict], float | None]:
        pairs = []
        for a, b in zip(peaks, peaks[1:]):
            rs = 2 * (b["rt_s"] - a["rt_s"]) / (a["width_s"] + b["width_s"])
            pairs.append({"between": [a["name"], b["name"]], "resolution": round(rs, 2)})
        return pairs, (min(p["resolution"] for p in pairs) if pairs else None)

    @staticmethod
    def _trace(peaks: list[dict], run_s: float, n: int = 100) -> list[list[float]]:
        out = []
        for i in range(n):
            t = run_s * i / (n - 1)
            y = sum(p["area"] / (p["width_s"] * 2.5) * math.exp(-0.5 * ((t - p["rt_s"]) / (p["width_s"] / 2.355)) ** 2) for p in peaks)
            out.append([round(t, 1), round(y, 1)])
        return out

    def on_invoke(self, job: Job):
        if job.action == "bakeout":
            for i in range(10):
                self.checkpoint(job, (i + 1) / 10)
                self.oven = 300.0
                time.sleep(max(0.02, 1800 * self.time_scale / 10))
            self.oven = 40.0
            return {"baked": True}
        if job.action == "run_method":
            p = job.params
            prog = p["oven_program"]
            flow = float(p.get("carrier_flow_ml_min", self.flow_sp))
            inj = float(p["injection_volume_ul"])
            words = [w.strip(",;/ ").lower() for w in str(p.get("sample") or "").split()]
            names = [w for w in words if w in COMPOUNDS] or list(DEFAULT_SAMPLE)
            peaks = self._peaks(prog, flow, inj, names)
            run_s = max(_program_seconds(prog), peaks[-1]["rt_s"] + 20)
            self.injections += 1
            self.emit_signal("injections_today", self.injections)
            steps = 10
            for i in range(steps):
                self.checkpoint(job, (i + 1) / steps, phase="oven program", elapsed_s=round(run_s * (i + 1) / steps))
                frac = (i + 1) / steps
                self.oven = prog[0]["temp"] + (prog[-1]["temp"] - prog[0]["temp"]) * frac
                self.emit_signal("oven_temperature", round(self.oven, 1))
                time.sleep(max(0.02, run_s * self.time_scale / steps))
            self.oven = prog[0]["temp"]
            pairs, rs_min = self._resolution(peaks)
            summary = {"sample": names, "peaks": peaks, "resolution": pairs, "resolution_min": rs_min,
                       "unresolved": [pr["between"] for pr in pairs if pr["resolution"] < 1.5],
                       "run_time_s": round(run_s, 1), "carrier_flow_ml_min": flow, "injection_volume_ul": inj,
                       "injection": self.injections}
            self.last_result = summary
            self.emit_signal("last_result", summary)          # pushed: no one has to ask
            return {**summary, "chromatogram": self._trace(peaks, run_s)}
        raise InvalidValue(f"unhandled action {job.action}")

    def on_estop(self):
        self.detector_ready = False                            # the flame goes out with the gas
        self.oven, self.inlet = 40.0, 40.0

    def verify_recovery(self):
        self.detector_ready, self.inlet = True, 250.0          # a person relit the FID before asking for a reset
        return super().verify_recovery()
