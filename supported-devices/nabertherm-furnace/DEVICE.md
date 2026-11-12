---
mhp: "2026-09-12"
id: nabertherm-furnace-01
class: furnace
make: Nabertherm
model: B400 / B410 / C440 / C450 / P470 / P480 (and series 500) controllers with the Modbus TCP communication module
location: ""
tags: [furnace, sintering, calcination, muffle, tube-furnace, modbus]
description: Nabertherm muffle, chamber and tube furnaces run by a B400/B410, C440/C450 or P470/P480 controller (and the series 500 successors) with the Modbus TCP communication module. Reads the control-zone and charge temperatures, program setpoint, output power, status, program and segment number, alarms and malfunctions; starts, pauses and stops a stored program; on P-controllers transfers a typed ramp/dwell program and runs it; and drives the external-setpoint mode with a person's confirmation. Pick it for sintering, calcination, annealing and burn-out under a controller program, not for atmosphere or gas control (those are the furnace's own extra functions) and not for furnaces without the communication module.
driver: driver.py:Device
sim: sim.py:Sim
---

# Nabertherm furnace (series 400/500 controller, Modbus TCP)

A laboratory or industrial furnace whose controller carries Nabertherm's communication module
and answers Modbus TCP on port 502: holding registers 100-151 report the state, 148-150 start,
stop, pause and jump segments of a program, 200-404 take a transferred program on P470/P480 and
series 500 P-controllers, and 405-409 run the external setpoint mode. Everything below comes from
Nabertherm's *Operating Instructions, Communication Module for Nabertherm Series 400/500
Controllers* (M03.0021, 2024-11); the package has not yet been run on a furnace.

## Operating procedure

1. Read `connected`, `controller_type_code`, `temperature`, `status_code` and `max_temperature`.
   The status must be 0 (off) or 4 (end) before anything is started; 6 is a malfunction, read
   `malfunction_code` and clear it at the controller.
2. To run a program stored on the controller: invoke `run_program {program: N}` (1-50). A person
   confirms because it heats the chamber. The job returns as soon as the start command is
   written; the firing itself takes hours. Poll `program_running`, `segment`, `temperature` and
   `program_time_remaining`.
3. To run a typed program (P-controllers only): invoke `run_program {segments: [{target_c,
   ramp_c_per_min, dwell_min}, ...]}`. Each typed segment becomes a rate ramp plus a dwell on the
   controller (up to 19 typed segments). The driver waits for `program_transferred` before it
   starts. On B/C controllers the transfer is refused by the controller: use a stored program.
4. `pause_program` holds the current segment; `segment_jump {offset: -1}` repeats the dwell when a
   charge needs longer. `stop_program` needs a person's confirmation: an interrupted sinter is
   usually ruined.
5. For a setpoint held from outside (a reactor loop, a calibration), write `external_setpoint`
   and invoke `start_external_setpoint`; invoke `stop_external_setpoint` when done. Both are
   confirmed by a person.
6. Let the furnace cool under its own program; never open it hot. Loading and unloading is by a
   person; the controller has no input that reports whether the furnace is closed.

## What to watch

- All temperatures are in tenths of a degree in the controller's unit (`temperature_unit_code`
  0 = C, 1 = F); the package assumes Celsius and scales by 0.1. If the controller is set to
  Fahrenheit the limits here are wrong: switch it to Celsius.
- `program_time_remaining` is a 32-bit value whose unit the manual does not state; the package
  assumes minutes and marks it unverified.
- A transferred program lives in the controller until it ends; it must be transferred again
  before the next run, which `run_program` does on every call.
- The controller only checks a transferred program against the furnace maximum; it does not
  check plausibility (a 0 degC target is accepted and useless). The descriptor bounds every
  segment, and the shipped maximum (1300 degC) is a placeholder: set it to your furnace's Tmax
  (`max_temperature`).
- Watchdog action is `release`, not stop: a controller that goes silent loses the lease, and the
  furnace finishes its program on its own, because an aborted firing is the damage.

## Resources

- `references/registers.md`: the register map used here, from M03.0021, with the unverified rows marked.
- `references/setup.md`: network, pymodbus, controller settings, first hardware test, status.
