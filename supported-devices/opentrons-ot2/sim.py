"""Simulated twin of the OT-2: PyLabRobot's chatterbox backend when pylabrobot is installed (it prints what it
would do), otherwise a fake LiquidHandler with the same surface, plus a fake door switch. Moves take a few
simulated seconds, scaled by OPENMHP_SIM_TIME_SCALE."""
from __future__ import annotations

import asyncio
import importlib.util
import os
import pathlib
import sys

_spec = importlib.util.spec_from_file_location(__name__ + "_real", pathlib.Path(__file__).with_name("driver.py"))
real = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = real
_spec.loader.exec_module(real)

WELLS = [f"{r}{c}" for c in range(1, 13) for r in "ABCDEFGH"]
DECK = {"tips_300": WELLS, "tips_20": WELLS, "src_plate": WELLS, "dst_plate": WELLS, "reservoir": [f"A{c}" for c in range(1, 13)],
        "trash": None}


class _Item:
    def __init__(self, parent, name): self.parent, self.name = parent, name
    def __repr__(self): return f"{self.parent}/{self.name}"


class _Resource:
    def __init__(self, name, wells): self.name, self.wells = name, wells
    def get_item(self, ident):
        if self.wells is None or ident not in self.wells:
            raise real.InvalidValue(f"no position {ident!r}")
        return _Item(self.name, ident)
    def __repr__(self): return self.name


class _Deck:
    def __init__(self, layout): self.layout = layout
    def get_resource(self, name):
        if name not in self.layout:
            raise real.InvalidValue(f"no resource {name!r}")
        return _Resource(name, self.layout[name])


class _FakeLH:
    def __init__(self, scale):
        self.scale, self.deck, self.log, self.tips = scale, _Deck(DECK), [], 0
    async def setup(self): self.log.append("setup")
    async def stop(self): self.log.append("stop")
    async def _move(self, s): await asyncio.sleep(s * self.scale)
    async def pick_up_tips(self, spots):
        await self._move(5); self.tips = len(spots); self.log.append(("pick_up_tips", [repr(s) for s in spots]))
    async def drop_tips(self, spots):
        await self._move(5); self.tips = 0; self.log.append(("drop_tips", [repr(s) for s in spots]))
    async def aspirate(self, wells, vols, flow_rates=None):
        if not self.tips:
            raise real.DeviceFault("no tips mounted")
        await self._move(8); self.log.append(("aspirate", [repr(w) for w in wells], vols))
    async def dispense(self, wells, vols, flow_rates=None):
        if not self.tips:
            raise real.DeviceFault("no tips mounted")
        await self._move(8); self.log.append(("dispense", [repr(w) for w in wells], vols))


class SimBackend:
    def __init__(self, scale): self.scale, self.lh, self.door = scale, None, False

    def build(self):
        try:
            from pylabrobot.liquid_handling import LiquidHandler
            from pylabrobot.liquid_handling.backends import LiquidHandlerChatterboxBackend
            from pylabrobot.resources.opentrons import OTDeck
            self.lh = LiquidHandler(backend=LiquidHandlerChatterboxBackend(), deck=OTDeck())
        except ImportError:                                      # keep the twin usable without pylabrobot
            self.lh = _FakeLH(self.scale)
        return self.lh

    def door_open(self):
        return self.door


def Sim():
    scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
    backend = SimBackend(scale)
    drv = real.build(real.Machine(backend))
    drv.server = backend                                         # .lh.log for assertions, .door to flip the switch
    return drv
