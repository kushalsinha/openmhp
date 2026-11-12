"""Simulated twin of the Neware BTS server: the same XML command protocol answered in software, with a
coin cell on each of eight channels. Time runs at OPENMHP_SIM_TIME_SCALE real seconds per simulated
second (default 0.01).

The cell is a 45 mAh lithium-ion coin cell (3.0-4.2 V) with a 2 ohm internal resistance: CC charge raises
the state of charge until the voltage limit, CV charge holds the voltage while the current decays to the
cut-off, CC discharge runs down to the lower limit, rest sits at open circuit. Each step also ends on its
time or capacity limit; the cycle counter increments after the last step of each pass. A channel reports
`working` while running, then `finish`; `protect` if a limit above 4.3 V or below 2.5 V is asked for.
"""
from __future__ import annotations

import importlib.util
import os
import pathlib
import re
import sys
import time
import xml.etree.ElementTree as ET

_spec = importlib.util.spec_from_file_location(__name__ + "_real", pathlib.Path(__file__).with_name("driver.py"))
real = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = real
_spec.loader.exec_module(real)

CAP_AH = 0.045
R_OHM = 2.0


def ocv(soc: float) -> float:
    soc = min(1.0, max(0.0, soc))
    return 3.0 + 1.2 * soc ** 0.8


class CoinCell:
    def __init__(self, scale: float):
        self.scale = scale
        self.soc = 0.3
        self.t = time.monotonic()
        self.status = "stop"
        self.steps: list[dict] = []
        self.cycles = 1
        self.idx, self.cycle, self.step_t, self.step_q, self.run_t = 0, 0, 0.0, 0.0, 0.0
        self.v, self.i = ocv(self.soc), 0.0
        self.barcode = ""

    def start(self, steps, cycles, barcode):
        self.steps, self.cycles, self.barcode = steps, cycles, barcode
        self.idx, self.cycle, self.step_t, self.step_q, self.run_t = 0, 0, 0.0, 0.0, 0.0
        if any((s.get("voltage_v") or 0) > 4.3 or (s["mode"] == "cc_discharge" and (s.get("voltage_v") or 3.0) < 2.5) for s in steps):
            self.status = "protect"
            return
        self.status = "working"
        self.t = time.monotonic()

    def stop(self):
        if self.status == "working":
            self.status = "stop"
        self.i = 0.0

    def _advance(self, dt: float) -> None:
        s = self.steps[self.idx]
        mode, cur, volt = s["mode"], s.get("current_a"), s.get("voltage_v")
        if mode == "cc_charge":
            self.i = cur
            self.soc += self.i * dt / 3600 / CAP_AH
            self.v = ocv(self.soc) + self.i * R_OHM
            done = volt is not None and self.v >= volt
        elif mode == "cv_charge":
            self.v = volt
            self.i = max(0.0, (volt - ocv(self.soc)) / R_OHM)
            self.soc += self.i * dt / 3600 / CAP_AH
            done = cur is not None and self.i <= cur
        elif mode == "cc_discharge":
            self.i = -cur
            self.soc += self.i * dt / 3600 / CAP_AH
            self.v = ocv(self.soc) + self.i * R_OHM
            done = volt is not None and self.v <= volt
        else:
            self.i = 0.0
            self.v = ocv(self.soc)
            done = False
        self.soc = min(1.05, max(-0.05, self.soc))
        self.step_t += dt
        self.step_q += abs(self.i) * dt / 3600
        self.run_t += dt
        if s.get("time_limit_s") is not None and self.step_t >= s["time_limit_s"]:
            done = True
        if s.get("capacity_limit_ah") is not None and self.step_q >= s["capacity_limit_ah"]:
            done = True
        if done:
            self.last_step_q = self.step_q
            self.idx += 1
            self.step_t = self.step_q = 0.0
            if self.idx >= len(self.steps):
                self.idx, self.cycle = 0, self.cycle + 1
                if self.cycle >= self.cycles:
                    self.status, self.i = "finish", 0.0

    def tick(self):
        now = time.monotonic()
        dt = (now - self.t) / self.scale
        self.t = now
        if self.status != "working":
            self.v = ocv(self.soc)
            return
        while dt > 0 and self.status == "working":
            h = min(dt, 1.0)
            self._advance(h)
            dt -= h

    def record(self) -> dict:
        self.tick()
        q = getattr(self, "last_step_q", self.step_q) if self.status != "working" else self.step_q
        return {"workstatus": self.status, "voltage": f"{self.v:.4f}", "current": f"{self.i * 1000:.3f}",
                "capacity": f"{q * 1000:.3f}", "cycle": str(self.cycle), "step": str(self.idx + 1), "time": f"{self.run_t:.1f}"}


class SimBackend(real.NewareBackend):
    """Answers the XML protocol without a socket; eight channels of one device."""

    def __init__(self, cfg: dict, scale: float):
        super().__init__(cfg)
        self.scale = scale
        self.cells = {f"1-1-{n}": CoinCell(scale) for n in range(1, 9)}

    def open(self) -> None:
        self.log.append("connect")
        self.channels = self.devinfo()

    def command(self, body: str, timeout: float = 30) -> str:
        cmd = body.split("</cmd>")[0].replace("<cmd>", "")
        self.log.append(cmd)
        root = ET.fromstring(real.HEAD + body + real.TAIL)
        if cmd == "getdevinfo":
            items = "".join(f'<chl ip="127.0.0.1" devtype="27" devid="1" subdevid="1" Channelid="{n}" />' for n in range(1, 9))
            return f'{real.HEAD}<cmd>getdevinfo</cmd><middle count="8">{items}</middle>{real.TAIL}'
        if cmd == "connect":
            return f"{real.HEAD}<cmd>connect</cmd><result>ok</result>{real.TAIL}"
        lst = root.find("list")
        out = []
        for el in (lst if lst is not None else []):
            if el.tag == "backup":
                continue
            pipe = f"{el.attrib.get('devid')}-{el.attrib.get('subdevid')}-{el.attrib.get('chlid')}"
            cell = self.cells.get(pipe)
            attrs = " ".join(f'{k}="{v}"' for k, v in el.attrib.items() if k in ("ip", "devtype", "devid", "subdevid", "chlid"))
            if cell is None:
                out.append(f"<{el.tag} {attrs}>false</{el.tag}>")
            elif cmd in ("inquire", "getchlstatus"):
                rec = cell.record()
                extra = " ".join(f'{k}="{v}"' for k, v in rec.items())
                out.append(f"<{el.tag} {attrs} {extra}>true</{el.tag}>")
            elif cmd == "start":
                cell.tick()
                if cell.status in real.IDLE_STATES:
                    try:
                        steps, cycles = real.parse_step_file(pathlib.Path(el.text.strip()).read_text(encoding="utf-8"))
                        cell.start(steps, cycles, el.attrib.get("barcode", ""))
                        out.append(f"<start {attrs}>ok</start>")
                    except (OSError, ET.ParseError, KeyError):
                        out.append(f"<start {attrs}>false</start>")
                else:
                    out.append(f"<start {attrs}>false</start>")
            elif cmd == "stop":
                cell.tick(); cell.stop()
                out.append(f"<stop {attrs}>ok</stop>")
            else:
                out.append(f"<{el.tag} {attrs}>false</{el.tag}>")
        return f'{real.HEAD}<cmd>{cmd}</cmd><list count="{len(out)}">{"".join(out)}</list>{real.TAIL}'


class Sim(real.Device):
    def setup(self) -> None:
        super().setup()
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        home = pathlib.Path(os.environ.get("OPENMHP_HOME", pathlib.Path.home() / ".openmhp"))
        step_dir = home / "sim-data" / "neware-battery-cycler" / "steps"
        self.cfg = {"host": "sim", "port": 502, "user": "admin", "step_dir": str(step_dir), "step_dir_on_server": str(step_dir),
                    "backup_dir": str(home / "sim-data" / "neware-battery-cycler" / "data"), "default_channel": "1-1-1",
                    "voltage_max_v": 4.35, "voltage_min_v": 2.4, "current_max_a": 1.0, "max_steps": 64,
                    "poll_s": 10, "max_run_hours": 240, "voltage_scale": 1.0, "current_scale": 0.001, "capacity_scale": 0.001}
        self.channel = "1-1-1"

    def time_scale(self) -> float:
        return self.scale

    def make_backend(self):
        return SimBackend(self.cfg, self.scale)
