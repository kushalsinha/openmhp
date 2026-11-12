---
mhp: "2026-09-12"
id: retsch-planetary-mill-01
class: mill
make: Retsch
model: PM 100 / PM 200 / PM 400 (serial interface)
location: ""
tags: [milling, ball-mill, planetary, materials-synthesis, mechanochemistry, serial, template]
description: Retsch PM 100, PM 200 and PM 400 planetary ball mills over the serial (RS-232/RS-485) socket of the newer units, written as a TEMPLATE whose command set is a placeholder; Retsch's interface description was not available and every command is unverified. Pick it to run a timed grind at a set speed with the lid interlock honoured, to stop the drive, and to read speed, remaining time and lid state; not for direction-reversal intervals, interval grinding or jar clamping, which stay at the front panel. Confirm every command against Retsch's interface description before touching a real mill.
driver: driver.py:Device
sim: sim.py:Sim
---

# Retsch PM 100 / PM 200 / PM 400 planetary ball mill (serial template)

A planetary ball mill grinds and mechanochemically reacts powders in sealed jars (12 mL to
500 mL) clamped on a sun wheel; the PM 100 and PM 200 run 100-650 rpm, the PM 400 30-400 rpm.
The jars are clamped by hand, the lid closes by hand, and the mill's own lid lock keeps it
shut while the sun wheel turns. The newer units carry a serial socket; Retsch's public manuals
(PM 100/200 operating instructions, PM 400 manual GB 98.535.9999) only say the RS-232 socket is
for software updates and the RS-485 socket is for "optional data communication, inactive".
The command set in `descriptor.yaml` is therefore a **placeholder** (`references/protocol.md`):
rewrite the `serial:` block from Retsch's interface description before first hardware use.

## Operating procedure

1. Read `connected`, `lid_closed` and `running`. Clamp the jars and close the lid by hand; the
   mill refuses `run` while `lid_closed` is false.
2. Invoke `run` with `speed` (rpm) and `duration_s`: the package writes the speed and time
   setpoints and sends the start command. The job completes once the commands are sent; the
   grind runs on the mill and ends by itself when `time_remaining` reaches 0. Each `run` is
   confirmed by a person: a 650 rpm sun wheel with unbalanced or badly clamped jars is the hazard.
3. Watch `speed` and `time_remaining`. `stop` ends a grind early; the e-stop sends the same
   stop command. Grinding heats the jars: let them cool before opening (the manual's cooling
   advice applies to every grind above a few minutes).
4. Open the lid only after `running` reads false and `speed` reads 0. `robot_access_ready`
   reads true when the lid is open and the drive is at rest, which is when a handling system
   may reach the jars; the lid itself is opened by hand or the lab's own actuator.

## What to watch

- `speed` not following `speed_setpoint_actual` within a few seconds of `run`: the mill's own
  imbalance or lid-lock check stopped it; look at the front panel and reset there.
- The lab must set the speed and time limits in `descriptor.yaml` to what its jars and media
  allow (small jars and a loaded sun wheel have lower safe speeds; see the Retsch manual's
  balancing table).
- Every command is unverified until the first hardware test in `references/setup.md` passes.

## Resources

- `references/protocol.md`: the placeholder command table, what the public manuals say about
  the serial sockets, and what must be confirmed.
- `references/setup.md`: cable, pyserial, port, first hardware test and status.
- `config.example.json`: the serial port.
