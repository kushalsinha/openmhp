"""Nabertherm series 400/500 controller over Modbus TCP: the declarative driver plus the two things its
grammar cannot say. `program_running` is derived from the status register (2 = run), and `run_program`
with typed `segments` unrolls them into the controller's program registers (M03.0021 section 8.3) before
the start command; with a stored `program` number it is the plain declarative step list."""
from __future__ import annotations

import time

from openmhp.driver import DeviceFault, InvalidValue, Job
from openmhp.drivers.modbus import ModbusDriver

REG_STATUS, REG_COMMAND, REG_PROGRAM, REG_TRANSFERRED = 125, 148, 149, 404
REG_TARGET, REG_TIME, REG_FLAGS, REG_HOLDBACK = 200, 240, 360, 320
REG_START_TEMP, REG_PROGRAM_FLAGS, REG_SEGMENTS, REG_RELEASE = 400, 401, 402, 403
MAX_CONTROLLER_SEGMENTS = 39
FLAG_RATE = 0b10                      # bit 1: the time/rate register is a rate in degC/h, not minutes


def _u16(reg: int) -> dict:
    return {"reg": reg, "kind": "holding", "type": "uint16"}


class Device(ModbusDriver):
    def on_read(self, name):
        if name == "program_running":
            return int(self._read_reg(_u16(REG_STATUS))) == 2
        return super().on_read(name)

    def validate_params(self, action: str, params: dict) -> None:
        if action != "run_program":
            return super().validate_params(action, params)
        segs = params.get("segments") or []
        if (params.get("program") is None) == (not segs):
            raise InvalidValue("run_program: give either a stored `program` number or a list of `segments`, not both and not neither")
        if 2 * len(segs) > MAX_CONTROLLER_SEGMENTS:
            raise InvalidValue(f"run_program: {len(segs)} typed segments need {2 * len(segs)} controller segments; the controller holds {MAX_CONTROLLER_SEGMENTS}")

    def on_invoke(self, job: Job):
        if job.action != "run_program" or not job.params.get("segments"):
            return super().on_invoke(job)
        segs = job.params["segments"]
        rows = []                                           # (target degC, time min or rate degC/h, flags)
        for s in segs:
            rate = float(s["ramp_c_per_min"])
            rows.append((int(round(s["target_c"])), int(round(rate * 60)) if rate > 0 else 0, FLAG_RATE if rate > 0 else 0))
            if float(s["dwell_min"]) > 0:
                rows.append((int(round(s["target_c"])), int(round(s["dwell_min"])), 0))
        writes = [(REG_SEGMENTS, len(rows)), (REG_START_TEMP, 0), (REG_PROGRAM_FLAGS, 0)]
        for i, (target, t, flags) in enumerate(rows):
            writes += [(REG_TARGET + i, target), (REG_TIME + i, t), (REG_FLAGS + i, flags), (REG_HOLDBACK + i, 0)]
        writes.append((REG_RELEASE, 1))
        n = len(writes) + 3
        for k, (reg, value) in enumerate(writes):
            self.checkpoint(job, k / n)
            self._write_reg(_u16(reg), value)
        deadline = time.time() + float(self.cfg.get("transfer_timeout_s", 20))
        while int(self._read_reg(_u16(REG_TRANSFERRED))) != 1:
            if time.time() > deadline:
                self._write_reg(_u16(REG_RELEASE), 0)
                raise DeviceFault("the controller did not acknowledge the transferred program within 20 s (register 404 stayed 0): "
                                  "B/C controllers do not accept transfers, or a value was out of range",
                                  {"transient": False, "recovery": "manual", "effect": "no program started"})
            self.checkpoint(job)
            time.sleep(0.05)
        for k, (reg, value) in enumerate([(REG_RELEASE, 0), (REG_COMMAND, 1), (REG_COMMAND, 0)]):
            self.checkpoint(job, (len(writes) + k) / n)
            self._write_reg(_u16(reg), value)
        self.progress(job, 1.0)
        return {"steps": n, "segments_written": len(rows)}
