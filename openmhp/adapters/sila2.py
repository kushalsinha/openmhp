"""SiLA 2 -> MHP.

    from openmhp.adapters.sila2 import sila_device
    dev = sila_device("10.0.0.12", 50052,
        device={"id": "arm-01", "class": "robot_arm", "location": "bay 3",
                "notes": "PF400 plate mover. Light curtain trips SafeZoneClear."},
        signals={"position": "RobotController.Position",
                 "safe_zone_clear": ("SafetyController.SafeZoneClear", "boolean")},
        settings={"speed": ("RobotController.SetSpeed.Speed", {"min": 1, "max": 100})},
        actions={"move_to": "RobotController.MoveTo",
                 "home": ("RobotController.Home", {"interlocks": ["safe_zone_clear"]})},
        estop="RobotController.EmergencyStop")

Mapping
  SiLA property (observable or not)            -> signal   "Feature.Property"
  SiLA unobservable command with one parameter -> setting  "Feature.Command.Parameter"
  SiLA command (observable or not)             -> action   "Feature.Command"; observable ones
                                                  report progress and honour cancel via the
                                                  command instance
  SiLA LockController                           -> MHP leases are enforced by the driver itself

Uses the `sila2` Python package's client (pip install sila2). `client` may be
injected for tests or for servers needing custom TLS setup.
"""
from __future__ import annotations

import time
from typing import Any

from .base import Action, BoundDriver, Setting, Signal


def _connect(host: str, port: int, insecure: bool):
    from sila2.client import SilaClient           # lazy: only needed for real hardware
    return SilaClient(host, port, insecure=insecure)


def _resolve(client, dotted: str):
    obj = client
    for part in dotted.split("."):
        obj = getattr(obj, part)
    return obj


def sila_device(host: str = "", port: int = 50052, *, device: dict, signals: dict | None = None,
                settings: dict | None = None, actions: dict | None = None, estop: str | None = None,
                physical: dict | None = None, insecure: bool = True, client=None, poll_s: float = 0.25) -> BoundDriver:
    client = client or _connect(host, port, insecure)

    def sig(name, spec):
        path, typ = (spec, "number") if isinstance(spec, str) else spec
        return Signal(name, read=lambda: _resolve(client, path).get(), type=typ)

    def setting(name, spec):
        path, opts = (spec, {}) if isinstance(spec, str) else (spec[0], spec[1] if isinstance(spec[1], dict) and "min" not in spec[1] and "max" not in spec[1] else {"limits": spec[1]})
        feat_cmd, param = path.rsplit(".", 1)
        return Setting(name, write=lambda v: _resolve(client, feat_cmd)(**{param: v}), **opts)

    def action(name, spec):
        path, opts = (spec, {}) if isinstance(spec, str) else spec

        def run(job, params):
            result = _resolve(client, path)(**params)
            if hasattr(result, "done"):                       # observable command instance
                while not result.done:
                    if job.cancel_requested and hasattr(result, "cancel"):
                        result.cancel()
                    prog = getattr(result, "progress", None)
                    if prog is not None:
                        driver.progress(job, float(prog))
                    time.sleep(poll_s)
                result = result.get_responses()
            return _plain(result)
        return Action(name, run=run, duration="long" if opts.pop("observable", False) else opts.pop("duration", "short"), **opts)

    driver = BoundDriver(
        device=device, physical=physical,
        signals=[sig(n, s) for n, s in (signals or {}).items()],
        settings=[setting(n, s) for n, s in (settings or {}).items()],
        actions=[action(n, s) for n, s in (actions or {}).items()],
        estop=(lambda: _resolve(client, estop)()) if estop else None,
        extra={"sila2": {"host": host, "port": port}},
    )
    return driver


def _plain(obj: Any) -> Any:
    """SiLA response objects -> JSON-able."""
    if hasattr(obj, "_asdict"):
        return obj._asdict()
    if hasattr(obj, "__dict__") and not isinstance(obj, (str, int, float, bool)):
        return {k: v for k, v in vars(obj).items() if not k.startswith("_")}
    return obj
