---
mhp: "2026-09-12"
id: palmsens-potentiostat-01
class: potentiostat
make: PalmSens
model: EmStat Pico, EmStat4 LR/HR, Sensit (MethodSCRIPT over USB virtual COM)
location: ""
tags: [potentiostat, electrochemistry, voltammetry, chronoamperometry, methodscript, serial]
description: A PalmSens MethodSCRIPT potentiostat (EmStat Pico, EmStat4 LR or HR, Sensit) on a USB virtual COM port. Pick it to run chronoamperometry, cyclic or linear sweep voltammetry, or an open-circuit potential record on a three-electrode cell, with typed potentials, scan rates and durations, and to get back a CSV of (time, potential, current) and the final values. One channel, one technique at a time; impedance (EIS), pulsed techniques and multiplexers are not wired here.
driver: driver.py:PalmSensPotentiostat
sim: sim.py:SimPalmSensPotentiostat
---

# PalmSens MethodSCRIPT potentiostat

The instrument appears as a serial port (230400 baud on an EmStat Pico, 921600 on an EmStat4 or Nexus).
Every technique is one MethodSCRIPT script built from the parameters and sent whole; the instrument
streams data packages back and switches the cell off when the script ends, is aborted, or errors.
PSTrace must be closed while this package holds the port.

## Operating procedure

1. Read `connected`, `device_type` and `firmware`.
2. Write `current_range_max_A` to the largest current the cell may pass; the scripts autorange up to it.
3. Invoke `ocp` for a few seconds first and read `e_final_V`: a drifting or absurd open-circuit potential
   means a bad reference or an open lead; do not apply potentials until it is sensible.
4. Invoke `ca`, `cv` or `lsv` with potentials within the lab's bounds (the shipped +/-1.2 V is a placeholder).
   Poll the job; `running` and `cell_on` are true while it streams. Cancelling the job sends `Z`, which
   aborts the script and turns the cell off.
5. Read the job result: the CSV path, point count, final potential and current, and the script that ran.

## What to watch

- A MethodSCRIPT error (`!xxxx`) fails the job with its code; the instrument has already switched the cell
  off. Common causes: a potential outside the instrument's range, a step larger than the sweep.
- `cell_on` is tracked by the driver from the scripts it sends; it does not read the instrument back.
- The twin is an EmStat Pico-shaped device with one reversible couple at +0.25 V; real currents depend on
  the cell.
- Emergency stop aborts the script and sends `cell_off`.

## Resources

- `references/setup.md`: pyserial, the COM port, baud rate, config.json and the first hardware test.
- `references/methodscript.md`: the MethodSCRIPT commands, data package format and sources, with what is unverified.
- `config.example.json`: port, baud, data folder, maximum run time.
