"""MHP driver for a Technobis Crystal16 under CrystalClear, through files: a temperature program written where the
software imports it, and the data report CSVs the software exports, parsed for clear and cloud points.

There is no public API. What is documented is the export format ("Crystal16 Data Report File, Version: 1014",
one CSV per block with the temperature program echoed and a data block of time, setpoint, actual temperature
and four reactor transmissions); see references/files.md. The program file written here uses the same step
vocabulary, but no import format is published, so it is unverified. File I/O sits behind CrystalClearFiles so
the simulated twin can replace the software's side.
"""
from __future__ import annotations

import csv
import json
import pathlib
import re
import time

from openmhp.driver import DeviceFault, Driver, InvalidValue, Job, JobCancelled

HERE = pathlib.Path(__file__).parent
BLOCKS = ("A", "B", "C", "D")
REACTORS_PER_BLOCK = 4
CLEAR_PCT = 90.0          # transmission at or above this on heating: dissolved (clear point)
CLOUD_PCT = 80.0          # transmission falling below this on cooling: nucleation (cloud point)


def load_config() -> dict:
    p = HERE / "config.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def program_lines(program: dict, block: str) -> list[str]:
    """The step vocabulary CrystalClear echoes in its export (Heat to, Cool to, Hold at, Stir (Bottom) at)."""
    out = [f"Block,{block}", f"Stir (Bottom) at,{int(program['stirrer_rpm'])}, rpm"]
    for _ in range(int(program["cycles"])):
        for s in program["steps"]:
            if s["action"] == "heat":
                out.append(f"Heat to,{s['temperature_c']:g}, at ,{s['rate_k_min']:g}, °C/min")
            elif s["action"] == "cool":
                out.append(f"Cool to,{s['temperature_c']:g}, at ,{s['rate_k_min']:g}, °C/min")
            else:
                out.append(f"Hold at,{s['temperature_c']:g}, for ,{int(s['hold_min'] * 60)}, sec")
    return out


def program_duration_min(program: dict, start_c: float = 20.0) -> float:
    t, cur = 0.0, start_c
    for _ in range(int(program["cycles"])):
        for s in program["steps"]:
            if s["action"] in ("heat", "cool"):
                t += abs(s["temperature_c"] - cur) / max(s["rate_k_min"], 0.01)
                cur = s["temperature_c"]
            else:
                t += s["hold_min"]
    return t


def parse_export(text: str) -> dict:
    """A Version 1014 data report: header fields, the echoed program and the data block."""
    rows = list(csv.reader(text.splitlines()))
    meta, program, data, section = {}, [], [], "header"
    header = None
    for r in rows:
        if not r or not any(c.strip() for c in r):
            continue
        key = r[0].strip()
        if section == "header":
            if key == "Temperature Program":
                section = "program"; continue
            if key == "Data Block":
                section = "data"; continue
            if len(r) > 1 and key:
                meta[key] = r[1].strip()
        elif section == "program":
            if key == "Data Block":
                section = "data"; continue
            program.append(",".join(c.strip() for c in r if c.strip()))
        elif section == "data":
            if header is None:
                header = [c.strip() for c in r]
                continue
            data.append(dict(zip(header, [c.strip() for c in r])))
    return {"meta": meta, "program": program, "columns": header or [], "data": data}


def _num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def transitions(data: list[dict], column: str) -> dict:
    """Clear point: first temperature where transmission reaches CLEAR_PCT while heating; cloud point: first
    temperature where it drops below CLOUD_PCT while cooling. Cycles = heating/cooling pairs seen."""
    clear, cloud, cycles = [], [], 0
    prev_t, direction = None, None
    for row in data:
        t, tr = _num(row.get("Temperature Actual [°C]")), _num(row.get(column))
        if t is None or tr is None:
            continue
        if prev_t is not None:
            d = "heat" if t > prev_t + 0.05 else ("cool" if t < prev_t - 0.05 else direction)
            if d == "cool" and direction == "heat":
                cycles += 1
            if d != direction:
                direction = d
                seen = False
            if direction == "heat" and tr >= CLEAR_PCT and not seen:
                clear.append(t); seen = True
            if direction == "cool" and tr < CLOUD_PCT and not seen:
                cloud.append(t); seen = True
        else:
            seen = False
        prev_t = t
    return {"clear_point_c": round(sum(clear) / len(clear), 2) if clear else None,
            "cloud_point_c": round(sum(cloud) / len(cloud), 2) if cloud else None,
            "cycles": max(cycles, len(clear), len(cloud))}


class CrystalClearFiles:
    def __init__(self, cfg: dict):
        self.cfg = cfg

    def open(self) -> None:
        if not self.cfg.get("program_dir"):
            raise DeviceFault("config.json is missing (copy config.example.json and fill it in)")
        for key in ("program_dir", "export_dir"):
            p = pathlib.Path(self.cfg.get(key) or "")
            if not p.is_dir():
                raise DeviceFault(f"{key} {p} is not reachable (a share to the CrystalClear PC must be mounted)", {"transient": True})

    def write_program(self, name: str, program: dict, blocks: list[str]) -> str:
        path = pathlib.Path(self.cfg["program_dir"]) / f"{name}.csv"
        lines = [f"Crystal16 Temperature Program,{name}", f"Blocks,{''.join(blocks)}", "Temperature Program"]
        for b in blocks:
            lines += program_lines(program, b)
        tmp = path.with_suffix(".tmp")
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        tmp.replace(path)
        return str(path)

    def exports(self, since: float) -> list[pathlib.Path]:
        folder = pathlib.Path(self.cfg["export_dir"])
        return sorted(f for f in folder.rglob("*.csv") if f.is_file() and f.stat().st_mtime >= since)

    def read(self, path: pathlib.Path) -> str:
        return path.read_text(encoding="utf-8", errors="replace")


class Device(Driver):
    def setup(self) -> None:
        self.cfg = load_config()
        self.hw = None
        self.is_running = False
        self.last_result = None
        self.stirrer_rpm = None
        self.program_started = None

    def make_backend(self):
        return CrystalClearFiles(self.cfg)

    def time_scale(self) -> float:
        return 1.0

    def _hw(self):
        if self.hw is None:
            hw = self.make_backend()
            try:
                hw.open()
            except DeviceFault:
                raise
            except Exception as e:                            # noqa: BLE001
                raise DeviceFault(f"cannot reach the CrystalClear folders: {type(e).__name__}: {e}") from None
            self.hw = hw
        return self.hw

    def _latest_rows(self) -> dict[str, dict]:
        """The last data row of the newest export per block, if the software writes exports live (unverified)."""
        hw = self._hw()
        since = self.program_started or (time.time() - 86400)
        out: dict[str, dict] = {}
        for f in hw.exports(since):
            try:
                parsed = parse_export(hw.read(f))
            except (OSError, csv.Error):
                continue
            block = next((l.split(",", 1)[1].strip() for l in parsed["program"] if l.startswith("Block,")), None)
            if block and parsed["data"]:
                out[block] = parsed["data"][-1]
        return out

    def on_read(self, name: str):
        if name == "connected":
            try:
                self._hw()
                return True
            except DeviceFault:
                return False
        if name == "running":
            return self.is_running
        if name == "last_result":
            return self.last_result
        if name == "stirrer_rpm":
            rows = self._latest_rows()
            vals = [_num(r.get("Stirring Rate [rpm]")) for r in rows.values()]
            vals = [v for v in vals if v is not None]
            return max(vals) if vals else self.stirrer_rpm
        if name.startswith("block_") and name.endswith("_temperature"):
            block = name[6].upper()
            row = self._latest_rows().get(block)
            return _num(row.get("Temperature Actual [°C]")) if row else None
        raise InvalidValue(f"unknown signal {name}")

    def on_write(self, name: str, value):
        if name != "stirrer_rpm":
            raise InvalidValue(f"unknown setting {name}")
        self.stirrer_rpm = float(value)
        return {"note": "used by the next run_program whose program has no stirrer_rpm; CrystalClear has no live setpoint route"}

    def validate_params(self, action: str, params: dict) -> None:
        if action != "run_program":
            return
        prog = params["program"]
        if not prog["steps"]:
            raise InvalidValue("run_program.program.steps must hold at least one step")
        for i, s in enumerate(prog["steps"]):
            if s["action"] in ("heat", "cool") and s.get("rate_k_min") is None:
                raise InvalidValue(f"steps[{i}]: a {s['action']} step needs rate_k_min")
            if s["action"] == "hold" and s.get("hold_min") is None:
                raise InvalidValue(f"steps[{i}]: a hold step needs hold_min")
        if prog.get("stirrer_rpm") is None and self.stirrer_rpm is None:
            raise InvalidValue("run_program: give program.stirrer_rpm or write the stirrer_rpm setting first")
        if program_duration_min(prog) > params["timeout_h"] * 60:
            raise InvalidValue(f"run_program: the program takes about {program_duration_min(prog):.0f} min, longer than timeout_h")
        if params.get("name") is not None and not re.fullmatch(r"[A-Za-z0-9 _.\-]+", params["name"]):
            raise InvalidValue("run_program.name must be a plain file name")

    def on_invoke(self, job: Job):
        hw = self._hw()
        if job.action != "run_program":
            raise InvalidValue(f"unhandled action {job.action}")
        p = job.params
        prog = dict(p["program"])
        if prog.get("stirrer_rpm") is None:
            prog["stirrer_rpm"] = self.stirrer_rpm
        blocks = p["blocks"]
        name = p.get("name") or f"mhp_{time.strftime('%Y%m%d_%H%M%S')}_{job.id}"
        started = time.time()
        scale = self.time_scale()
        path = hw.write_program(name, prog, blocks)
        self.program_started = started - 1
        self.is_running = True
        expected = program_duration_min(prog) * 60 * scale
        limit = p["timeout_h"] * 3600 * scale
        poll = max(0.02, min(5.0, 10 * scale))
        t0, files = time.monotonic(), []
        try:
            while True:
                try:
                    self.checkpoint(job, min(0.95, (time.monotonic() - t0) / max(expected, 1e-9) * 0.9), phase="temperature program")
                except JobCancelled:
                    raise
                files = [f for f in hw.exports(started - 1) if name in f.name]
                if len(files) >= len(blocks):
                    time.sleep(min(2.0, 2 * scale) if scale < 1 else 2.0)
                    break
                if time.monotonic() - t0 > limit:
                    raise DeviceFault(f"no export for {name} appeared in export_dir within {p['timeout_h']} h; "
                                      "did CrystalClear import and run the program, and is auto-export on?")
                time.sleep(poll)
        finally:
            self.is_running = False
        reactors = []
        for f in files:
            parsed = parse_export(hw.read(f))
            block = next((l.split(",", 1)[1].strip() for l in parsed["program"] if l.startswith("Block,")), "?")
            offset = BLOCKS.index(block) * REACTORS_PER_BLOCK if block in BLOCKS else 0
            for k in range(1, REACTORS_PER_BLOCK + 1):
                col = f"Reactor{k} Transmission [%]"
                if col not in parsed["columns"]:
                    continue
                tr = transitions(parsed["data"], col)
                reactors.append({"reactor": offset + k, "block": block, **tr,
                                 "description": parsed["meta"].get(f"Reactor{k}") or None})
        reactors.sort(key=lambda r: r["reactor"])
        result = {"program_file": path, "duration_s": round((time.time() - started) / scale, 1), "blocks": blocks,
                  "reactors": reactors, "csv": [f.name for f in files]}
        self.last_result = result
        self.emit_signal("last_result", result)
        return result

    # ---- setup-time check (`mhp node setup`) ---------------------------------------------- #
    @classmethod
    def probe(cls, cfg: dict) -> str:
        hw = CrystalClearFiles(cfg)
        hw.open()
        n = len(list(pathlib.Path(cfg["export_dir"]).rglob("*.csv")))
        return f"program folder {cfg['program_dir']} and export folder {cfg['export_dir']} are reachable; {n} csv export(s) present"
