"""MHP driver for a Quantum Design PPMS / DynaCool / MPMS3 (VersaLab, OptiCool by the same calls) through the
MultiVu socket server: Quantum Design's MultiPyVu package (MIT, PyPI; Server on the MultiVu PC, Client
anywhere). Calls used: Client(host, port).open(), get_temperature(), set_temperature(set_point, rate_K_per_min,
approach_mode), get_temperature_setpoints(), get_field(), set_field(set_point, rate_oe_per_sec, approach_mode
[, driven_mode]), get_field_setpoints(), get_chamber(), set_chamber(mode), close_client(), with the enums
client.temperature.approach_mode.{fast_settle, no_overshoot}, client.field.approach_mode.{linear, no_overshoot,
oscillate}, client.field.driven_mode.{persistent, driven} and client.chamber.mode.{seal, purge_seal, vent_seal,
pump_continuous, vent_continuous, high_vacuum}. Every MultiPyVu call sits in PpmsBackend; the twin replaces the
client with a ramp model. No vendor import at module top: `connected` reads False with a plain reason when
MultiPyVu is not installed or the server is not running.
"""
from __future__ import annotations

import json
import pathlib
import time

from openmhp.driver import DeviceFault, Driver, InvalidValue, Job

HERE = pathlib.Path(__file__).parent
TEMP_APPROACH = ("fast_settle", "no_overshoot")
FIELD_APPROACH = ("linear", "no_overshoot", "oscillate")
DRIVEN = ("persistent", "driven")
CHAMBER_MODES = ("seal", "purge_seal", "vent_seal", "pump_continuous", "vent_continuous", "high_vacuum")
TEMP_STABLE = ("stable",)
FIELD_STABLE = ("stable driven", "stable persistent")
# which chamber status word says a chamber command has finished (MultiVu's words; unverified spellings,
# compared case-insensitively on their first word)
CHAMBER_SETTLED = {"seal": ("sealed",), "purge_seal": ("purged",), "vent_seal": ("vented",),
                   "pump_continuous": ("pumping",), "vent_continuous": ("venting",), "high_vacuum": ("high",)}


def load_config() -> dict:
    p = HERE / "config.json"
    return json.loads(p.read_text(encoding="utf-8") or "{}") if p.is_file() else {}


class PpmsBackend:
    """Every MultiPyVu call. `client` is a MultiPyVu.Client once open() has run."""

    def __init__(self, cfg: dict):
        self.cfg, self.client = cfg, None

    def open(self) -> None:
        if not self.cfg.get("host"):
            raise DeviceFault("config.json is missing (copy config.example.json and fill it in)")
        import MultiPyVu as mpv                                  # pip install MultiPyVu (client runs anywhere)
        self.client = mpv.Client(host=self.cfg["host"], port=int(self.cfg.get("port", 27183)))
        self.client.open()

    def close(self) -> None:
        if self.client is not None:
            try:
                self.client.close_client()
            finally:
                self.client = None

    def temperature(self) -> tuple[float, str]:
        t, status = self.client.get_temperature()
        return float(t), str(status)

    def temperature_setpoints(self) -> tuple[float, float, str]:
        sp, rate, approach = self.client.get_temperature_setpoints()
        return float(sp), float(rate), str(approach)

    def set_temperature(self, kelvin: float, rate_k_min: float, approach: str) -> None:
        mode = getattr(self.client.temperature.approach_mode, approach)
        self.client.set_temperature(float(kelvin), float(rate_k_min), mode)

    def field(self) -> tuple[float, str]:
        h, status = self.client.get_field()
        return float(h), str(status)

    def field_setpoints(self) -> tuple[float, float, str, str]:
        sp, rate, approach, driven = self.client.get_field_setpoints()
        return float(sp), float(rate), str(approach), str(driven)

    def set_field(self, oe: float, rate_oe_s: float, approach: str, driven: str | None) -> None:
        mode = getattr(self.client.field.approach_mode, approach)
        if driven is None:
            self.client.set_field(float(oe), float(rate_oe_s), mode)
        else:
            self.client.set_field(float(oe), float(rate_oe_s), mode, getattr(self.client.field.driven_mode, driven))

    def chamber(self) -> str:
        return str(self.client.get_chamber())

    def set_chamber(self, mode: str) -> None:
        self.client.set_chamber(getattr(self.client.chamber.mode, mode))


class PpmsCryostat(Driver):
    def setup(self) -> None:
        self.cfg = load_config()
        self.hw = None
        self.temperature_rate = 5.0
        self.temperature_approach = "fast_settle"
        self.field_rate = 100.0
        self.field_approach = "linear"
        self.field_driven_mode = None
        self.temperature_setpoint = None
        self.field_setpoint = None

    def make_backend(self):
        return PpmsBackend(self.cfg)

    def time_scale(self) -> float:
        return 1.0

    def _hw(self):
        if self.hw is None:
            hw = self.make_backend()
            try:
                hw.open()
            except DeviceFault:
                raise
            except ImportError:
                raise DeviceFault("MultiPyVu is not installed (pip install MultiPyVu)") from None
            except Exception as e:                               # noqa: BLE001  vendor boundary
                raise DeviceFault(f"cannot reach the MultiVu socket server at {self.cfg.get('host')}:{self.cfg.get('port', 27183)}: "
                                  f"{type(e).__name__}: {e}", {"transient": True}) from None
            self.hw = hw
        return self.hw

    def _vendor(self, what, fn):
        try:
            return fn()
        except (DeviceFault, InvalidValue):
            raise
        except Exception as e:                                   # noqa: BLE001  vendor boundary
            raise DeviceFault(f"MultiVu {what} failed: {type(e).__name__}: {e}", {"transient": True}) from None

    def _platform(self) -> str:
        return str(self.cfg.get("platform", "")).lower()

    def on_read(self, name: str):
        if name == "connected":
            try:
                self._vendor("get_temperature", self._hw().temperature)
                return True
            except DeviceFault:
                return False
        hw = self._hw()
        if name == "temperature":
            return round(self._vendor("get_temperature", hw.temperature)[0], 4)
        if name == "temperature_status":
            return self._vendor("get_temperature", hw.temperature)[1]
        if name == "field":
            return round(self._vendor("get_field", hw.field)[0], 2)
        if name == "field_status":
            return self._vendor("get_field", hw.field)[1]
        if name == "chamber_state":
            return self._vendor("get_chamber", hw.chamber)
        if name == "temperature_setpoint_actual":
            return self._vendor("get_temperature_setpoints", hw.temperature_setpoints)[0]
        if name == "field_setpoint_actual":
            return self._vendor("get_field_setpoints", hw.field_setpoints)[0]
        if name == "temperature_setpoint":
            return self.temperature_setpoint
        if name == "field_setpoint":
            return self.field_setpoint
        if name in ("temperature_rate", "temperature_approach", "field_rate", "field_approach", "field_driven_mode"):
            return getattr(self, name)
        raise InvalidValue(f"unknown signal {name}")

    def on_write(self, name: str, value):
        if name == "temperature_setpoint":
            self._vendor("set_temperature", lambda: self._hw().set_temperature(value, self.temperature_rate, self.temperature_approach))
            self.temperature_setpoint = float(value)
            return None
        if name == "field_setpoint":
            self._vendor("set_field", lambda: self._hw().set_field(value, self.field_rate, self.field_approach, self.field_driven_mode))
            self.field_setpoint = float(value)
            return None
        if name == "field_driven_mode":
            if self._platform() != "ppms":
                raise InvalidValue("field_driven_mode is a PPMS-only setting (MultiPyVu raises on other platforms); "
                                   f"config.json platform is {self._platform() or 'unset'!r}")
            self.field_driven_mode = value
            return None
        if name in ("temperature_rate", "temperature_approach", "field_rate", "field_approach"):
            setattr(self, name, value)
            return None
        raise InvalidValue(f"unknown setting {name}")

    def validate_params(self, action: str, params: dict) -> None:
        if action == "set_field_and_wait" and params.get("driven_mode") is not None and self._platform() != "ppms":
            raise InvalidValue("driven_mode is PPMS-only; leave it null on a DynaCool, MPMS3, VersaLab or OptiCool")
        if action == "set_chamber" and self._platform() == "opticool":
            raise InvalidValue("set_chamber is not used on an OptiCool")

    def on_invoke(self, job: Job):
        hw, p, scale = self._hw(), job.params, self.time_scale()
        started = time.time()
        if job.action == "set_temperature_and_wait":
            t0 = self._vendor("get_temperature", hw.temperature)[0]
            self._vendor("set_temperature", lambda: hw.set_temperature(p["temperature"], p["rate"], p["approach"]))
            self.temperature_setpoint = float(p["temperature"])
            t, status, reached = self._follow(job, "temperature", lambda: hw.temperature(), TEMP_STABLE,
                                              t0, p["temperature"], p["settle_s"], p["timeout_s"])
            return {"setpoint_K": float(p["temperature"]), "temperature_K": round(t, 4), "status": status,
                    "reached": reached, "duration_s": round((time.time() - started) / scale, 1)}
        if job.action in ("set_field_and_wait", "discharge_magnet"):
            target = float(p["field"]) if job.action == "set_field_and_wait" else 0.0
            approach = p.get("approach", "linear") if job.action == "set_field_and_wait" else "linear"
            driven = p.get("driven_mode") if job.action == "set_field_and_wait" else None
            settle = p.get("settle_s", 10) if job.action == "set_field_and_wait" else 10
            timeout = p.get("timeout_s", 3600) if job.action == "set_field_and_wait" else 3600
            h0 = self._vendor("get_field", hw.field)[0]
            self._vendor("set_field", lambda: hw.set_field(target, p["rate"], approach, driven))
            self.field_setpoint = target
            h, status, reached = self._follow(job, "field", lambda: hw.field(), FIELD_STABLE, h0, target, settle, timeout)
            out = {"field_Oe": round(h, 2), "status": status, "reached": reached,
                   "duration_s": round((time.time() - started) / scale, 1)}
            if job.action == "set_field_and_wait":
                out["setpoint_Oe"] = target
            return out
        if job.action == "set_chamber":
            self._vendor("set_chamber", lambda: hw.set_chamber(p["mode"]))
            words = CHAMBER_SETTLED[p["mode"]]
            deadline = time.time() + float(p["timeout_s"]) * scale
            state, reached = "", False
            while True:
                self.checkpoint(job, phase="chamber")
                state = self._vendor("get_chamber", hw.chamber)
                if state.lower().split()[:1] and state.lower().split()[0] in words:
                    reached = True
                    break
                if time.time() > deadline:
                    break
                time.sleep(min(1.0, 2 * scale))
            return {"mode": p["mode"], "chamber_state": state, "reached": reached,
                    "duration_s": round((time.time() - started) / scale, 1)}
        raise InvalidValue(f"unhandled action {job.action}")

    def _follow(self, job, what, read, stable_words, start, target, settle_s, timeout_s):
        """Poll until the status word is a stable one for settle_s; progress is the fraction of the ramp covered."""
        scale = self.time_scale()
        deadline = time.time() + float(timeout_s) * scale
        stable_since = None
        value, status = start, ""
        span = abs(float(target) - float(start)) or 1.0
        while True:
            self.checkpoint(job, phase=what)
            value, status = self._vendor(f"get_{what}", read)
            self.progress(job, max(0.0, min(0.95, 1 - abs(float(target) - value) / span)))
            if status.lower() in stable_words:
                stable_since = stable_since or time.time()
                if time.time() - stable_since >= float(settle_s) * scale:
                    return value, status, True
            else:
                stable_since = None
            if time.time() > deadline:
                return value, status, False
            time.sleep(min(1.0, 2 * scale))

    def on_estop(self) -> None:
        pass                                                     # safety.estop is false: nothing to send (see safety.notes)

    def close(self) -> None:
        try:
            if self.hw is not None:
                self.hw.close()
        except Exception:                                        # noqa: BLE001
            pass
        super().close()

    @classmethod
    def probe(cls, cfg: dict) -> str:
        hw = PpmsBackend(cfg)
        hw.open()
        try:
            t, st = hw.temperature()
            h, hst = hw.field()
            return f"MultiVu socket server at {cfg.get('host')}:{cfg.get('port', 27183)}: {t:.3f} K ({st}), {h:.1f} Oe ({hst}), chamber {hw.chamber()}"
        finally:
            hw.close()
