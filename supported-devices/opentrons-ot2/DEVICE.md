---
mhp: "2026-09-12"
id: opentrons-ot2-01
class: liquid_handler
make: Opentrons
model: OT-2
location: ""
tags: [pipetting, liquid-handling, plates, pylabrobot, biology]
description: Opentrons OT-2 liquid handler driven through PyLabRobot's OT-2 backend over the robot's HTTP API. Pick it for single- or 8-channel pipetting between named labware in its deck slots (tips up, aspirate, dispense, tips off, 1-1000 uL depending on the pipette mounted). It reads the door switch so a handling robot knows when it may load the deck. No gripper, so it does not move plates; not for Opentrons App protocols, and not for labware missing from the deck layout file.
driver: driver.py:Device
sim: sim.py:Sim
---

# Opentrons OT-2 (PyLabRobot)

PyLabRobot drives the OT-2 through the robot's own HTTP API (port 31950), creating a run and
sending pipetting commands to it. The deck is described once in a PyLabRobot deck layout file
(`config.json: deck_file`); every request names labware from it: a tip spot as `tips_300/A1`, a
well as `src_plate/A1`, the fixed trash as `trash`. The Opentrons App may stay open but must not
run a protocol at the same time.

## Operating procedure

1. Read `connected`. If false, `connect_error` says why (library, network, no pipette attached).
2. Confirm the labware in the slots matches the layout file; the OT-2 cannot see its deck.
3. `pick_up_tips` (one spot for a single-channel pipette, a column of eight for the 8-channel),
   then `aspirate` and `dispense` with wells named as in the deck file, then `drop_tips` into
   `trash`.
4. A handling robot loads or unloads slots only when `robot_access_ready` is true (door open,
   nothing running). The OT-2 pauses itself if the door opens mid-run when that setting is on.
5. `safety/estop` cancels the run and halts the gantry; afterwards `mhp_lab op='reload'` re-runs
   setup so the robot homes again.

## What to watch

- Volumes outside the mounted pipette's range: the descriptor spans 1-1000 uL; set the limits to
  the pipette in use (P20 1-20, P300 20-300, P1000 100-1000) as a package edit.
- A failed action leaves the device in `fault` with tips possibly on the pipette; read the error,
  clear the deck, `safety/reset`, then `drop_tips`.
- `door_open` null means the robot did not answer the door query; treat the deck as not accessible.

## Resources

- `references/setup.md`: PyLabRobot install, robot address, the deck layout file, first hardware test.
- `references/pylabrobot.md`: the PyLabRobot members and the HTTP door endpoint this package calls.
- `config.example.json`: robot address, port, deck layout file.
