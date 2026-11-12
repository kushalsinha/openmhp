---
mhp: "2026-09-12"
id: eurotherm-tube-furnace-01
class: furnace
make: Eurotherm (Carbolite Gero, MTI, Thermcraft furnaces)
model: 2416 / 2404 / 2408 programmer-controllers (2400 series Modbus map); 3216 / 3508 / nanodac need their own map
location: ""
tags: [furnace, tube-furnace, sintering, annealing, cvd, modbus]
description: Tube and box furnaces from Carbolite Gero, MTI, Thermcraft and others whose heater is run by a Eurotherm 2400-series programmer-controller (2416, 2404, 2408) over Modbus RTU on EIA-485/232 or a Modbus TCP gateway. Reads the process temperature, working setpoint, output power, program status, segment and time remaining; writes the target setpoint with confirmation; runs, holds and resets a program stored on the controller, and can write a typed ramp/dwell program into a program slot first. Pick it for annealing, sintering, CVD and calcination under a controller program; the register map is the 2400 series one (HA026230) and must be swapped for the iTools map on 3216, 3508 or nanodac controllers.
driver: driver.py:Device
sim: sim.py:Sim
---

# Eurotherm 2400-series furnace controller (Modbus)

The furnace itself is passive: a Eurotherm 2416 (or 2404/2408) PID programmer-controller in the
furnace's console drives the heater and holds up to 20 programs of 16 segments. Its EIA-485 or
EIA-232 port speaks Modbus RTU; every parameter is a holding register whose address is listed in
the *Series 2000 Communications Handbook* (HA026230, Issue 3). The package writes the stored
program's segments if you give typed ones, selects the program, and sets the program status to
Run, Hold or Reset. Values are integers in the controller's display resolution (usually whole
degrees), which is why every temperature here has resolution 1.

## Operating procedure

1. Read `connected`, `temperature`, `program_status_code` and `manual_mode`. Status 1 (reset)
   and auto mode (manual_mode false) are where a firing starts; status 16 means the last
   program completed.
2. To run a program already stored on the controller: invoke `run_program {program: N}`. A
   person confirms because it heats the tube. The job returns when the Run command is written;
   the firing runs for hours under the controller. Poll `program_running`, `segment`,
   `segment_type_code`, `temperature` and `program_time_remaining`.
3. To write the program first: invoke `run_program {program: N, segments: [{target_c,
   ramp_c_per_min, dwell_min}, ...]}`. Each typed segment becomes a rate ramp plus a dwell in
   program N's block (up to 7 typed segments in the 16-segment block, then an End segment),
   with ramp and dwell units set to minutes. Program 1 is the safe default slot.
4. `hold_program` freezes the programmer setpoint; `run_program` with the same number resumes
   it from Hold. `reset_program` abandons the firing and needs a person's confirmation.
5. For a plain setpoint hold (no program), write `target_setpoint` (confirmed) with the
   programmer in Reset; the controller drives to it immediately at its configured rate limit.
6. Let the tube cool under the program's last segment; work tubes crack if the end caps are
   removed hot. Loading is by a person; the controller has no input that reports whether the
   tube is closed.

## What to watch

- Resolution: the 2400 series sends integers in display units. A controller configured with one
  decimal place reports 1234 for 123.4 degC; if your readings are ten times too high, set
  `scale: 0.1` on the temperature registers in descriptor.yaml (or read the IEEE float region the
  handbook describes at 0x8000 + 2 x address).
- The segment-edit addresses are the 2400 series ones (program 1 at 8328, 136 registers per
  program, 8 per segment). Writes to a program that is running are rejected by the controller;
  write only in Reset or Hold.
- `program_number` (22) selects the program for Run; the handbook lists its address in the Run
  list but its write behaviour is marked unverified in `references/registers.md`.
- The 3216, 3508 and nanodac have different parameter addresses (Eurotherm iTools shows them);
  rewrite the `modbus:` block from that map before using this package on one.
- Watchdog action is `release`: a controller that goes silent loses the lease and the furnace
  finishes its program, because an aborted sinter is the damage.

## Resources

- `references/registers.md`: the Modbus addresses used, from HA026230 Issue 3, with the unverified rows marked.
- `references/setup.md`: wiring, pymodbus, controller comms settings, first hardware test, status.
