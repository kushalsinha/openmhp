"""Eurotherm 2400-series programmer-controller over Modbus: the declarative driver plus what its grammar
cannot say. `program_running` is derived from the program status word (2 run, 8 holdback), and
`run_program` with typed `segments` writes them into the selected program's segment blocks (HA026230
section 5.9: program 1 at 8328, 136 registers per program, 8 per segment) before selecting and running it."""
from __future__ import annotations

from openmhp.driver import InvalidValue, Job
from openmhp.drivers.modbus import ModbusDriver

REG_PROGRAM, REG_STATUS = 22, 23
PROGRAM_BASE, PROGRAM_STRIDE, SEGMENT_STRIDE, MAX_SEGMENTS = 8328, 136, 8, 16
SEG_END, SEG_RAMP_RATE, SEG_DWELL = 0, 1, 3
UNITS_MINUTES = 1
RUNNING = {2, 8}


def _u16(reg: int) -> dict:
    return {"reg": reg, "kind": "holding", "type": "uint16"}


def _i16(reg: int) -> dict:
    return {"reg": reg, "kind": "holding", "type": "int16"}           # targets may be negative on a cooled furnace


class Device(ModbusDriver):
    def on_read(self, name):
        if name == "program_running":
            return int(self._read_reg(_u16(REG_STATUS))) in RUNNING
        return super().on_read(name)

    def validate_params(self, action: str, params: dict) -> None:
        super().validate_params(action, params)
        if action == "run_program":
            segs = params.get("segments") or []
            rows = sum(2 if float(s["dwell_min"]) > 0 else 1 for s in segs) + 1
            if rows > MAX_SEGMENTS:
                raise InvalidValue(f"run_program: {len(segs)} typed segments need {rows} controller segments including End; a program holds {MAX_SEGMENTS}")

    def on_invoke(self, job: Job):
        segs = job.params.get("segments") or []
        if job.action != "run_program" or not segs:
            return super().on_invoke(job)
        base = PROGRAM_BASE + PROGRAM_STRIDE * (int(job.params["program"]) - 1)
        rows = []                                           # (segment type, target, rate-or-duration)
        for s in segs:
            rows.append((SEG_RAMP_RATE, int(round(s["target_c"])), int(round(float(s["ramp_c_per_min"])))))
            if float(s["dwell_min"]) > 0:
                rows.append((SEG_DWELL, int(round(s["target_c"])), int(round(s["dwell_min"]))))
        rows.append((SEG_END, 0, 0))
        writes = [(base + 0, 0), (base + 1, 0), (base + 2, UNITS_MINUTES), (base + 3, UNITS_MINUTES), (base + 4, 1)]
        for i, (typ, target, value) in enumerate(rows):
            off = base + SEGMENT_STRIDE * (i + 1)
            writes.append((off + 0, typ))
            if typ != SEG_END:
                writes += [(off + 1, target), (off + 2, value)]
        writes += [(REG_PROGRAM, int(job.params["program"])), (REG_STATUS, 2)]
        for k, (reg, value) in enumerate(writes):
            self.checkpoint(job, k / len(writes))
            self._write_reg(_i16(reg), value)
        self.progress(job, 1.0)
        return {"steps": len(writes), "segments_written": len(rows)}
