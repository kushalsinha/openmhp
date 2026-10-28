"""MHP driver for a Cytiva ÄKTA avant through the UNICORN OPC Data Access server (Windows, OpenOPC).

Item names and behaviour follow the UNICORN 7.6 OPC Manual; see references/opc_items.md.
The OPC client sits behind a small interface (read, write, browse) so the simulated twin can
replace it.
"""
from __future__ import annotations

import json
import pathlib
import time

from openmhp.driver import DeviceFault, Driver, InvalidValue, Job, JobCancelled, LimitViolation

HERE = pathlib.Path(__file__).parent
COMMAND = {"pause": 0, "hold": 1, "continue_run": 2, "end_run": 3}
RUN_STATES = ["Ready", "Method Run", "System Pause", "Hold", "Pause Hold", "Hold Pause", "Manual Pause", "Wash",
              "Alarms and errors", "Initializing system", "Resetting", "Starting method run", "Starting manual run"]
ACTIVE = {"Method Run", "System Pause", "Hold", "Pause Hold", "Hold Pause", "Manual Pause", "Wash", "Starting method run"}


def load_config() -> dict:
    p = HERE / "config.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


class UnicornOPC:
    """OpenOPC (classic OPC DA over COM) on the UNICORN instrument PC."""

    def __init__(self, cfg: dict):
        self.cfg = cfg

    def open(self) -> None:
        if not self.cfg.get("progid"):
            raise DeviceFault("config.json is missing (copy config.example.json and fill it in)")
        try:
            import OpenOPC
        except ImportError:
            from openopc2 import da_com as OpenOPC          # noqa: N812  newer fork, same client API
        self.opc = OpenOPC.client()
        self.opc.connect(self.cfg["progid"], self.cfg.get("host", "localhost"))

    def read(self, item: str):
        value, quality, _ = self.opc.read(item, sync=True)
        if quality != "Good":
            raise DeviceFault(f"OPC item {item!r} quality {quality}")
        return value

    def write(self, item: str, value) -> None:
        status = self.opc.write((item, value))
        if status not in ("Success", True, None):
            raise DeviceFault(f"OPC write {item!r} = {value!r} failed: {status}")
        time.sleep(0.2)                                     # Cytiva: writes can arrive out of order if rushed

    def browse(self, path: str) -> list[str]:
        return [str(x) for x in self.opc.list(path)]

    def properties(self, item: str) -> dict:
        out = {}
        for pid, desc, value in self.opc.properties(item):
            out[desc] = value
        return out


class AktaAvant(Driver):
    def setup(self) -> None:
        self.cfg = load_config()
        self.hw = None
        self.last_result = None
        self.last_live = None

    def make_backend(self):
        return UnicornOPC(self.cfg)

    def time_scale(self) -> float:
        return 1.0

    def _hw(self):
        if self.hw is None:
            hw = self.make_backend()
            try:
                hw.open()
            except Exception as e:                          # noqa: BLE001
                raise DeviceFault(f"cannot reach the UNICORN OPC server: {type(e).__name__}: {e}") from None
            self.hw = hw
        return self.hw

    # ---- reads ------------------------------------------------------------------------------
    def _run_state(self) -> str:
        v = self._hw().read("STATE\\RunState")
        return RUN_STATES[v] if isinstance(v, int) and 0 <= v < len(RUN_STATES) else str(v)

    def _snapshot(self) -> dict:
        snap = {"run_state": self._run_state()}
        for name in ("uv_mAU", "conductivity_mS_cm", "pressure_MPa", "flow_ml_min"):
            snap[name] = self.on_read(name)
        for name in ("current_method", "current_result", "current_block"):
            snap[name] = self.on_read(name)
        return snap

    def on_read(self, name: str):
        if name == "connected":
            try:
                self._hw()
                return True
            except DeviceFault:
                return False
        if name == "in_control":
            return self._hw().read("STATE\\AssignState") == 1
        if name == "run_state":
            return self._run_state()
        if name in ("current_method", "current_result", "current_block"):
            key = {"current_method": "CurrentMethod", "current_result": "CurrentResult", "current_block": "CurrentBlock"}[name]
            try:
                return str(self._hw().read(f"Event\\Curves\\{key}"))
            except DeviceFault:
                return None
        if name in ("uv_mAU", "conductivity_mS_cm", "pressure_MPa", "flow_ml_min"):
            item = (self.cfg.get("items") or {}).get(name)
            if not item:
                return None
            v = self._hw().read(item)
            return round(float(v), 4) if isinstance(v, (int, float)) else v
        if name == "live":
            return self.last_live
        if name == "last_result":
            return self.last_result
        raise InvalidValue(f"unknown signal {name}")

    # ---- methods ------------------------------------------------------------------------------
    def _method_paths(self) -> dict[str, str]:
        """method name -> OPC branch, for every method under method_root (one folder level deep)."""
        hw, root, out = self._hw(), self.cfg.get("method_root", "\\Method\\DefaultHome"), {}
        for folder in hw.browse(root):
            for method in hw.browse(f"{root}\\{folder}"):
                out[method] = f"{root}\\{folder}\\{method}"
        allowed = self.cfg.get("allowed_methods") or []
        return {k: v for k, v in out.items() if not allowed or k in allowed}

    def _variables(self, path: str) -> dict[str, dict]:
        hw, out = self._hw(), {}
        try:
            names = hw.browse(f"{path}\\Method Variable(s)")
        except Exception:                                   # noqa: BLE001  method without variables
            return out
        for n in names:
            props = hw.properties(f"{path}\\Method Variable(s)\\{n}")
            out[n] = {"unit": props.get("Unit") or props.get("EU unit"), "min": props.get("Minimum value"),
                      "max": props.get("Maximum value"), "default": props.get("Default value"),
                      "value": props.get("Current value"), "description": props.get("Description")}
        return out

    def _questions(self, path: str) -> list[str]:
        try:
            return self._hw().browse(f"{path}\\Question(s)")
        except Exception:                                   # noqa: BLE001
            return []

    def validate_params(self, action: str, params: dict) -> None:
        if action != "run_method":
            return
        for key in ("method", "result_name"):
            if not isinstance(params.get(key), str) or not params[key].strip() or "\\" in params[key]:
                raise InvalidValue(f"run_method.{key} must be a plain, non-empty name")
        for key in ("variables", "questions"):
            if params.get(key) is not None and not isinstance(params[key], dict):
                raise InvalidValue(f"run_method.{key} must be an object")
        # checked against UNICORN before anything is written, in dry runs too
        path = self._method_paths().get(params["method"])
        if path is None:
            raise InvalidValue(f"method {params['method']!r} is not available or not allowed; see list_methods")
        known = self._variables(path)
        for name, value in (params.get("variables") or {}).items():
            spec = known.get(name)
            if spec is None:
                raise InvalidValue(f"{params['method']} has no Start Protocol variable {name!r}; available: {sorted(known)}")
            lo, hi = spec.get("min"), spec.get("max")
            if isinstance(value, (int, float)) and ((lo is not None and value < lo) or (hi is not None and value > hi)):
                raise LimitViolation(f"run_method.variables[{name!r}]={value} outside UNICORN's range {lo}..{hi}",
                                     {"min": lo, "max": hi})

    def _take_control(self) -> None:
        hw = self._hw()
        if hw.read("STATE\\AssignState") != 1:
            hw.write("STATE\\AssignState", 1)
            if hw.read("STATE\\AssignState") != 1:
                who = None
                try:
                    who = hw.read("STATE\\UserInControl")
                except DeviceFault:
                    pass
                raise DeviceFault(f"UNICORN did not grant control{f'; {who} holds the system' if who else ''}")

    def on_invoke(self, job: Job):
        hw = self._hw()
        if job.action == "list_methods":
            return {"methods": [{"name": n, "variables": self._variables(p), "questions": self._questions(p)}
                                for n, p in sorted(self._method_paths().items())]}
        if job.action in COMMAND:
            self._take_control()
            hw.write("STATE\\Command", COMMAND[job.action])
            return {"command": job.action, "run_state": self._run_state()}
        if job.action != "run_method":
            raise InvalidValue(f"unhandled action {job.action}")

        p = job.params
        path = self._method_paths()[p["method"]]
        state = self._run_state()
        if state != "Ready" and not p.get("queue"):
            raise DeviceFault(f"system is not Ready (run state {state}); pass queue: true to let UNICORN queue it")

        self._take_control()
        for name, value in (p.get("variables") or {}).items():
            hw.write(f"{path}\\Method Variable(s)\\{name}", value)
        for q, answer in (p.get("questions") or {}).items():
            hw.write(f"{path}\\Question(s)\\{q}", answer)
        if p.get("batch_id"):
            hw.write(f"{path}\\Batch ID", p["batch_id"])
        hw.write(f"{path}\\Result Name", p["result_name"])
        started = time.time()
        hw.write(f"{path}\\Run Method", 1)

        live_every = float(self.cfg.get("live_every_s", 5)) * self.time_scale()
        deadline = time.monotonic() + 120 * max(self.time_scale(), 0.05)
        seen_active, snap, next_live = False, {}, 0.0
        while True:
            try:
                self.checkpoint(job, phase="method run")
            except JobCancelled:
                hw.write("STATE\\Command", COMMAND["end_run"])
                raise
            snap = self._snapshot()
            state = snap["run_state"]
            if state == "Alarms and errors":
                raise DeviceFault(f"UNICORN reports alarms during {p['method']}; a person must check the system. Last: {snap}")
            if state in ACTIVE:
                seen_active = True
            elif state == "Ready" and seen_active:
                break
            elif not seen_active and time.monotonic() > deadline:
                raise DeviceFault(f"{p['method']} did not start (run state {state}); check result name and mandatory questions")
            if time.monotonic() >= next_live:
                next_live = time.monotonic() + live_every
                self.last_live = {"t_s": round((time.time() - started) / self.time_scale(), 1), **snap}
                self.emit_signal("live", self.last_live)
            time.sleep(min(1.0, live_every / 2))
        result = {"method": p["method"], "result_name": p["result_name"], "variables": p.get("variables") or {},
                  "duration_s": round((time.time() - started) / self.time_scale(), 1),
                  "last_live": self.last_live, "final": snap,
                  "note": "Chromatogram and peak table are stored in UNICORN under result_name."}
        self.last_result = result
        self.emit_signal("last_result", result)
        return result

    def on_estop(self) -> None:
        try:
            if self.hw is not None:
                self.hw.write("STATE\\AssignState", 1)
                self.hw.write("STATE\\Command", COMMAND["pause"])
        except Exception:                                   # noqa: BLE001  must not raise
            pass
