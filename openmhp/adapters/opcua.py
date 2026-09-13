"""OPC UA -> MHP.  (Also the pattern for Modbus and other register-style layers.)

    from openmhp.adapters.opcua import opcua_device
    dev = opcua_device("opc.tcp://furnace-plc:4840",
        device={"id": "furnace-02", "class": "oven", "location": "line 4",
                "notes": "Sintering furnace. Door interlock is hardwired; MHP mirrors it."},
        signals={"zone1_temperature": ("ns=2;s=Furnace.Zone1.PV", "degC"),
                 "door_closed": ("ns=2;s=Furnace.DoorClosed", "boolean")},
        settings={"zone1_setpoint": ("ns=2;s=Furnace.Zone1.SP", {"min": 20, "max": 1400}, "degC")},
        actions={"start_program": ("ns=2;s=Furnace", "ns=2;s=Furnace.Start",
                                   {"interlocks": ["door_closed"], "approval": "confirm"})},
        estop=("ns=2;s=Furnace", "ns=2;s=Furnace.Abort"))

Mapping
  Variable node (read)      -> signal   (nodeid, unit?)
  Variable node (write)     -> setting  (nodeid, limits?, unit?)
  Method node               -> action   (object nodeid, method nodeid, opts?); params are passed
                                        positionally in the order of the `params` doc you give
  Alarms & conditions       -> not mapped in 0.2; poll a signal instead

Uses python-opcua (`opcua.Client`) or asyncua's sync wrapper
(`asyncua.sync.Client`); pass `client=` to inject either, or a fake for tests
(needs get_node(id) -> node with get_value/set_value, and call_method).
"""
from __future__ import annotations

from .base import Action, BoundDriver, Setting, Signal


def _connect(url: str):
    try:
        from asyncua.sync import Client
    except ImportError:
        from opcua import Client
    c = Client(url)
    c.connect()
    return c


def opcua_device(url: str = "", *, device: dict, signals: dict | None = None, settings: dict | None = None,
                 actions: dict | None = None, estop: tuple | None = None, physical: dict | None = None,
                 client=None) -> BoundDriver:
    client = client or _connect(url)
    node = client.get_node

    def sig(name, spec):
        nid, unit = (spec, None) if isinstance(spec, str) else (spec[0], spec[1] if len(spec) > 1 else None)
        typ = "boolean" if unit == "boolean" else "number"
        return Signal(name, read=lambda: node(nid).get_value(), unit=None if typ == "boolean" else unit, type=typ)

    def setting(name, spec):
        nid, limits, unit = (spec, None, None) if isinstance(spec, str) else (spec + (None, None))[:3]
        return Setting(name, write=lambda v: node(nid).set_value(v), read=lambda: node(nid).get_value(),
                       limits=limits, unit=unit)

    def action(name, spec):
        obj, meth, opts = (spec + ({},))[:3]
        order = list((opts.get("params") or {}).keys())

        def run(job, params):
            args = [params[k] for k in order] if order else list(params.values())
            return node(obj).call_method(meth, *args)
        return Action(name, run=run, **opts)

    return BoundDriver(
        device=device, physical=physical,
        signals=[sig(n, s) for n, s in (signals or {}).items()],
        settings=[setting(n, s) for n, s in (settings or {}).items()],
        actions=[action(n, s) for n, s in (actions or {}).items()],
        estop=(lambda: node(estop[0]).call_method(estop[1])) if estop else None,
        extra={"opcua": {"url": url}},
    )
