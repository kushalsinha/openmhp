"""Sartorius Biostat B / Biostat STR (DCU 4, Biobrain) through the Biobrain OPC UA server: node bindings.

The device is assembled from OPC UA node bindings the way openmhp.adapters.opcua does it (a
`client` with `get_node(id)` -> node with `get_value`, `set_value`, `call_method`), so the twin
injects a fake server and the real driver connects lazily through `Backend`. Node ids are
site-specific: Sartorius hands each customer an "OPC UA interface report" listing them, so the
ids live in config.json (`nodes`) and the ones shipped in config.example.json are placeholders
marked unverified (see references/opcua.md).

Requires on the real instrument: pip install asyncua (or opcua) and keyring.
"""
from __future__ import annotations

import json
import pathlib
import time

from openmhp.adapters import Action, BoundDriver, Setting, Signal
from openmhp.driver import DeviceFault, InvalidValue, JobCancelled

HERE = pathlib.Path(__file__).parent

# node keys -> placeholder ids (every one unverified; the site's interface report has the real ones)
DEFAULT_NODES = {
    "temperature": "ns=2;s=Unit1.TEMP.PV", "temperature_setpoint": "ns=2;s=Unit1.TEMP.SP",
    "temperature_mode": "ns=2;s=Unit1.TEMP.Mode",
    "ph": "ns=2;s=Unit1.PH.PV", "ph_setpoint": "ns=2;s=Unit1.PH.SP", "ph_mode": "ns=2;s=Unit1.PH.Mode",
    "do": "ns=2;s=Unit1.DO.PV", "do_setpoint": "ns=2;s=Unit1.DO.SP", "do_mode": "ns=2;s=Unit1.DO.Mode",
    "agitation": "ns=2;s=Unit1.STIRR.PV", "agitation_setpoint": "ns=2;s=Unit1.STIRR.SP",
    "agitation_mode": "ns=2;s=Unit1.STIRR.Mode",
    "gas_flow": "ns=2;s=Unit1.GASFL.PV", "gas_flow_setpoint": "ns=2;s=Unit1.GASFL.SP",
    "gas_flow_mode": "ns=2;s=Unit1.GASFL.Mode",
    "weight": "ns=2;s=Unit1.BALANCE.PV", "foam_alarm": "ns=2;s=Unit1.FOAM.Alarm",
    "feed_rate_setpoint": "ns=2;s=Unit1.SUBS.SP", "feed_mode": "ns=2;s=Unit1.SUBS.Mode",
    "acid_mode": "ns=2;s=Unit1.ACID.Mode", "base_mode": "ns=2;s=Unit1.BASE.Mode",
    "phase": "ns=2;s=Unit1.Recipe.Phase", "recipe_object": "ns=2;s=Unit1.Recipe",
    "recipe_start": "ns=2;s=Unit1.Recipe.Start", "recipe_stop": "ns=2;s=Unit1.Recipe.Stop",
}
MODE_OFF, MODE_AUTO = 0, 1          # DCU controller modes Off / Auto (manual is 2); numeric coding unverified
COMPLETE_PHASES = ("Complete", "Completed", "Idle", "Stopped", "")


def load_config() -> dict:
    p = HERE / "config.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


class Backend:
    """Every vendor call. Connects on first use so the package loads on a laptop without asyncua."""

    def __init__(self, cfg: dict):
        self.cfg, self.client, self.error = cfg, None, None

    def open(self):
        if self.client is not None:
            return self.client
        if self.error is not None:
            raise DeviceFault(self.error, {"transient": True})
        try:
            if not self.cfg.get("url"):
                raise DeviceFault("config.json is missing (copy config.example.json and fill it in)")
            try:
                from asyncua.sync import Client
            except ImportError:
                from opcua import Client
            c = Client(self.cfg["url"])
            user = self.cfg.get("user")
            if user:
                import keyring
                c.set_user(user)
                c.set_password(keyring.get_password("Biobrain", user) or "")
            c.connect()
            self.client = c
        except DeviceFault as e:
            self.error = e.message
            raise
        except ImportError:
            self.error = "asyncua is not installed (pip install asyncua keyring)"
            raise DeviceFault(self.error) from None
        except Exception as e:                                   # noqa: BLE001  vendor boundary
            self.error = f"cannot reach the Biobrain OPC UA server at {self.cfg.get('url')}: {type(e).__name__}: {e}"
            raise DeviceFault(self.error, {"transient": True}) from None
        return self.client

    def get_node(self, nid: str):
        return self.open().get_node(nid)

    def is_open(self) -> bool:
        try:
            self.open()
            return True
        except DeviceFault:
            return False


def build(client, cfg: dict | None = None, scale: float = 1.0) -> BoundDriver:
    """Assemble the MHP device from node bindings. `client` is a Backend or any fake with get_node()."""
    cfg = cfg or {}
    nodes = {**DEFAULT_NODES, **(cfg.get("nodes") or {})}
    ref: dict = {}                                               # the BoundDriver, once built (for checkpoint)
    poll_s = float(cfg.get("poll_s", 10))

    def node(key):
        return client.get_node(nodes[key])

    def read(key, cast=float):
        try:
            v = node(key).get_value()
        except DeviceFault:
            raise
        except Exception as e:                                   # noqa: BLE001  vendor boundary
            raise DeviceFault(f"OPC UA read of {nodes[key]} failed: {type(e).__name__}: {e}", {"transient": True}) from None
        return cast(v) if v is not None else None

    def write(key, value):
        try:
            node(key).set_value(value)
        except DeviceFault:
            raise
        except Exception as e:                                   # noqa: BLE001
            raise DeviceFault(f"OPC UA write of {nodes[key]} failed: {type(e).__name__}: {e}", {"transient": True}) from None

    def call(obj_key, meth_key, *args):
        try:
            return node(obj_key).call_method(nodes[meth_key], *args)
        except DeviceFault:
            raise
        except Exception as e:                                   # noqa: BLE001
            raise DeviceFault(f"OPC UA method {nodes[meth_key]} failed: {type(e).__name__}: {e}") from None

    def weight():
        try:
            return read("weight")
        except DeviceFault:
            return None                                          # no balance on this unit

    def phase() -> str:
        v = read("phase", str)
        return v if v is not None else ""

    signals = [
        Signal("connected", read=lambda: bool(client.is_open()) if hasattr(client, "is_open") else True, type="boolean"),
        Signal("temperature", read=lambda: read("temperature"), unit="Cel"),
        Signal("ph", read=lambda: read("ph"), unit="[pH]"),
        Signal("do", read=lambda: read("do"), unit="%"),
        Signal("agitation_rpm", read=lambda: read("agitation"), unit="{rev}/min"),
        Signal("gas_flow", read=lambda: read("gas_flow"), unit="L/min"),
        Signal("weight_kg", read=weight, unit="kg"),
        Signal("foam_alarm", read=lambda: bool(read("foam_alarm", int)), type="boolean"),
        Signal("phase", read=phase, type="string"),
        Signal("agitation_running", read=lambda: read("agitation") > 5, type="boolean"),
    ]

    def setpoint(name, key, mode_key, unit, limits):
        def w(v):
            write(key, float(v))
            write(mode_key, MODE_AUTO)
        return Setting(name, write=w, read=lambda: read(key), unit=unit, limits=limits)

    settings = [
        setpoint("temperature_setpoint", "temperature_setpoint", "temperature_mode", "Cel", {"min": 4, "max": 50}),
        setpoint("ph_setpoint", "ph_setpoint", "ph_mode", "[pH]", {"min": 2, "max": 12}),
        setpoint("do_setpoint", "do_setpoint", "do_mode", "%", {"min": 0, "max": 100}),
        setpoint("agitation_setpoint", "agitation_setpoint", "agitation_mode", "{rev}/min", {"min": 0, "max": 1500}),
        setpoint("gas_flow_setpoint", "gas_flow_setpoint", "gas_flow_mode", "L/min", {"min": 0, "max": 20}),
    ]

    def snapshot() -> dict:
        return {"phase": phase(), "temperature": read("temperature"), "ph": read("ph"), "do": read("do"),
                "agitation_rpm": read("agitation"), "gas_flow": read("gas_flow"), "weight_kg": weight()}

    def start_batch(job, p):
        drv = ref["drv"]
        if phase() not in COMPLETE_PHASES:
            raise DeviceFault(f"a recipe is already running (phase {phase()!r}); stop it first")
        call("recipe_object", "recipe_start", str(p["recipe"]))
        started = time.time()
        limit = p.get("duration_s")
        max_s = float(cfg.get("max_batch_hours", 21 * 24)) * 3600
        seen_running = False
        while True:
            try:
                drv.checkpoint(job, phase="recipe " + phase())
            except JobCancelled:
                call("recipe_object", "recipe_stop")
                raise
            ph = phase()
            elapsed = (time.time() - started) / scale
            if ph not in COMPLETE_PHASES:
                seen_running = True
            elif seen_running:
                break
            elif elapsed > 10 * poll_s + 30:
                raise DeviceFault(f"recipe {p['recipe']!r} did not start (phase {ph!r}); check the recipe name in Biobrain")
            if limit is not None and elapsed >= float(limit):
                call("recipe_object", "recipe_stop")
                break
            if elapsed > max_s:
                raise DeviceFault(f"recipe still running after {max_s / 3600:.0f} h (max_batch_hours)")
            if limit:
                drv.progress(job, min(0.99, elapsed / float(limit)))
            drv.emit_signal("phase", ph)
            time.sleep(min(1.0, poll_s * scale))
        return {"recipe": p["recipe"], "duration_s": round((time.time() - started) / scale, 1), "final": snapshot()}

    def add_feed(job, p):
        drv = ref["drv"]
        vol, rate = float(p["volume_ml"]), float(p["rate_ml_h"])
        hours = vol / rate
        if hours * 3600 > float(cfg.get("max_feed_hours", 48)) * 3600:
            raise InvalidValue(f"feeding {vol} mL at {rate} mL/h takes {hours:.1f} h, above max_feed_hours")
        write("feed_rate_setpoint", rate)
        write("feed_mode", MODE_AUTO)
        started = time.time()
        try:
            while (time.time() - started) / scale < hours * 3600:
                drv.checkpoint(job, min(0.99, (time.time() - started) / scale / (hours * 3600)), phase="feeding")
                time.sleep(min(1.0, poll_s * scale))
        finally:
            write("feed_rate_setpoint", 0.0)
            write("feed_mode", MODE_OFF)
        return {"volume_ml": vol, "rate_ml_h": rate, "duration_s": round((time.time() - started) / scale, 1),
                "weight_kg": weight()}

    def stop_batch(job, p):
        call("recipe_object", "recipe_stop")
        return {"stopped": True, "phase": phase()}

    actions = [
        Action("start_batch", run=start_batch, duration="long", interlocks=["connected"], pausable=True),
        Action("add_feed", run=add_feed, duration="long", interlocks=["connected", "agitation_running"], pausable=True),
        Action("stop_batch", run=stop_batch, duration="short", approval="confirm", interlocks=["connected"]),
    ]

    def estop():
        # the DCU's own alarms stay primary; this removes energy and motion the way a person would at the panel
        for key, value in (("agitation_setpoint", 0.0), ("agitation_mode", MODE_OFF), ("gas_flow_setpoint", 0.0),
                           ("gas_flow_mode", MODE_OFF), ("feed_rate_setpoint", 0.0), ("feed_mode", MODE_OFF),
                           ("acid_mode", MODE_OFF), ("base_mode", MODE_OFF), ("temperature_mode", MODE_OFF)):
            try:
                write(key, value)
            except DeviceFault:
                pass                                             # keep going: every output that can be reached is cut

    drv = BoundDriver(device={}, signals=signals, settings=settings, actions=actions, estop=estop,
                      extra={"opcua": {"url": cfg.get("url", "")}})
    ref["drv"] = drv
    return drv


def Device() -> BoundDriver:
    cfg = load_config()
    return build(Backend(cfg), cfg)


# ---- setup-time checks (`mhp node setup`) ------------------------------------------------- #
def probe(cfg: dict) -> str:
    hw = Backend(cfg)
    hw.open()
    nodes = {**DEFAULT_NODES, **(cfg.get("nodes") or {})}
    v = hw.get_node(nodes["temperature"]).get_value()
    return f"Biobrain OPC UA server at {cfg.get('url')} answers; temperature node reads {v}"


Device.probe = probe                                             # noqa: E305  mhp node setup looks here
