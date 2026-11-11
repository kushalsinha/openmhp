---
mhp: "2026-09-12"
id: tecan-cavro-pump-01
class: pump
make: Tecan
model: Cavro XLP 6000 / XCalibur (DT protocol)
location: ""
tags: [syringe-pump, oem, aspirate, dispense, biology, serial]
description: Tecan Cavro XLP 6000 or XCalibur OEM syringe pump driven over RS-232 with the Cavro DT protocol (/1ZR initialise, A/P/D plunger moves, I/O valve, Q status). Initialises, aspirates and dispenses volumes converted to plunger steps from the syringe size in config.json, switches the valve, and waits for each move to finish. Use for microlitre-precise liquid transfer from a fixed syringe; one package instance per pump at DT address 1.
driver: driver.py:Device
sim: sim.py:Sim
---

# Tecan Cavro XLP 6000 / XCalibur syringe pump

An OEM syringe pump module: a stepper-driven plunger with 6000 increments per full stroke on the XLP 6000
(3000 on the XCalibur, 8x more in fine-positioning mode) and a rotary valve. It speaks the Cavro DT
protocol: a frame is `/`, the address character (`1` for address switch 0), a string of commands and `R`
to run them, ending in CR; the answer is `/0`, a status byte, data, ETX. Put the port, the syringe
volume and the full-stroke step count under `port`, `syringe_ul` and `steps_full_stroke` in
`config.json` (see `references/setup.md`): the driver converts `volume_ul` to steps from those two
numbers, so a wrong `syringe_ul` moves the wrong volume.

## Operating procedure

1. Read `firmware` and `status_reply` to confirm the link (`` /0` `` with bit 5 set means ready, low nibble 0 means no error).
2. Invoke `initialize` (`ZR`) once after power-on: it drives the plunger to the top and homes the valve, and
   a person confirms because it moves the plunger through its full travel with whatever is in the syringe.
   Every move before it is refused by the pump with error 7.
3. Invoke `valve_input`, then `aspirate` with `volume_ul`; the action sends the move and polls `Q` until the
   pump is ready, then returns. Invoke `valve_output`, then `dispense`.
4. Read `plunger_position` (steps from the top) to confirm where the plunger stands; `move_to` goes to an
   absolute volume.
5. `terminate` (`T`) stops a plunger move at once; `estop` sends the same.

## What to watch

- A status byte with a non-zero low nibble is an error: 1 initialisation, 2 invalid command, 3 invalid
  operand, 7 not initialised, 9 plunger overload, 10 valve overload, 11 move not allowed. `references/dt-protocol.md`
  has the table. After 9 or 10 the pump needs a new `initialize`.
- `aspirate` past the stroke (more than `syringe_ul` left in the syringe) is refused before anything is sent.
- `speed_code` and `top_velocity` change how hard the plunger pulls; too fast on a viscous liquid cavitates
  or overloads.
- Fine-positioning mode (`N1`) multiplies the step count by 8; set `steps_full_stroke` accordingly if it is on.

## Resources

- `references/setup.md`: cable, address switch, baud, syringe size, first hardware test.
- `references/dt-protocol.md`: the DT protocol frames and commands this package uses, with sources.
