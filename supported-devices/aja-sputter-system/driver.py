"""Sputter deposition tool over Modbus TCP: the register map is declared in descriptor.yaml `modbus:` (template).

Everything is the declarative Modbus driver except `deposit`, which the grammar cannot express: it must
wait for the plasma to strike, hold the shutter closed for the presputter time, keep it open for the
deposition time and close it again whatever happens. That one action is overridden here with the smallest
possible code; the registers it writes still come from the descriptor (`modbus.actions.deposit` and
`modbus.sequences`).
"""
from __future__ import annotations

import time

from openmhp.driver import DeviceFault, Job, JobCancelled
from openmhp.drivers.modbus import ModbusDriver


class Device(ModbusDriver):
    def time_scale(self) -> float:
        return 1.0

    def _run_steps(self, steps: list, params: dict) -> int:
        for s in steps:
            v = s.get("value")
            if isinstance(v, str) and v.startswith("{") and v.endswith("}"):
                v = params[v[1:-1]]
            self._write_reg(s, v)
        return len(steps)

    def _wait(self, job: Job, seconds: float, phase: str, start_frac: float, end_frac: float) -> float:
        """Sleep `seconds` instrument seconds with checkpoints; return the instrument seconds actually waited."""
        scale = self.time_scale()
        t0 = time.monotonic()
        total = seconds * scale
        while True:
            done = (time.monotonic() - t0) / scale if scale else seconds
            if done >= seconds:
                return seconds
            self.checkpoint(job, start_frac + (end_frac - start_frac) * done / seconds, phase=phase)
            time.sleep(min(0.05, max(0.001, total - (time.monotonic() - t0))))

    def on_invoke(self, job: Job):
        if job.action != "deposit":
            return super().on_invoke(job)
        p = job.params
        seq = self.cfg.get("sequences") or {}
        pre, open_, finish = (self.cfg.get("actions") or {}).get("deposit") or [], seq.get("shutter_open") or [], seq.get("deposit_finish") or []
        if not (pre and open_ and finish):
            raise DeviceFault("descriptor.yaml has no modbus.actions.deposit / modbus.sequences.shutter_open / deposit_finish")
        scale = self.time_scale()
        started = time.monotonic()
        steps, shutter_open_s, power, pressure = 0, 0.0, 0.0, 0.0
        try:
            self.checkpoint(job, 0.0, phase="setting gas and power")
            steps += self._run_steps(pre, p)
            deadline = time.monotonic() + float(p["ignition_timeout_s"]) * scale
            while not self._read_reg(self._spec("read", "plasma_on")):
                if time.monotonic() > deadline:
                    raise DeviceFault(f"plasma did not strike within {p['ignition_timeout_s']} s at {p['gas_flow_ml_min']} sccm; "
                                      f"the shutter stayed closed", {"transient": True, "recovery": "retry_after"})
                self.checkpoint(job, 0.05, phase="waiting for plasma")
                time.sleep(min(0.05, 1.0 * scale))
            self._wait(job, float(p["presputter_s"]), "presputtering", 0.1, 0.2)
            steps += self._run_steps(open_, p)
            t_open = time.monotonic()
            try:
                self._wait(job, float(p["duration_s"]), "depositing", 0.2, 0.95)
            finally:
                shutter_open_s = (time.monotonic() - t_open) / scale
                power = float(self._read_reg(self._spec("read", "power")))
                pressure = float(self._read_reg(self._spec("read", "process_pressure")))
        except JobCancelled:
            raise
        finally:
            steps += self._run_steps(finish, p)
        rate = float(p["rate_nm_per_min"])
        return {"steps": steps, "power_w": round(power, 1), "duration_s": round((time.monotonic() - started) / scale, 1),
                "shutter_open_s": round(shutter_open_s, 1), "thickness_estimate_nm": round(rate * shutter_open_s / 60, 2),
                "rate_nm_per_min": rate, "process_pressure_mbar": pressure}
