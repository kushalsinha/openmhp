"""MHP driver for a Vapourtec R-Series (R2 pumps, R4 reactor heater) under Flow Commander, through its OPC UA server.

Vapourtec's R-Series brochure says Flow Commander "includes an optional OPC UA server" with Python examples, but
publishes no node list. Every node id this package uses is therefore a config.json entry (`nodes`), shipped as
placeholders marked unverified in references/opcua_nodes.md. The client sits behind OpcUaBackend so the twin can
replace it.
"""
from __future__ import annotations

import json
import pathlib
import time

from openmhp.driver import DeviceFault, Driver, InvalidValue, Job, JobCancelled

HERE = pathlib.Path(__file__).parent
REACTORS = (1, 2, 3, 4)
READ_NODES = ("pump_a_flow", "pump_b_flow", "system_pressure", "system_state", "collection_valve",
              *[f"reactor_{n}_temperature" for n in REACTORS])
WRITE_NODES = ("pump_a_flow_setpoint", "pump_b_flow_setpoint", "bpr_pressure", "collection_valve_set",
               *[f"reactor_{n}_setpoint" for n in REACTORS], *[f"reactor_{n}_enable" for n in REACTORS])
METHOD_NODES = ("object", "start", "stop", "prime")
VALVE_COLLECT, VALVE_WASTE = "collect", "waste"
# Flow Commander run states as the TheWorldAvatar VapourtecAgent maps FCRemote.GetState (0..4); more exist
STATES = {0: "Idle", 1: "Initialising", 2: "RunningReaction", 3: "CleaningReaction", 4: "FinalCleaning"}


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
                pw = keyring.get_password("FlowCommanderOPC", self.cfg["username"])
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
            raise DeviceFault(f"config.json nodes.{key} is not set; browse the Flow Commander OPC UA server and fill it in")
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
        """Call method node `key` on the object node; skipped (None) when the lab has not mapped it."""
        if not self.nodes.get(key) or not self.nodes.get("object"):
            return None
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
        self.is_busy = False
        self.last_result = None

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
                raise DeviceFault(f"cannot reach Flow Commander's OPC UA server: {type(e).__name__}: {e}") from None
            self.hw = hw
        return self.hw

    @staticmethod
    def _num(v, where: str):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise DeviceFault(f"{where} read {v!r}, not a number")
        return round(float(v), 3)

    def on_read(self, name: str):
        if name == "connected":
            try:
                self._hw()
                return True
            except DeviceFault:
                return False
        if name == "busy":
            return self.is_busy
        if name == "last_result":
            return self.last_result
        hw = self._hw()
        if name in ("pump_a_flow", "pump_b_flow", "system_pressure"):
            return self._num(hw.read(name), name)
        if name.startswith("reactor_") and name.endswith("_temperature"):
            if not hw.nodes.get(name):
                return None
            v = hw.read(name)
            return None if v is None else self._num(v, name)
        if name == "system_state":
            v = hw.read("system_state")
            return STATES.get(v, str(v)) if isinstance(v, int) else str(v)
        if name == "collection_valve":
            v = hw.read("collection_valve")
            if isinstance(v, bool):
                return VALVE_COLLECT if v else VALVE_WASTE
            return str(v).lower()
        if name == "pressure_ok":
            return self._num(hw.read("system_pressure"), "system_pressure") < float(self.cfg.get("max_pressure_bar", 20))
        raise InvalidValue(f"unknown signal {name}")

    def on_write(self, name: str, value):
        hw = self._hw()
        if name in WRITE_NODES:
            hw.write(name, float(value))
            if name.startswith("reactor_") and name.endswith("_setpoint"):
                en = name.replace("_setpoint", "_enable")
                if hw.nodes.get(en):
                    hw.write(en, True)
            return None
        raise InvalidValue(f"unknown setting {name}")

    def validate_params(self, action: str, params: dict) -> None:
        if action == "run_experiment":
            seen = set()
            for r in params["reactors"]:
                if r["channel"] in seen:
                    raise InvalidValue(f"run_experiment.reactors names channel {r['channel']} twice")
                seen.add(r["channel"])
            total = params["pump_a_ml_min"] + params["pump_b_ml_min"]
            if total <= 0:
                raise InvalidValue("run_experiment: at least one pump must deliver flow")
            if params["collect_ml"] > 0 and params["collect_ml"] / total > 24 * 60:
                raise InvalidValue("run_experiment: collecting that volume at that flow takes longer than a day")

    def _snapshot(self) -> dict:
        snap = {k: self.on_read(k) for k in ("pump_a_flow", "pump_b_flow", "system_pressure", "system_state", "collection_valve")}
        snap["reactors"] = {str(n): self.on_read(f"reactor_{n}_temperature") for n in REACTORS}
        return snap

    def _pumps_off(self, hw) -> None:
        hw.write("pump_a_flow_setpoint", 0.0)
        hw.write("pump_b_flow_setpoint", 0.0)

    def _heaters_off(self, hw) -> None:
        for n in REACTORS:
            if hw.nodes.get(f"reactor_{n}_enable"):
                hw.write(f"reactor_{n}_enable", False)

    def _valve(self, hw, position: str) -> None:
        if hw.nodes.get("collection_valve_set"):
            hw.write("collection_valve_set", position == VALVE_COLLECT)

    def _wait(self, job: Job, seconds: float, phase: str, f0: float, f1: float, check=None):
        scale = self.time_scale()
        t0 = time.monotonic()
        while (time.monotonic() - t0) / scale < seconds:
            self.checkpoint(job, f0 + (f1 - f0) * ((time.monotonic() - t0) / scale / max(seconds, 1e-9)), phase=phase)
            if check:
                check()
            time.sleep(max(0.02, min(1.0, seconds * scale / 20)))

    def on_invoke(self, job: Job):
        hw = self._hw()
        p = job.params
        if job.action == "stop":
            hw.call("stop")
            self._pumps_off(hw)
            self._heaters_off(hw)
            self._valve(hw, VALVE_WASTE)
            return self._snapshot()

        if job.action == "prime":
            started = time.time()
            self._valve(hw, VALVE_WASTE)
            key = "pump_a_flow_setpoint" if p["pump"] == "A" else "pump_b_flow_setpoint"
            hw.call("prime", p["pump"], float(p["volume_ml"]))
            hw.write(key, float(p["rate_ml_min"]))
            self.is_busy = True
            try:
                self._wait(job, p["volume_ml"] / p["rate_ml_min"] * 60, f"priming pump {p['pump']}", 0.0, 0.98)
            finally:
                hw.write(key, 0.0)
                self.is_busy = False
            return {"pump": p["pump"], "volume_ml": float(p["volume_ml"]),
                    "duration_s": round((time.time() - started) / self.time_scale(), 1)}

        if job.action != "run_experiment":
            raise InvalidValue(f"unhandled action {job.action}")

        name = p.get("name") or f"mhp_{time.strftime('%Y%m%d_%H%M%S')}_{job.id}"
        started = time.time()
        max_bar = float(self.cfg.get("max_pressure_bar", 20))
        self.is_busy = True
        collected = 0.0
        try:
            # 1. heaters to temperature
            self._valve(hw, VALVE_WASTE)
            for r in p["reactors"]:
                hw.write(f"reactor_{r['channel']}_setpoint", float(r["temperature_c"]))
                if hw.nodes.get(f"reactor_{r['channel']}_enable"):
                    hw.write(f"reactor_{r['channel']}_enable", True)
            hw.write("bpr_pressure", float(p["bpr_bar"]))
            hw.call("start", name)
            scale = self.time_scale()
            t0 = time.monotonic()
            tol = float(p["tolerance_k"])
            while True:
                temps = {r["channel"]: self.on_read(f"reactor_{r['channel']}_temperature") for r in p["reactors"]}
                if all(t is not None and abs(t - r["temperature_c"]) <= tol for r, t in zip(p["reactors"], temps.values())):
                    break
                elapsed = (time.monotonic() - t0) / scale
                self.checkpoint(job, min(0.15, 0.15 * elapsed / 1800), phase="heating reactors", temperatures=temps)
                if elapsed > 3600:
                    raise DeviceFault(f"reactors did not reach temperature within an hour: {temps}")
                time.sleep(max(0.02, min(2.0, 5 * scale)))
            # 2. pumps on; wait one residence time plus the lead-in before collecting
            hw.write("pump_a_flow_setpoint", float(p["pump_a_ml_min"]))
            hw.write("pump_b_flow_setpoint", float(p["pump_b_ml_min"]))

            def pressure_check():
                bar = self._num(hw.read("system_pressure"), "system_pressure")
                if bar > max_bar:
                    raise DeviceFault(f"system pressure {bar} bar is above the configured maximum {max_bar} bar")
                state = self.on_read("system_state")
                if "pressure" in str(state).lower():
                    raise DeviceFault(f"Flow Commander reports {state}")

            self._wait(job, p["residence_time_min"] * 60 + p["lead_in_min"] * 60, "steady state", 0.15, 0.5, pressure_check)
            # 3. collect
            total = p["pump_a_ml_min"] + p["pump_b_ml_min"]
            if p["collect_ml"] > 0:
                self._valve(hw, VALVE_COLLECT)
                self._wait(job, p["collect_ml"] / total * 60, "collecting", 0.5, 0.95, pressure_check)
                collected = float(p["collect_ml"])
                self._valve(hw, VALVE_WASTE)
            # 4. flush with the pumps still running for the flush time, then stop
            if p["flush_min"] > 0:
                self._wait(job, p["flush_min"] * 60, "flushing to waste", 0.95, 0.99, pressure_check)
        except JobCancelled:
            self._pumps_off(hw)
            self._heaters_off(hw)
            self._valve(hw, VALVE_WASTE)
            hw.call("stop")
            raise
        except Exception:
            self._pumps_off(hw)
            self._valve(hw, VALVE_WASTE)
            raise
        finally:
            self.is_busy = False
        self._pumps_off(hw)
        if not p["keep_heaters_on"]:
            self._heaters_off(hw)
        hw.call("stop")
        final = self._snapshot()
        result = {"experiment": name, "duration_s": round((time.time() - started) / self.time_scale(), 1),
                  "collected_ml": collected, "final": final}
        self.last_result = result
        self.emit_signal("last_result", result)
        return result

    def on_estop(self) -> None:
        try:
            if self.hw is not None:
                self._pumps_off(self.hw)
                self._heaters_off(self.hw)
                self._valve(self.hw, VALVE_WASTE)
                self.hw.call("stop")
        except Exception:                                        # noqa: BLE001  must not raise
            pass
        self.is_busy = False

    # ---- setup-time checks (`mhp node setup`) ---------------------------------------------- #
    @classmethod
    def probe(cls, cfg: dict) -> str:
        hw = OpcUaBackend(cfg)
        hw.open()
        try:
            missing = [k for k in ("pump_a_flow", "pump_b_flow", "system_pressure", "pump_a_flow_setpoint", "pump_b_flow_setpoint")
                       if not (cfg.get("nodes") or {}).get(k)]
            bar = hw.read("system_pressure") if not missing else None
        finally:
            hw.close()
        if missing:
            return f"{cfg.get('url')} answers, but config.json nodes {missing} are not set; browse the server (UaExpert) and fill them in"
        return f"{cfg.get('url')} answers; system pressure reads {bar} bar"
