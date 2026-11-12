---
mhp: "2026-09-12"
id: ossila-spin-coater-01
class: spin_coater
make: Ossila
model: Spin Coater L2001A3 (120-6,000 rpm) and L2001B1 (500-10,000 rpm)
location: ""
tags: [spin-coater, thin-film, perovskite, organic-electronics, glovebox, serial, template]
description: Ossila Spin Coater (L2001A3 and the higher-speed L2001B1), the compact unit for gloveboxes and benches that holds substrates on the chuck without vacuum, written as a TEMPLATE whose USB serial command frames are unverified placeholders. Reads chuck speed, lid state, program and step; runs a typed recipe of steps (speed, acceleration, duration) written into one of the unit's programs; stops the chuck. Pick it for spin coating of perovskite, polymer and small-molecule films on small substrates inside a glovebox; not for vacuum chucks (the unit has none), and not without Ossila's command set written into the descriptor.
driver: driver.py:Device
sim: sim.py:Sim
---

# Ossila Spin Coater (USB serial template)

A small spin coater built for gloveboxes: a central chuck that holds substrates by their edges
(no vacuum), a lid with a software/hardware interlock, a colour touch display, and 10 programs of
up to 50 steps (15 programs on the L2001B1). The L2001A3 spins 120-6,000 rpm with 1-1,000 s steps;
the L2001B1 500-10,000 rpm with 1-3,600 s steps and better than 0.25 % speed stability. The
*Spin Coater User Manual* (version 3.1.B, product code L2001A3/L2001B1, product version 3.0/1.0)
says the unit is operated from its display and needs no PC, and it publishes no command set, so
every command in `descriptor.yaml` is a **placeholder** marked unverified in `references/serial.md`.
Ossila's other instruments (the solar simulator, the monochromator) are driven by serial commands
over their USB port; ask Ossila whether the spin coater's firmware offers the same, and rewrite the
`serial:` block from their answer.

## Operating procedure

1. Read `connected` and `lid_closed`. The unit will not spin with the lid open; there is no
   vacuum to check, which is why no `vacuum_ok` signal is declared.
2. Place the substrate in the chuck, pipette the solution, close the lid.
3. Invoke `run_recipe {steps: [{speed_rpm, acceleration_rpm_s, duration_s}, ...], slot: 10}`.
   The steps are written into the program slot and the program is started; the job returns the
   unit's replies. Poll `running`, `speed_rpm` and `step` until `running` is false. A perovskite
   two-step recipe (1,000 rpm 10 s, 4,000 rpm 30 s) takes under a minute.
4. Open the lid only when `speed_rpm` reads 0; `robot_access_ready` is true with the lid open and
   the chuck still.
5. `stop` ends a run at once. E-stop sends the same stop.

## What to watch

- Acceleration: the unit ramps between steps at a settable rate; the 2,000 rpm/s placeholder cap
  is a guess for a 25 mm substrate held by its edges, not a published figure. Set it to what your
  substrates survive.
- The L2001A3 cannot hold below 120 rpm; a 0 rpm step stops the chuck.
- Solvent vapour collects under the lid; in a glovebox the box's circulation takes it.
- Until the command set is known, an error reply or a timeout on every command is the expected
  behaviour on a real unit.

## Resources

- `references/serial.md`: the placeholder command set, what the manual says about the unit, and the recipe limits per model.
- `references/setup.md`: cable, port, first hardware test, status.
