---
mhp: "2026-09-12"
id: sigma-4-16ks-centrifuge-01
class: centrifuge
make: Sigma Laborzentrifugen
model: 4-16KS (Spincontrol serial interface; 3-18KS, 4-5KRL, 4-16KR and other Spincontrol models)
location: ""
tags: [centrifuge, refrigerated, benchtop, spincontrol, serial, robot]
description: Sigma 4-16KS benchtop refrigerated centrifuge (and every Sigma centrifuge with Spincontrol electronics and the RS-232 option) through Sigma's plain-text serial control interface, word commands such as speed, temp, setspeed, start, stop and door at 9600 baud. Reads rotor speed, chamber temperature, remaining time, the setpoints and the lid state; sets speed, temperature and run time; starts, stops and opens the lid. Pick it to spin plates or tubes under agent control with the lid interlock and robot-access readiness exposed; it does not know which rotor is fitted, so the lab sets the speed limit.
driver: driver.py:Device
sim: sim.py:Sim
---

# Sigma 4-16KS centrifuge (Spincontrol serial interface)

A benchtop refrigerated centrifuge with swing-out or fixed-angle rotors, controlled through the
word-oriented "Spincontrol" serial protocol Sigma documents in its manuals. The same protocol runs
on the other Spincontrol models (3-18KS, 4-5KRL, 4-16KR, 2-16KL, 8KS); the robot variants add
positioning and lifter commands that this package does not use.

## Operating procedure

1. Read `status_code`, `lid_closed`, `speed`, `temperature` to see the state a person left it in.
   `robot_access_ready` is true exactly when the lid is open and the rotor stands still: load or unload then.
2. Close the lid (a person, or the robot's lid-closing fixture), confirm `lid_closed`.
3. Invoke `start` with `speed` (rpm), `temperature` (degC) and `time_s`; the package writes the three setpoints
   and sends `start`. The job returns at once; follow the spin with `speed`, `time_remaining` and `status_code`.
4. `stop` decelerates on the set brake curve; `fast_stop` brakes hard. Wait for `standstill` before `open_lid`
   (confirm), which the centrifuge refuses while the rotor turns.
5. If `status_code` reads 3 (error), read `error_code`, fix the cause (imbalance, lid, over-temperature) and invoke `reset_error`.

## What to watch

- The rotor sets the real speed limit: the centrifuge refuses a `setspeed` above the fitted rotor's maximum (with echo on it answers `ERR`; with echo off, silently) and the descriptor's cap is a placeholder. Set it to the slowest rotor you use.
- Balance the load; an imbalance shutdown shows as `status_code` 3 with `error_code` set and bit 4 of `status1`.
- The refrigerated chamber takes several minutes to reach a low setpoint; pre-cool with a short spin.
- Replies are plain numbers; the centrifuge also prints a `SIGMA>` prompt that the parse rules skip.

## Resources

- `references/setup.md`: cable, port, interface option, limits to set, first hardware test.
- `references/protocol.md`: the Spincontrol commands and status codes this package uses, from Sigma's interface specification.
