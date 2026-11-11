---
mhp: "2026-09-12"
id: hamilton-star-01
class: liquid_handler
make: Hamilton
model: Microlab STAR / STARlet (Vantage via the STAR backend)
location: ""
tags: [pipetting, liquid-handling, plates, pylabrobot, iswap, pharma-biologics]
description: Hamilton Microlab STAR or STARlet liquid handler driven through PyLabRobot over USB. Pick it for channel pipetting between named labware on its deck (tips up, aspirate, dispense, tips off, 0.5-1000 uL per channel) and for moving plates between carrier sites with the iSWAP. It reports whether the front cover is open so a handling robot knows when it may load the deck. Not for VENUS methods or the 96-head, and not for labware missing from the deck layout file.
driver: driver.py:Device
sim: sim.py:Sim
---

# Hamilton Microlab STAR (PyLabRobot)

PyLabRobot talks to the STAR's firmware directly over USB, so Hamilton's VENUS software must be
closed. The deck is described once in a PyLabRobot deck layout file (`config.json: deck_file`),
and every request names resources from it: a tip spot as `tips_1000/A1`, a well as `src_plate/A1`,
a plate or site by its name. Volumes are per channel; the tip on the channel sets the real ceiling.

## Operating procedure

1. Read `connected`. If false, `connect_error` says why (library, USB, initialisation); check the
   cable and that VENUS is closed.
2. Confirm the physical deck matches the layout file (carriers in the right tracks, racks and plates
   on the named sites). PyLabRobot cannot see what is on the deck.
3. `pick_up_tips` from a rack, then `aspirate` and `dispense` with wells named as in the deck file,
   then `drop_tips` into `trash`.
4. `move_plate` uses the iSWAP; keep the path clear and never reach in while it moves.
5. A handling robot loads or unloads the deck only when `robot_access_ready` is true (cover open,
   connected, nothing running). Close the cover before pipetting resumes.
6. `safety/estop` stops the session; after a physical STOP a person re-initialises the instrument.

## What to watch

- Volumes above the mounted tip's capacity: the descriptor caps at 1000 uL (1000 uL channels); set
  the limits lower for 300 uL channels and lower still when 50 uL tips are in use.
- A failed action leaves the device in `fault` with an unknown outcome; tips may be on the channels.
  Read the error, clear the deck problem, `safety/reset`, then `drop_tips`.
- `cover_open` null means the instrument has no cover monitoring; then `robot_access_ready` never
  reads true and loading needs a person.

## Resources

- `references/setup.md`: PyLabRobot install, USB, the deck layout file, first hardware test.
- `references/pylabrobot.md`: the PyLabRobot members this package calls and what was verified.
- `config.example.json`: deck layout file, deck type, USB selection.
