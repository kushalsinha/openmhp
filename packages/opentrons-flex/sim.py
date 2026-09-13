"""Simulated twin: PyLabRobot's chatterbox backend prints what it would do. Requires pylabrobot."""
from openmhp.adapters.pylabrobot import plr_device

try:
    from pylabrobot.liquid_handling import LiquidHandler
    from pylabrobot.liquid_handling.backends import LiquidHandlerChatterboxBackend
    from pylabrobot.resources.opentrons import OTDeck
    lh = LiquidHandler(backend=LiquidHandlerChatterboxBackend(), deck=OTDeck())
except ImportError:                                    # keep the twin usable without pylabrobot
    class _Fake:
        setup_finished = False
        async def setup(self): self.setup_finished = True
        async def stop(self): pass
        async def pick_up_tips(self, resources: list): return None
        async def drop_tips(self, resources: list): return None
        async def aspirate(self, resources: list, vols: list): return None
        async def dispense(self, resources: list, vols: list): return None
        async def move_plate(self, plate: str, to: str): return None
    lh = _Fake()

Sim = lambda: plr_device(lh, device={}, actions=["pick_up_tips", "drop_tips", "aspirate", "dispense", "move_plate"],   # noqa: E731
                         limits={"aspirate": {"vols": [0, 1000]}, "dispense": {"vols": [0, 1000]}})
