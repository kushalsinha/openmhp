"""PyLabRobot -> MHP.

    from pylabrobot.liquid_handling import LiquidHandler
    from pylabrobot.liquid_handling.backends import STAR
    from pylabrobot.resources import STARLetDeck
    from openmhp.adapters.pylabrobot import plr_device

    lh = LiquidHandler(backend=STAR(), deck=STARLetDeck())
    dev = plr_device(lh, device={"id": "star-01", "class": "liquid_handler", "location": "bay 1",
                                 "notes": "Hamilton STARlet. Keep the deck clear of loose tips."},
                     actions=["pick_up_tips", "drop_tips", "aspirate", "dispense", "move_plate"],
                     limits={"aspirate": {"vols": [0, 1000]}})

Every public coroutine on the machine becomes an MHP action (or only the ones
you name), with `params` documented from its Python signature. setup()/stop()
are wired to the driver's lifecycle and e-stop. Coroutines run on a private
event loop thread so the synchronous MHP driver can call them.

Works with any pylabrobot Machine (LiquidHandler, PlateReader, Centrifuge,
Incubator, ...). `machine` may be a fake with async methods for testing.
"""
from __future__ import annotations

import asyncio
import inspect
import threading

from .base import Action, BoundDriver, Signal, params_from_signature

_SKIP = {"setup", "stop", "serialize", "deserialize", "save", "load", "assign_child_resource",
         "unassign_child_resource", "get_resource"}


class _Loop:
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()

    def run(self, coro, timeout=None):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)


def plr_device(machine, *, device: dict, actions: list[str] | None = None, signals: dict | None = None,
               limits: dict | None = None, approval: dict | None = None, physical: dict | None = None,
               setup: bool = True, action_timeout_s: float = 3600) -> BoundDriver:
    loop = _Loop()
    limits, approval = limits or {}, approval or {}

    names = actions or [n for n, m in inspect.getmembers(machine, inspect.iscoroutinefunction)
                        if not n.startswith("_") and n not in _SKIP]

    def make_action(name):
        fn = getattr(machine, name)

        def run(job, params):
            res = loop.run(fn(**params), timeout=action_timeout_s)
            return res if isinstance(res, (dict, list, str, int, float, bool, type(None))) else str(res)
        return Action(name, run=run, duration="long", params=params_from_signature(fn) or None,
                      limits=limits.get(name), approval=approval.get(name, "auto"),
                      notes=(inspect.getdoc(fn) or "").split("\n")[0] or None)

    sigs = [Signal("setup_finished", read=lambda: bool(getattr(machine, "setup_finished", False)), type="boolean")]
    for n, fn in (signals or {}).items():
        sigs.append(Signal(n, read=fn))

    def do_setup():
        if setup and hasattr(machine, "setup"):
            loop.run(machine.setup())

    def do_stop():
        if hasattr(machine, "stop"):
            loop.run(machine.stop(), timeout=30)

    return BoundDriver(device=device, physical=physical, signals=sigs,
                       actions=[make_action(n) for n in names], estop=do_stop, setup=do_setup,
                       extra={"pylabrobot": {"machine": type(machine).__name__,
                                             "backend": type(getattr(machine, "backend", None)).__name__}})
