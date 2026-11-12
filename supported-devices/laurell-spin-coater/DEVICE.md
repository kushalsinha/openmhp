---
mhp: "2026-09-12"
id: laurell-spin-coater-01
class: spin_coater
make: Laurell Technologies
model: WS-650 and WS-400 series spin processors with the 650 controller (RS-232 / USB to Spin 3000)
location: ""
tags: [spin-coater, thin-film, photoresist, perovskite, serial, template]
description: Laurell WS-650 and WS-400 series spin processors with the 650 controller, driven over the controller's RS-232/USB port, written as a TEMPLATE whose command frames are unverified placeholders. Reads chuck speed, lid and vacuum interlocks, vacuum level, program and step; runs a typed recipe of steps (speed, acceleration, duration) written into a program slot; stops the chuck; releases the chuck vacuum when the chuck is still. Pick it for spin coating of resists, sol-gels and perovskite inks on wafers and small substrates; not for the dispense valves (set in Spin 3000), and not without the command set from Laurell written into the descriptor.
driver: driver.py:Device
sim: sim.py:Sim
---

# Laurell WS-650 / WS-400 spin processor (650 controller, serial template)

A benchtop spin processor: a vacuum chuck in a bowl under a lid, a brushless motor to 12,000 rpm
(10,000 on the standard drive) with acceleration up to 30,000 rpm/s, and the 650 controller
whose keypad and LCD run up to 20 programs of 51 steps each. Laurell's Spin 3000 PC software
talks to the controller over RS-232 or USB to download programs and change the vacuum, sensor
and valve configuration. The *WS-650 Series Operations Manual* (revision 8/2016) names Spin 3000
as the PC interface but does not publish the serial protocol, so every command in
`descriptor.yaml` is a **placeholder** marked unverified in `references/serial.md`. Obtain the
remote command set from Laurell (support@laurell.com), rewrite the `serial:` block, and rehearse
with the twin until then.

## Operating procedure

1. Read `connected`, `lid_closed`, `vacuum_ok` and `vacuum_inhg`. The controller itself refuses
   to start below 15 inHg of chuck vacuum, so `vacuum_ok` is the same gate seen from here.
2. Place the substrate on the chuck, invoke `vacuum_on`, read `vacuum_ok` true, dispense, close
   the lid.
3. Invoke `run_recipe {steps: [{speed_rpm, acceleration_rpm_s, duration_s}, ...], slot: 20}`.
   The steps are written into the program slot and the slot is started; the job returns the
   controller's replies. Poll `running`, `speed_rpm` and `step` until `running` is false.
4. Invoke `vacuum_off` only when `speed_rpm` reads 0; the controller holds vacuum until the chuck
   stops anyway, and releases it 10 minutes after the last run or when the lid opens.
5. `robot_access_ready` is true with the lid open and the chuck still: that is when a handler may
   reach the chuck.
6. `stop` ends a run at once; the chuck decelerates under control. E-stop sends the same stop.

## What to watch

- The lid interlock in the controller stops the motor and the valves the moment the lid opens;
  the run can be resumed from the keypad. Over this link a stopped run must be started again.
- Acceleration above a few thousand rpm/s throws loosely placed substrates; the placeholders
  cap at 30,000 rpm/s only because that is the drive's maximum: set the recipe limits to what
  your substrates survive.
- Speed above 6,000 rpm on 4-inch wafers and above 3,000 rpm on glass slides is a chip hazard:
  the 12,000 rpm limit is the motor's, not the sample's.
- Until the command set is known, an `ES`-style reply or a timeout on every command is the
  expected behaviour on a real controller.

## Resources

- `references/serial.md`: the placeholder command set, what the manual says about the interface, and the recipe limits.
- `references/setup.md`: cable, port, controller settings, first hardware test, status.
