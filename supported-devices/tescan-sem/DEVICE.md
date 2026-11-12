---
mhp: "2026-09-12"
id: tescan-sem-01
class: electron_microscope
class_ref: CHMO:0000941
make: TESCAN
model: VEGA / MIRA / CLARA (SharkSEM remote control)
location: ""
tags: [sem, electron-microscope, imaging, tescan, sharksem, template, materials-characterization]
description: Template for a TESCAN VEGA, MIRA or CLARA scanning electron microscope through SharkSEM, TESCAN's remote-control TCP interface served by the microscope PC and reached with the client library TESCAN ships. Pick it to pump the chamber after a person or robot has closed the door, switch the beam on at a set high voltage, move the five-axis stage, auto-focus and acquire an SE or BSE image at a chosen view field, resolution and scan speed saved as a TIFF, then switch the beam off and vent for the next sample. SharkSEM is documented only to TESCAN customers, so every function name here is an unverified placeholder taken from config.json; the twin models the instrument faithfully. Not for EDS, FIB columns or TESCAN Essence recipes.
driver: driver.py:TescanSEM
sim: sim.py:SimTescanSEM
---

# TESCAN SEM (SharkSEM remote control): template

A TESCAN SEM runs its own control software on the microscope PC; SharkSEM is that software's remote
control interface, a TCP protocol with a client library TESCAN gives its customers (a `sem` module;
public example scripts connect to the microscope PC on a port in the 8300 range). The protocol is not
published, so this package is a template: the shape of a SharkSEM session (connect, vacuum, high
voltage, stage, scanning and image fetch, detectors) with every function name in config.json for the
lab to correct from TESCAN's SharkSEM manual. The twin models pumping, venting, beam run-up, stage
moves and image acquisition with realistic times and writes real TIFFs.

## Operating procedure

1. Read `connected`, `vacuum_status`, `vacuum_ready`, `beam_on` and `stage_position`.
   `robot_access_ready` is true when the chamber is vented and nothing moves, which is when a person
   or robot may open the door and exchange the stub.
2. After the door is closed: `load_sample` pumps the chamber and waits for the vacuum to be ready
   (a few minutes). Then `beam_on` true through `set_beam` at the `high_voltage` written.
3. `move_stage` to x, y (and z, rotation, tilt) in millimetres and degrees; the stage reports busy
   until it arrives.
4. `acquire_image` with magnification, pixel size, scan speed, frames and detector; `auto_focus:
   true` runs the auto working distance first. The result names the TIFF and the view field.
5. `unload_sample` switches the beam off and vents; `robot_access_ready` reads true once vented.
6. E-stop switches the high voltage off (beam off) and stops the stage; the chamber stays pumped.

## What to watch

- `vacuum_status` not reaching ready within the pump time: a leaking door seal or a wet sample.
- `beam_on` false after `set_beam`: the source needs its run-up time; the twin models ~30 s.
- Every function name is a placeholder until the lab checks it against the SharkSEM manual
  (`references/sharksem.md`); a wrong name fails the call with a DeviceFault naming it.

## Resources

- `references/setup.md`: enabling remote control on the microscope PC, the client library, the port,
  correcting the function names, the first hardware test.
- `references/sharksem.md`: the SharkSEM functions this package calls, their assumed arguments and
  units, the sources, and the full list of what is unverified.
- `config.example.json`: host, port, image folder; the function names as an advanced block.
