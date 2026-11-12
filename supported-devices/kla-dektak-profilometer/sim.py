"""Simulated twin of the Vision64 route: a fake control server that answers the command strings, runs a scan for
the requested duration (scaled), then writes the .OPDx file (the 12-byte VCA DATA header followed by a small
payload) and appends a database CSV row with a step height from a model of a 500 nm film step."""
from __future__ import annotations

import importlib.util
import os
import pathlib
import random
import sys
import tempfile
import time

_spec = importlib.util.spec_from_file_location(__name__ + "_real", pathlib.Path(__file__).with_name("driver.py"))
real = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = real
_spec.loader.exec_module(real)

STEP_NM = 500.0


class FakeServer:
    """Answers the line protocol the backend assumes; holds the tower/scan state and writes the result files."""

    def __init__(self, cfg, scale):
        self.cfg, self.scale = cfg, scale
        self.online = True
        self.state = "idle"
        self.fields: dict[str, str] = {}
        self.recipe = None
        self.scan_end = None
        self.log: list[str] = []

    def _tick(self):
        if self.state == "scanning" and time.monotonic() >= self.scan_end:
            self._finish()

    def _finish(self):
        self.state = "idle"
        name = pathlib.Path(self.fields.get("AutoSaveFileName", "scan.OPDx")).stem
        out = pathlib.Path(self.cfg["data_dir"]) / (name + ".OPDx")
        n = max(10, int(float(self.fields.get("Duration", "10")) * 300))
        out.write_bytes(real.OPDX_MAGIC + (8).to_bytes(4, "little") + b"/MetaData" + bytes([0x7D]) + n.to_bytes(4, "little"))
        force = float(self.fields.get("Force", "3"))
        step = STEP_NM * (1 - 0.004 * max(0.0, force - 3)) + random.gauss(0, 1.5)
        db = pathlib.Path(self.cfg["db_csv"])
        if not db.exists():
            db.write_text("Date,Time,Sample ID,Recipe,Scan Length (um),Stylus Force (mg),ASH\r\n", encoding="utf-8")
        with db.open("a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d')},{time.strftime('%H:%M:%S')},{self.fields.get('SampleID', '')},{self.recipe},"
                    f"{self.fields.get('Length', '')},{self.fields.get('Force', '')},{step:.2f}\r\n")
        self.log.append(f"scan done: {out.name}, ASH {step:.1f} nm")

    def answer(self, line: str) -> str:
        self._tick()
        parts = line.split(" ", 2)
        cmd = parts[0].upper()
        if cmd == "STATUS":
            return "OK " + self.state.upper()
        if cmd == "LOAD_RECIPE":
            self.recipe = pathlib.PureWindowsPath(parts[1] if len(parts) > 1 else "").name
            return "OK"
        if cmd == "SET" and len(parts) == 3:
            self.fields[parts[1]] = parts[2]
            return "OK"
        if cmd == "RUN":
            if self.state != "idle":
                return "ERR busy"
            if self.recipe is None:
                return "ERR no recipe"
            self.state = "scanning"
            self.scan_end = time.monotonic() + (float(self.fields.get("Duration", "10")) + 5) * self.scale
            return "OK"
        if cmd == "ABORT":
            self.state = "idle"
            self.scan_end = None
            return "OK"
        if cmd == "TOWER_HOME":
            return "OK"
        return "ERR unknown command"


class SimBackend(real.VisionBackend):
    def __init__(self, cfg, scale):
        super().__init__(cfg)
        self.server = FakeServer(cfg, scale)

    def open(self) -> None:
        if not self.server.online:
            raise real.DeviceFault("twin offline", {"transient": True})
        self.status()

    def send(self, line: str) -> str:
        reply = self.server.answer(line)
        self.log.append(f"{line} -> {reply}")
        if reply.upper().startswith(("ERR", "NAK")):
            raise real.DeviceFault(f"Vision64 refused {line.split()[0]}: {reply}", {"transient": False, "recovery": "operator"})
        return reply

    def close(self) -> None:
        pass


class SimDektakVision(real.DektakVision):
    def setup(self) -> None:
        super().setup()
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        base = os.environ.get("OPENMHP_HOME") or tempfile.gettempdir()
        pathlib.Path(base).mkdir(parents=True, exist_ok=True)
        root = pathlib.Path(tempfile.mkdtemp(prefix="kla-dektak-", dir=base))
        (root / "data").mkdir()
        self.cfg = {"host": "sim", "port": 0, "data_dir": str(root / "data"), "db_csv": str(root / "db.csv"), "recipes_dir": "",
                    "step_height_unit": "nm", "max_duration_s": 600, "result_wait_s": 120, "poll_s": 1}

    def time_scale(self) -> float:
        return self.scale

    def make_backend(self):
        return SimBackend(self.cfg, self.scale)
