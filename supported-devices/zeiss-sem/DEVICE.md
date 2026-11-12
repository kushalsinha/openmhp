---
mhp: "2026-09-12"
id: zeiss-sem-01
class: electron_microscope
class_ref: CHMO:0000941
make: ZEISS
model: EVO / Sigma / GeminiSEM under SmartSEM (Remote API)
location: ""
tags: [sem, electron-microscope, imaging, zeiss, smartsem, template, windows, materials-characterization]
description: Template for a ZEISS EVO, Sigma or GeminiSEM scanning electron microscope under SmartSEM through the SmartSEM Remote API, the COM automation object ZEISS installs with SmartSEM on the microscope PC (Windows only). Pick it to pump the chamber after a person or robot has closed the door, switch the EHT on at a set voltage, move the five-axis stage, auto-focus and grab an SE or BSD image at a chosen magnification and size saved as a TIFF, then switch the EHT off and vent for the next sample. ZEISS documents the API only to licensees, so every COM member and parameter name here is an unverified placeholder taken from config.json; the twin models the instrument faithfully. Not for EDS, FIB columns, SmartSEM Touch or ZEN Core recipes.
driver: driver.py:ZeissSEM
sim: sim.py:SimZeissSEM
---

# ZEISS SEM (SmartSEM Remote API): template

SmartSEM runs the microscope on its Windows PC; the SmartSEM Remote API is a licensed COM
automation object installed with it (ZEISS's knowledge base describes installing the "Remote API
Client" so that ZEN can talk to SmartSEM, and a "SmartSEM API Test" desktop app). Its reference is
not public, so this package is a template: the shape of a remote session (initialise, Get/Set of
named parameters, Execute of named commands, an image grab) with every name in config.json for the
lab to correct from the API reference. The twin models pumping, venting, EHT run-up, stage moves and
image grabs with realistic times and writes real TIFFs.

## Operating procedure

1. Read `connected`, `vacuum_status`, `vacuum_ready`, `beam_on` and `stage_position`.
   `robot_access_ready` is true when the chamber is at atmosphere and nothing moves, which is when
   a person or robot may open the door and exchange the stub.
2. After the door is closed: `load_sample` pumps the chamber and waits for the vacuum ready state
   (a few minutes). Then `set_beam {enable: true}` at the `high_voltage` written (EHT on).
3. `move_stage` to x, y (and z, rotation, tilt) in millimetres and degrees; the job returns when the
   stage reports idle.
4. `acquire_image` with magnification, width, height, scan speed, frames and detector;
   `auto_focus: true` runs the auto-focus command first. The result names the TIFF and the
   magnification read back.
5. `unload_sample` switches the EHT off and vents; `robot_access_ready` reads true once vented.
6. E-stop switches the EHT off (beam off) and freezes the scan; the chamber stays pumped.

## What to watch

- `vacuum_status` not reaching ready within the pump time: door seal or a wet sample.
- `beam_on` false after `set_beam`: EHT run-up on a field-emission Gemini column takes longer; the
  twin models ~20 s.
- Every parameter and command name is a placeholder until the lab checks it against the SmartSEM
  Remote API reference (`references/smartsem_api.md`); a wrong name fails the call with a
  DeviceFault naming it.

## Resources

- `references/setup.md`: the Remote API licence and installation, pywin32, correcting the names,
  the first hardware test. Windows only.
- `references/smartsem_api.md`: the COM members, parameters and commands this package uses, their
  assumed units, the sources and the full list of what is unverified.
- `config.example.json`: image folder; the COM ProgID and the parameter and command names as an
  advanced block.
