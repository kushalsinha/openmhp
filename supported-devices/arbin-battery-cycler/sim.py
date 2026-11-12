"""Simulated twin of the Arbin file route: a fake MITS Pro PC that starts the queued test at once and exports a
CSV in the documented column layout when the protocol ends. Time scaled by OPENMHP_SIM_TIME_SCALE.

The cell is a 45 mAh lithium-ion coin cell (3.0-4.2 V, 2 ohm): the twin integrates the requested steps at
10 s resolution (CC charge to the voltage limit, CV hold to the cut-off current, CC discharge to the lower limit,
rest) for the requested cycles, writes one row per sample with Test_Time(s), Step_Time(s), Step_Index,
Cycle_Index, Current(A), Voltage(V), Charge_Capacity(Ah), Discharge_Capacity(Ah) (capacities cumulative within
a step, as MITS Pro exports them), and names the file <barcode>_mhp_<job>.csv.
"""
from __future__ import annotations

import csv
import importlib.util
import json
import os
import pathlib
import sys
import time

_spec = importlib.util.spec_from_file_location(__name__ + "_real", pathlib.Path(__file__).with_name("driver.py"))
real = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = real
_spec.loader.exec_module(real)

CAP_AH, R_OHM, DT = 0.045, 2.0, 10.0


def ocv(soc: float) -> float:
    return 3.0 + 1.2 * min(1.0, max(0.0, soc)) ** 0.8


def simulate(steps: list[dict], cycles: int) -> list[list]:
    """Rows of (test_time, step_time, step_index, cycle_index, current, voltage, qc, qd)."""
    soc, t, rows = 0.3, 0.0, []
    for cyc in range(1, cycles + 1):
        for idx, s in enumerate(steps, 1):
            mode, cur, volt = s["mode"], s.get("current_a"), s.get("voltage_v")
            st, qc, qd = 0.0, 0.0, 0.0
            while True:
                if mode == "cc_charge":
                    i = cur; soc += i * DT / 3600 / CAP_AH; v = ocv(soc) + i * R_OHM; done = volt is not None and v >= volt
                elif mode == "cv_charge":
                    v = volt; i = max(0.0, (volt - ocv(soc)) / R_OHM); soc += i * DT / 3600 / CAP_AH; done = i <= cur
                elif mode == "cc_discharge":
                    i = -cur; soc += i * DT / 3600 / CAP_AH; v = ocv(soc) + i * R_OHM; done = volt is not None and v <= volt
                else:
                    i, v, done = 0.0, ocv(soc), False
                soc = min(1.05, max(-0.05, soc))
                st += DT; t += DT
                qc += max(i, 0.0) * DT / 3600; qd += max(-i, 0.0) * DT / 3600
                rows.append([round(t, 1), round(st, 1), idx, cyc, round(i, 6), round(v, 4), round(qc, 6), round(qd, 6)])
                if s.get("time_limit_s") is not None and st >= s["time_limit_s"]:
                    done = True
                if s.get("capacity_limit_ah") is not None and max(qc, qd) >= s["capacity_limit_ah"]:
                    done = True
                if done or st > 48 * 3600:
                    break
    return rows


class SimBackend(real.ArbinBackend):
    def __init__(self, cfg: dict, scale: float):
        super().__init__(cfg)
        self.scale = scale
        self.folders_ok = True
        self.hold = False                               # True: nobody at the console starts the test
        self.due: dict[str, float] = {}
        self.running: set[str] = set()

    def open(self) -> None:
        if not self.folders_ok:
            raise real.DeviceFault("simulated: the MITS Pro share is unreachable", {"transient": True, "recovery": "retry_after"})
        for key in ("request_dir", "results_dir"):
            pathlib.Path(self.cfg[key]).mkdir(parents=True, exist_ok=True)
        super().open()

    def channel_state(self, channel: str) -> str:
        if channel in self.running:
            return "running"
        return super().channel_state(channel)

    def write_request(self, token: str, params: dict) -> str:
        path = super().write_request(token, params)
        rows = simulate(params["steps"], int(params["cycles"]))
        self.due[token] = time.monotonic() + (rows[-1][0] if rows else 0.0) * self.scale
        self.running.add(params["channel"])
        return path

    def poll(self) -> None:
        if self.hold:
            return
        for token, when in list(self.due.items()):
            if time.monotonic() < when:
                continue
            req_path = pathlib.Path(self.cfg["request_dir"]) / f"{token}.json"
            try:
                req = json.loads(req_path.read_text(encoding="utf-8"))
                self._export(req)
                req_path.unlink()
                self.running.discard(req["channel"])
            except OSError:                             # withdrawn: nobody started it
                pass
            del self.due[token]

    def _export(self, req: dict) -> None:
        out = pathlib.Path(self.cfg["results_dir"]) / req["export"]
        tmp = out.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Data_Point", "Test_Time(s)", "Step_Time(s)", "Step_Index", "Cycle_Index", "Current(A)", "Voltage(V)",
                        "Charge_Capacity(Ah)", "Discharge_Capacity(Ah)"])
            for n, row in enumerate(simulate(req["steps"], int(req["cycles"])), 1):
                w.writerow([n, *row])
        tmp.replace(out)
        self.log.append(f"export {out.name}")


class Sim(real.Device):
    def setup(self) -> None:
        super().setup()
        self.scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
        home = pathlib.Path(os.environ.get("OPENMHP_HOME", pathlib.Path.home() / ".openmhp"))
        root = home / "sim-data" / "arbin-battery-cycler"
        self.cfg = {"request_dir": str(root / "requests"), "results_dir": str(root / "results"), "software": "SIM MITS Pro 8",
                    "default_channel": "1", "allowed_schedules": [], "voltage_max_v": 4.3, "current_max_a": 1.0,
                    "result_wait_s": 1209600, "poll_s": 60}

    def time_scale(self) -> float:
        return self.scale

    def make_backend(self):
        return SimBackend(self.cfg, self.scale)
