---
mhp: "2026-09-12"
id: agilent-dissolution-708ds-01
class: dissolution_tester
make: Agilent Technologies (Varian / VanKel)
model: 708-DS dissolution apparatus (template; VK 7000 / 7010 / 7025 family)
location: ""
tags: [dissolution, usp-apparatus-2, paddle, basket, pharma, serial, template]
description: TEMPLATE for the Agilent 708-DS dissolution apparatus (USP apparatus 1 and 2, 8 vessels, 850-DS sampling station optional) over its RS-232 port. The bath temperature, vessel temperatures, spindle speed, run state, setpoints, start/stop and dosage drop are declared with the shape a 708-DS has, but Agilent does not publish the serial command set, so every command in the serial block is a PLACEHOLDER frame marked unverified and must be replaced from a protocol trace or Agilent's documentation before the real driver is used. Pick this package to rehearse against the twin or as the starting point once the commands are known; do not point it at a bath.
driver: driver.py:Device
sim: sim.py:Sim
---

# Agilent 708-DS dissolution apparatus (template)

A USP apparatus 1/2 dissolution bath: eight vessels in a heated water bath, paddles or baskets on
a motorised drive head, optional dosage delivery module (DDM) for dropping tablets, optional 850-DS
sampling station. Agilent's Dissolution Workstation software drives it over a 25-pin RS-232 port at
9600 baud with 10-digit numeric frames (two-digit Comm ID, four-digit code, four-digit data), but
the codes are not published and Agilent says it has no command list for third parties. **This package
is therefore a template**: the signals, settings and actions are real 708-DS capabilities, the twin
behaves like a bath, and the frames in descriptor.yaml are placeholders that a real 708-DS will reject.
Read `references/setup.md` before doing anything with hardware.

## Operating procedure (as it will be once the commands are confirmed)

1. Read `bath_temperature`, `paddle_speed`, `run_state`; a bath takes 30 to 45 minutes to reach 37 degC from cold.
2. Write `temperature_setpoint` (37.0 for most monographs) and `paddle_speed_setpoint` (50 or 75 rpm) and `run_time`.
3. Confirm `vessel_temperature_1` (the AutoTemp probe) is within 0.5 degC of the setpoint before dosing.
4. Invoke `start_run` (confirm): the drive head lowers, spindles turn and the timer starts. With a DDM, invoke `drop_samples` to drop all eight tablets at once, usually at t = 0 of the run.
5. Sampling is the 850-DS's job, or a person's. `stop_run` stops the spindles; the heater stays on.

## What to watch

- Every number here is a placeholder reply from the twin until the frames are confirmed; `identity` is the only frame taken from a real trace.
- Dissolution methods (medium, volume, temperature, speed, sampling times) are per product and come from the monograph or the validated method; this package does not store them (no `methods/` folder) because the run action cannot yet be validated against the instrument.
- The bath heater is controlled by the 708-DS itself (or an external VK 750D circulator on older units); the e-stop placeholder stops the spindles and the heater.

## Resources

- `references/setup.md`: why this is a template, how to obtain the real command set (protocol trace or Agilent), cabling, and the first test once it is known.
- `references/protocol.md`: what is known of the 708-DS/VanKel serial link and the placeholder frames this package uses, every one marked unverified.
