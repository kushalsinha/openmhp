"""Simulated twin of the STAR: PyLabRobot's STARChatterboxBackend when pylabrobot is installed (it prints
every firmware command it would send), otherwise a fake LiquidHandler with the same surface, so the twin
runs without any vendor library. Moves take a few simulated seconds, scaled by OPENMHP_SIM_TIME_SCALE."""
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

DECK = {"tips_1000": [f"{r}{c}" for c in range(1, 13) for r in "ABCDEFGH"],
        "tips_300": [f"{r}{c}" for c in range(1, 13) for r in "ABCDEFGH"],
        "src_plate": [f"{r}{c}" for c in range(1, 13) for r in "ABCDEFGH"],
        "dst_plate": [f"{r}{c}" for c in range(1, 13) for r in "ABCDEFGH"],
        "trash": None, "site_1": None, "site_2": None}


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


class _FakeSTAR:
    """Enough of STARBackend for the driver: the cover sensor and stop()."""
    def __init__(self): self.cover = False
    async def request_cover_open(self): return self.cover


class _FakeLH:
    def __init__(self, scale):
        self.scale, self.deck, self.backend, self.log, self.tips = scale, _Deck(DECK), _FakeSTAR(), [], 0
    async def setup(self): self.log.append("setup")
    async def stop(self): self.log.append("stop")
    async def _move(self, s): await asyncio.sleep(s * self.scale)
    async def pick_up_tips(self, spots):
        await self._move(4); self.tips = len(spots); self.log.append(("pick_up_tips", [repr(s) for s in spots]))
    async def drop_tips(self, spots):
        await self._move(4); self.tips = 0; self.log.append(("drop_tips", [repr(s) for s in spots]))
    async def aspirate(self, wells, vols, flow_rates=None):
        if not self.tips:
            raise real.DeviceFault("no tips mounted")
        await self._move(6); self.log.append(("aspirate", [repr(w) for w in wells], vols))
    async def dispense(self, wells, vols, flow_rates=None):
        if not self.tips:
            raise real.DeviceFault("no tips mounted")
        await self._move(6); self.log.append(("dispense", [repr(w) for w in wells], vols))
    async def move_plate(self, plate, to):
        await self._move(15); self.log.append(("move_plate", repr(plate), repr(to)))


class SimBackend:
    def __init__(self, scale): self.scale, self.lh = scale, None

    def build(self):
        try:
            from pylabrobot.liquid_handling import LiquidHandler
            from pylabrobot.liquid_handling.backends.hamilton.STAR_chatterbox import STARChatterboxBackend
            from pylabrobot.resources import STARLetDeck
            self.lh = LiquidHandler(backend=STARChatterboxBackend(), deck=STARLetDeck())
        except ImportError:                                      # keep the twin usable without pylabrobot
            self.lh = _FakeLH(self.scale)
        return self.lh


def Sim():
    scale = float(os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.01"))
    backend = SimBackend(scale)
    machine = real.Machine(backend)
    drv = real.build(machine)
    drv.server = backend.lh                                      # the test asserts on its log and flips the cover
    return drv
