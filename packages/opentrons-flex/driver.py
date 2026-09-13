"""Opentrons Flex through PyLabRobot. Requires: pip install pylabrobot"""
import os

from openmhp.adapters.pylabrobot import plr_device

ROBOT_HOST = os.environ.get("OPENTRONS_HOST", "192.168.1.50")

from pylabrobot.liquid_handling import LiquidHandler                      # noqa: E402
from pylabrobot.liquid_handling.backends.opentrons_backend import OpentronsBackend   # noqa: E402
from pylabrobot.resources.opentrons import OTDeck                         # noqa: E402

lh = LiquidHandler(backend=OpentronsBackend(host=ROBOT_HOST, port=31950), deck=OTDeck())

DEVICE = plr_device(lh, device={},
    actions=["pick_up_tips", "drop_tips", "aspirate", "dispense", "move_plate", "move_lid"],
    limits={"aspirate": {"vols": [0, 1000]}, "dispense": {"vols": [0, 1000]}})
