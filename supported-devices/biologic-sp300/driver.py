"""MHP driver for a BioLogic SP-300 through easy-biologic (EC-Lab Development Package, Windows).

A technique runs in a backend "run" object that the driver polls: new data rows, alive, stop.
The driver owns the gates, the live relay, the potential-window abort and the CSV trace.
"""
from __future__ import annotations

import csv
import json
import pathlib
import threading
import time

from openmhp.driver import DeviceFault, Driver, InvalidValue, Job, JobCancelled, LimitViolation

HERE = pathlib.Path(__file__).parent
FIELDS = ("t_s", "ewe_V", "current_A", "cycle")


def load_config() -> dict:
    p = HERE / "config.json"
    return json.loads(p.read_text()) if p.is_file() else {}


class _ProgramRun:
    """One easy-biologic program running in a thread; rows are (t_s, ewe_V, current_A, cycle)."""

    def __init__(self, backend, program):
        self.backend, self.program, self.error, self._sent = backend, program, None, 0
        self.thread = threading.Thread(target=self._go, daemon=True)
        self.thread.start()

    def _go(self):
        try:
            self.program.run()
        except Exception as e:                        # noqa: BLE001
            self.error = f"{type(e).__name__}: {e}"

    def alive(self) -> bool:
        return self.thread.is_alive()

    def poll(self) -> list[tuple]:
        data = self.program.data.get(self.backend.channel, [])
        new, self._sent = data[self._sent:], len(data)
        return [(float(d.time), float(d.voltage), float(d.current), int(getattr(d, "cycle", 0) or 0)) for d in new]

    def stop(self) -> None:
        self.backend.dev.stop_channel(self.backend.channel)
        self.thread.join(timeout=15)


class BiologicBackend:
    def __init__(self, cfg: dict):
        self.cfg, self.channel = cfg, int(cfg.get("channel", 0))

    def open(self) -> None:
        if not self.cfg.get("address"):
            raise DeviceFault("config.json is missing (copy config.example.json and fill it in)")
        import easy_biologic as ebl
        from easy_biologic import base_programs as blp
        self.blp = blp
        self.dev = ebl.BiologicDevice(self.cfg["address"])
        self.dev.connect()

        class PulsedCP(blp.CP):                       # CP with N_Cycles exposed: [I_O for t_O, I_R for t_R] repeated
            def run(self, retrieve_data=True):
                params = {}
                for ch, p in self.params.items():
                    steps = len(p["currents"])
                    params[ch] = {"Current_step": p["currents"], "vs_initial": [False] * steps,
                                  "Duration_step": p["durations"], "Step_number": steps - 1,
                                  "Record_every_dT": p["time_interval"], "Record_every_dE": p["voltage_interval"],
                                  "N_Cycles": int(p.get("n_cycles", 0))}
                    params[ch].update(blp.map_hardware_params(p, by_channel=False))
                self._run("cp", params, retrieve_data=retrieve_data)
        self.PulsedCP = PulsedCP

    def values(self) -> tuple[float, float]:
        v = self.dev.get_values(self.channel)
        return float(v.Ewe), float(v.I)

    def start(self, kind: str, p: dict):
        kw = {"channels": [self.channel], "autoconnect": False}
        blp = self.blp
        if kind == "ocv":
            prog = blp.OCV(self.dev, {"time": p["duration_s"], "time_interval": p["record_dt_s"], "voltage_interval": 0.01}, **kw)
        elif kind == "cp":
            prog = self.PulsedCP(self.dev, {"currents": p["currents_A"], "durations": p["durations_s"], "n_cycles": p["n_cycles"],
                                            "time_interval": p["record_dt_s"], "voltage_interval": 0.05}, **kw)
        elif kind == "cv":
            prog = blp.CV(self.dev, {"start": p["e_start_V"], "end": p["e_vertex1_V"], "E2": p["e_vertex2_V"],
                                     "Ef": p["e_vertex2_V"], "rate": p["scan_rate_mV_s"] / 1000, "step": 0.001,
                                     "N_Cycles": p["cycles"] - 1}, **kw)
        else:
            raise InvalidValue(kind)
        return _ProgramRun(self, prog)

    def stop(self) -> None:
        self.dev.stop_channel(self.channel)


class SP300(Driver):
    def setup(self) -> None:
        self.cfg = load_config()
        self.hw = None
        self.is_running = False
        self.last_result = None
        self.last_live = None

    def make_backend(self):
        return BiologicBackend(self.cfg)

    def _hw(self):
        if self.hw is None:
            hw = self.make_backend()
            try:
                hw.open()
            except Exception as e:                    # noqa: BLE001
                raise DeviceFault(f"cannot open the SP-300: {type(e).__name__}: {e}") from None
            self.hw = hw
        return self.hw

    def on_read(self, name: str):
        if name == "connected":
            try:
                self._hw()
                return True
            except DeviceFault:
                return False
        if name == "running":
            return self.is_running
        if name == "ewe_V":
            return round(self._hw().values()[0], 4)
        if name == "current_mA":
            return round(self._hw().values()[1] * 1000, 4)
        if name == "live":
            return self.last_live
        if name == "last_result":
            return self.last_result
        raise InvalidValue(f"unknown signal {name}")

    def validate_params(self, action: str, params: dict) -> None:
        if action == "cp_pulsed":
            tr, to, dur = params.get("t_reduction_s"), params.get("t_oxidation_s"), params.get("duration_s")
            if all(isinstance(x, (int, float)) for x in (tr, to, dur)) and dur < tr + to:
                raise LimitViolation(f"cp_pulsed.duration_s={dur} is shorter than one cycle ({tr + to} s)")

    def _plan(self, job: Job) -> tuple[str, dict, float]:
        p = job.params
        if job.action == "ocv":
            return "ocv", {"duration_s": float(p["duration_s"]), "record_dt_s": float(p.get("record_dt_s", 1))}, float(p["duration_s"])
        if job.action == "cp_static":
            dur = float(p["duration_s"])
            return "cp", {"currents_A": [float(p["current_mA"]) / 1000], "durations_s": [dur], "n_cycles": 0,
                          "record_dt_s": float(p.get("record_dt_s", 1))}, dur
        if job.action == "cp_pulsed":
            tr, to = float(p["t_reduction_s"]), float(p["t_oxidation_s"])
            cycles = max(1, int(float(p["duration_s"]) // (tr + to)))
            return "cp", {"currents_A": [float(p["i_oxidation_mA"]) / 1000, float(p["i_reduction_mA"]) / 1000],
                          "durations_s": [to, tr], "n_cycles": cycles - 1,
                          "record_dt_s": float(p.get("record_dt_s", 0.1))}, cycles * (tr + to)
        if job.action == "cv":
            cyc = int(p.get("cycles", 1))
            span = abs(p["e_vertex1_V"] - p["e_start_V"]) + abs(p["e_vertex2_V"] - p["e_vertex1_V"])
            return "cv", {**{k: float(p[k]) for k in ("e_start_V", "e_vertex1_V", "e_vertex2_V", "scan_rate_mV_s")},
                          "cycles": cyc}, cyc * span / (float(p["scan_rate_mV_s"]) / 1000)
        raise InvalidValue(f"unhandled action {job.action}")

    @staticmethod
    def _median(xs: list[float]):
        if not xs:
            return None
        s = sorted(xs)
        return round(s[len(s) // 2], 4)

    def on_invoke(self, job: Job):
        hw = self._hw()
        kind, plan, expected_s = self._plan(job)
        lo, hi = self.cfg.get("ewe_abort_window_V", [-3.5, 1.5])
        live_every = float(self.cfg.get("live_every_s", 5))
        data_dir = pathlib.Path(self.cfg.get("data_dir") or HERE / "data")
        data_dir.mkdir(parents=True, exist_ok=True)
        path = data_dir / f"{time.strftime('%Y%m%d-%H%M%S')}_{job.action}_{job.id}.csv"
        n = 0
        charge_red = charge_ox = 0.0
        v_red: list[float] = []
        v_ox: list[float] = []
        recent_red: list[float] = []
        recent_ox: list[float] = []
        last = prev_t = None
        aborted = None
        run = hw.start(kind, plan)
        self.is_running = True
        next_live = time.monotonic() + live_every
        try:
            with path.open("w", newline="") as f:
                w = csv.writer(f)
                w.writerow(FIELDS)
                while True:
                    alive = run.alive()
                    rows = run.poll()
                    for t, v, i, cyc in rows:
                        w.writerow((round(t, 4), round(v, 5), i, cyc))
                        dt = (t - prev_t) if prev_t is not None and t > prev_t else 0.0
                        prev_t = t
                        if i < 0:
                            charge_red += -i * dt; v_red.append(v); recent_red.append(v)
                        elif i > 0:
                            charge_ox += i * dt; v_ox.append(v); recent_ox.append(v)
                        if kind != "ocv" and not lo <= v <= hi:
                            aborted = f"potential {v:.3f} V left the safe window {lo}..{hi} V at t={t:.1f} s"
                        last = (t, v, i, cyc)
                    n += len(rows)
                    if aborted:
                        run.stop()
                        break
                    if last and time.monotonic() >= next_live:
                        next_live = time.monotonic() + live_every
                        self.last_live = {"t_s": round(last[0], 2), "ewe_V": round(last[1], 4), "current_mA": round(last[2] * 1000, 3),
                                          "v_reduction_V": self._median(recent_red), "v_oxidation_V": self._median(recent_ox),
                                          "cycle": last[3], "points": n}
                        recent_red, recent_ox = [], []
                        self.emit_signal("live", self.last_live)
                    if not alive and not rows:
                        break
                    try:
                        self.checkpoint(job, min(0.99, (last[0] / expected_s) if last and expected_s else 0.0))
                    except JobCancelled:
                        run.stop()
                        raise
                    time.sleep(0.2)
        finally:
            self.is_running = False
        result = {"technique": job.action, "params": job.params, "points": n, "elapsed_s": round(last[0], 2) if last else 0,
                  "v_reduction_median_V": self._median(v_red), "v_oxidation_median_V": self._median(v_ox),
                  "charge_reduction_C": round(charge_red, 4), "charge_oxidation_C": round(charge_ox, 4),
                  "final_ewe_V": round(last[1], 4) if last else None, "trace_csv": str(path)}
        if kind == "cv":
            result.pop("charge_oxidation_C"); result.pop("charge_reduction_C")
        self.last_result = result
        self.emit_signal("last_result", result)
        if aborted:
            raise DeviceFault(f"run stopped: {aborted}. Trace kept at {path}")
        if run.error:
            raise DeviceFault(f"technique failed: {run.error}. Trace kept at {path}")
        return result

    def on_estop(self) -> None:
        try:
            if self.hw is not None:
                self.hw.stop()
        except Exception:                             # noqa: BLE001  must not raise
            pass
        self.is_running = False
