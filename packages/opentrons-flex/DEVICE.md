---
mhp: "2026-09-12"
id: opentrons-flex-01
class: liquid_handler
make: Opentrons
model: Flex
location: ""
tags: [pipetting, plates, biology, gripper]
description: Opentrons Flex liquid handler driven through PyLabRobot's Opentrons backend. Use for pipetting between labware on its deck, tip handling and moving plates with the gripper. Not for volumes below the pipette's minimum, and it will not move labware it does not know about; load the deck layout first.
sim: sim.py:Sim
---

# Opentrons Flex

Set the robot's IP under `ROBOT_HOST` in driver.py (or the `OPENTRONS_HOST` environment variable)
and describe the deck layout in `deck.py` following the PyLabRobot examples. Every public
coroutine of PyLabRobot's `LiquidHandler` becomes an action; the ones listed in driver.py are
exposed by default.

## Operating procedure

1. Read `setup_finished`. If false, the robot is not connected; check the network and `ROBOT_HOST`.
2. Confirm the deck layout matches what is physically loaded before any pipetting.
3. `pick_up_tips` from a tip rack, then `aspirate` and `dispense` with resources named as in the deck file, then `drop_tips`.
4. `move_plate` uses the gripper; keep hands out of the enclosure while it moves.
5. When finished, drop tips and home; `stop` (e-stop) halts motion and releases the gripper state as PyLabRobot defines.

## What to watch

- Volumes are capped in the descriptor at the pipette maximum; the driver refuses larger requests.
- A failed action leaves the device in `fault`; read the error, clear the deck problem, then reset.

## Resources

- `sim.py`: a simulated twin using PyLabRobot's chatterbox backend, for rehearsal without the robot.
