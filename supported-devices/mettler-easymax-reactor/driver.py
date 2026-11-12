"""MHP driver for a Mettler Toledo EasyMax 102/402 or OptiMax 1001 under iControl, through an OPC UA server.

Mettler publishes no node list for iControl's OPC interface. Every node id this package reads or writes is
therefore a config.json entry (`nodes`), shipped as placeholders marked unverified in references/opcua_nodes.md,
to be confirmed by browsing the server on the first hardware test. The OPC UA client sits behind OpcUaBackend
so the simulated twin can replace it.
"""
from __future__ import annotations

import json
import pathlib
import time

from openmhp.driver import DeviceFault, Driver, InvalidValue, Job, JobCancelled

HERE = pathlib.Path(__file__).parent
# the nodes the driver uses, each a key of config.json `nodes` (placeholder ids in config.example.json)
READ_NODES = ("tr", "tj", "stirrer_rpm", "stirrer_running", "dosing_total_ml", "ph", "phase", "connection_status")
WRITE_NODES = ("tr_setpoint", "tj_setpoint", "stirrer_setpoint", "ramp_rate", "thermostat_mode")
METHOD_NODES = ("object", "start_experiment", "end_experiment", "dose", "stop_dosing", "safe_state")
IDLE_MODE = 0                   # thermostat_mode value for "off / idle"   # unverified
TR_MODE, TJ_MODE = 1, 2         # thermostat_mode values for Tr and Tj control   # unverified


def load_config() -> dict:
    p = HERE / "config.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


class OpcUaBackend:
    """asyncua (sync wrapper) or python-opcua client; node ids come from config.json `nodes`."""

    def __init__(self, cfg: dict):
        self.cfg, self.nodes, self.client = cfg, dict(cfg.get("nodes") or {}), None

    def open(self) -> None:
        if not self.cfg.get("url"):
            raise DeviceFault("config.json is missing (copy config.example.json and fill it in)")
        try:
            from asyncua.sync import Client
        except ImportError:
            try:
                from opcua import Client
            except ImportError:
                raise DeviceFault("no OPC UA client is installed (pip install asyncua)") from None
        client = Client(self.cfg["url"])
        if self.cfg.get("username"):
            try:
                import keyring
                pw = keyring.get_password("iControlOPC", self.cfg["username"])
            except ImportError:
                pw = None
            client.set_user(self.cfg["username"])
            if pw:
                client.set_password(pw)
        try:
            client.connect()
        except Exception as e:                                   # noqa: BLE001
            raise DeviceFault(f"cannot connect to {self.cfg['url']}: {type(e).__name__}: {e}", {"transient": True}) from None
        self.client = client

    def _node(self, key: str):
        nid = self.nodes.get(key)
        if not nid:
            raise DeviceFault(f"config.json nodes.{key} is not set; browse the iControl OPC UA server and fill it in")
        return self.client.get_node(nid)

    def read(self, key: str):
        try:
            node = self._node(key)
            return node.read_value() if hasattr(node, "read_value") else node.get_value()
        except DeviceFault:
            raise
        except Exception as e:                                   # noqa: BLE001
            raise DeviceFault(f"OPC UA read of nodes.{key} ({self.nodes.get(key)}) failed: {type(e).__name__}: {e}",
                              {"transient": True}) from None

    def write(self, key: str, value) -> None:
        try:
            node = self._node(key)
            if hasattr(node, "write_value"):
                node.write_value(value)
            else:
                node.set_value(value)
        except DeviceFault:
            raise
        except Exception as e:                                   # noqa: BLE001
            raise DeviceFault(f"OPC UA write of nodes.{key} = {value!r} failed: {type(e).__name__}: {e}") from None

    def call(self, key: str, *args):
        """Call the method node `key` on the object node `object`; both optional in the config."""
        if not self.nodes.get(key) or not self.nodes.get("object"):
            return None                                         # the lab has not mapped this method
        try:
            return self._node("object").call_method(self._node(key), *args)
        except DeviceFault:
            raise
        except Exception as e:                                   # noqa: BLE001
            raise DeviceFault(f"OPC UA method nodes.{key} failed: {type(e).__name__}: {e}") from None

    def close(self) -> None:
        try:
            if self.client is not None:
                self.client.disconnect()
        except Exception:                                        # noqa: BLE001
            pass


class Device(Driver):
    def setup(self) -> None:
        self.cfg = load_config()
        self.hw = None
        self.experiment = None
        self.is_busy = False
        self.last_result = None
        self.dosed_here_ml = 0.0

    def make_backend(self):
        return OpcUaBackend(self.cfg)

    def time_scale(self) -> float:
        return 1.0

    def _hw(self):
        if self.hw is None:
            hw = self.make_backend()
            try:
                hw.open()
            except DeviceFault:
                raise
            except Exception as e:                                # noqa: BLE001
                raise DeviceFault(f"cannot reach iControl's OPC UA server: {type(e).__name__}: {e}") from None
            self.hw = hw
        return self.hw

    @staticmethod
    def _num(v, where: str):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise DeviceFault(f"{where} read {v!r}, not a number")
        return round(float(v), 2)

    def on_read(self, name: str):
        if name == "connected":
            try:
                hw = self._hw()
                if hw.nodes.get("connection_status"):
                    return bool(hw.read("connection_status"))
                return True
            except DeviceFault:
                return False
        if name == "busy":
            return self.is_busy
        if name == "last_result":
            return self.last_result
        if name == "experiment":
            return self.experiment
        hw = self._hw()
        if name in ("tr", "tj", "stirrer_rpm"):
            return self._num(hw.read(name), name)
        if name == "stirrer_running":
            if hw.nodes.get("stirrer_running"):
                return bool(hw.read("stirrer_running"))
            return self._num(hw.read("stirrer_rpm"), "stirrer_rpm") > 0
        if name in ("dosing_total_ml", "ph"):
            if not hw.nodes.get(name):
                return None
            v = hw.read(name)
            return None if v is None else self._num(v, name)
        if name == "phase":
            if not hw.nodes.get("phase"):
                return "running" if self.experiment else "idle"
            return str(hw.read("phase"))
        raise InvalidValue(f"unknown signal {name}")

    def on_write(self, name: str, value):
        hw = self._hw()
        if name == "tr_setpoint":
            hw.write("tr_setpoint", float(value))
            if hw.nodes.get("thermostat_mode"):
                hw.write("thermostat_mode", TR_MODE)
            return None
        if name == "tj_setpoint":
            hw.write("tj_setpoint", float(value))
            if hw.nodes.get("thermostat_mode"):
                hw.write("thermostat_mode", TJ_MODE)
            return None
        if name == "stirrer_setpoint":
            hw.write("stirrer_setpoint", float(value))
            return None
        if name == "ramp_rate":
            hw.write("ramp_rate", float(value))
            return None
        raise InvalidValue(f"unknown setting {name}")

    def validate_params(self, action: str, params: dict) -> None:
        if action == "start_experiment":
            steps = params["steps"]
            if not steps:
                raise InvalidValue("start_experiment.steps must hold at least one step")
            for i, s in enumerate(steps):
                if s.get("tj_c") is not None and abs(s["tj_c"] - s["tr_c"]) > 60:
                    raise InvalidValue(f"steps[{i}]: tj_c may not differ from tr_c by more than 60 K (Tj-Tr is limited to 60 K in Tr mode)")
        if action == "dose":
            if params["volume_ml"] / params["rate_ml_min"] > 24 * 60:
                raise InvalidValue("dose: volume at that rate takes longer than a day")

    def _wait_for_tr(self, job: Job, hw, target: float, tol: float, timeout_s: float, phase: str, frac0: float, frac1: float):
        """Block until Tr is within tol of target, checkpointing; a fault if the thermostat never gets there."""
        scale = self.time_scale()
        t0 = time.monotonic()
        poll = max(0.02, min(2.0, 5 * scale))
        while True:
            tr = self._num(hw.read("tr"), "tr")
            self.emit_signal("tr", tr)
            if abs(tr - target) <= tol:
                return tr
            elapsed = (time.monotonic() - t0) / scale
            self.checkpoint(job, frac0 + (frac1 - frac0) * min(0.95, elapsed / timeout_s), phase=phase, tr=tr)
            if elapsed > timeout_s:
                raise DeviceFault(f"Tr is {tr} after {timeout_s:.0f} s, not within {tol} K of {target}; check the thermostat and the Tsafe limits")
            time.sleep(poll)

    def _hold(self, job: Job, seconds: float, phase: str, frac0: float, frac1: float):
        scale = self.time_scale()
        t0 = time.monotonic()
        while (time.monotonic() - t0) / scale < seconds:
            self.checkpoint(job, frac0 + (frac1 - frac0) * ((time.monotonic() - t0) / scale / max(seconds, 1e-9)), phase=phase)
            time.sleep(max(0.02, min(1.0, seconds * scale / 20)))

    def _snapshot(self) -> dict:
        return {k: self.on_read(k) for k in ("tr", "tj", "stirrer_rpm", "stirrer_running", "dosing_total_ml", "ph", "phase")}

    def on_invoke(self, job: Job):
        hw = self._hw()
        p = job.params
        if job.action == "end_experiment":
            hw.call("end_experiment")
            if hw.nodes.get("thermostat_mode"):
                hw.write("thermostat_mode", IDLE_MODE)
            hw.write("stirrer_setpoint", 0.0)
            self.experiment = None
            return self._snapshot()

        if job.action == "dose":
            started = time.time()
            before = self.on_read("dosing_total_ml") or 0.0
            hw.call("dose", float(p["volume_ml"]), float(p["rate_ml_min"]))
            self.is_busy = True
            try:
                minutes = p["volume_ml"] / p["rate_ml_min"]
                self._hold(job, minutes * 60, "dosing", 0.0, 0.98)
            except JobCancelled:
                hw.call("stop_dosing")
                raise
            finally:
                self.is_busy = False
            after = self.on_read("dosing_total_ml")
            self.dosed_here_ml += float(p["volume_ml"])
            result = {"volume_ml": float(p["volume_ml"]), "rate_ml_min": float(p["rate_ml_min"]),
                      "duration_s": round((time.time() - started) / self.time_scale(), 1),
                      "dosing_total_ml": after if after is not None else round(before + p["volume_ml"], 3)}
            return result

        if job.action != "start_experiment":
            raise InvalidValue(f"unhandled action {job.action}")

        name = p.get("name") or f"mhp_{time.strftime('%Y%m%d_%H%M%S')}_{job.id}"
        started = time.time()
        hw.call("start_experiment", name)
        self.experiment = name
        self.is_busy = True
        steps = p["steps"]
        n = len(steps)
        try:
            for i, s in enumerate(steps):
                f0, f1 = i / (n + 1), (i + 1) / (n + 1)
                hw.write("stirrer_setpoint", float(s["stirrer_rpm"]))
                if s.get("ramp_k_min") is not None:
                    hw.write("ramp_rate", float(s["ramp_k_min"]))
                if s.get("tj_c") is not None:
                    hw.write("tj_setpoint", float(s["tj_c"]))
                    if hw.nodes.get("thermostat_mode"):
                        hw.write("thermostat_mode", TJ_MODE)
                hw.write("tr_setpoint", float(s["tr_c"]))
                if hw.nodes.get("thermostat_mode") and s.get("tj_c") is None:
                    hw.write("thermostat_mode", TR_MODE)
                ramp = s.get("ramp_k_min") or 5.0
                tr_now = self._num(hw.read("tr"), "tr")
                timeout = 60 * (abs(s["tr_c"] - tr_now) / ramp + 30)       # ramp time plus 30 min of settling
                self._wait_for_tr(job, hw, float(s["tr_c"]), float(p["tolerance_k"]), timeout, f"step {i + 1}: ramp", f0, (f0 + f1) / 2)
                self._hold(job, s["hold_min"] * 60, f"step {i + 1}: hold", (f0 + f1) / 2, f1)
            # end: bring the reactor to the end temperature, stirrer as asked
            hw.write("tr_setpoint", float(p["end_tr_c"]))
            if hw.nodes.get("thermostat_mode"):
                hw.write("thermostat_mode", TR_MODE)
            self._wait_for_tr(job, hw, float(p["end_tr_c"]), max(2.0, float(p["tolerance_k"])), 60 * 120, "end: to end_tr_c", n / (n + 1), 0.99)
            hw.write("stirrer_setpoint", float(p["end_stirrer_rpm"]))
        except JobCancelled:
            self._safe(hw)
            self.experiment = None
            raise
        finally:
            self.is_busy = False
        if p["end_experiment"]:
            hw.call("end_experiment")
            if hw.nodes.get("thermostat_mode"):
                hw.write("thermostat_mode", IDLE_MODE)
            self.experiment = None
        final = self._snapshot()
        result = {"experiment": name, "duration_s": round((time.time() - started) / self.time_scale(), 1),
                  "steps": n, "final": final}
        self.last_result = result
        self.emit_signal("last_result", result)
        return result

    def _safe(self, hw) -> None:
        """Stirrer off, dosing stopped, thermostat to its idle state (no heating or cooling demand)."""
        hw.write("stirrer_setpoint", 0.0)
        hw.call("stop_dosing")
        if hw.nodes.get("thermostat_mode"):
            hw.write("thermostat_mode", IDLE_MODE)
        hw.call("safe_state")

    def on_estop(self) -> None:
        try:
            if self.hw is not None:
                self._safe(self.hw)
        except Exception:                                        # noqa: BLE001  must not raise
            pass
        self.is_busy = False

    # ---- setup-time checks (`mhp node setup`) ---------------------------------------------- #
    @classmethod
    def probe(cls, cfg: dict) -> str:
        hw = OpcUaBackend(cfg)
        hw.open()
        try:
            missing = [k for k in READ_NODES[:3] + WRITE_NODES[:3] if not (cfg.get("nodes") or {}).get(k)]
            tr = hw.read("tr") if not missing else None
        finally:
            hw.close()
        if missing:
            return f"{cfg.get('url')} answers, but config.json nodes {missing} are not set; browse the server (UaExpert) and fill them in"
        return f"{cfg.get('url')} answers; Tr reads {tr}"
