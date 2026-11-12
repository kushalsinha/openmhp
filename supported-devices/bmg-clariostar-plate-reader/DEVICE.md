---
mhp: "2026-09-12"
id: bmg-clariostar-plate-reader-01
class: microplate_reader
make: BMG LABTECH (also Molecular Devices, Tecan)
model: CLARIOstar / PHERAstar (SpectraMax via SoftMax Pro, Spark via SiLA 2)
location: ""
tags: [plate-reader, absorbance, fluorescence, luminescence, microplate, pharma-biologics]
description: Microplate reader driven through its vendor software's automation interface, selected in config - BMG CLARIOstar/PHERAstar/Omega through Reader Control's ActiveX, Molecular Devices SpectraMax through SoftMax Pro's Automation API, or Tecan Spark through its SiLA 2 server. Pick it to move the plate carrier, run a saved read protocol (absorbance, fluorescence, luminescence, kinetic) on a barcoded plate and get the exported well table back, with the incubator setpoint settable on incubating models. Not for writing protocols or for data analysis beyond the raw plate table.
driver: driver.py:PlateReader
sim: sim.py:SimPlateReader
---

# Plate reader (BMG / SoftMax Pro / Spark)

The vendor software owns the optics, the protocols and the primary data. This package is a client
of its automation interface: it moves the plate carrier, starts a named protocol with a plate ID,
waits for the reader to go idle, and reads the exported plate table. Which interface is used is a
one-word choice in config.json (`backend`); the signals and actions are the same on all three.

## Operating procedure

1. Read `connected`, `status` and `plate_in`. `status` must be idle before anything moves.
2. For a handling robot: `plate_out`, wait for `robot_access_ready` true, place the plate, then
   `plate_in` (it refuses unless the tray is out and nothing reads).
3. Find the protocol for the assay: `methods/find` with the compound or assay and project; a saved
   method is the protocol name as the vendor software lists it. Then
   `actions/invoke {name: read, method: {name, project}, params: {plate_id: ...}}`.
4. The job lasts the read; cancelling it aborts the read. The result carries the export file path
   and `wells` ({well: value}).
5. Incubating readers: write `temperature_setpoint` (25-45) and wait for `temperature` to settle
   before the first read; write null to switch the incubator off.

## What to watch

- `status` Error (BMG) or ERROR/OFFLINE (SoftMax Pro) needs a person at the vendor software.
- The export must be configured in the protocol (BMG ASCII export; SoftMax Pro auto-export or the
  ExportAs the driver sends); an empty `wells` with a warning means it was not.
- On a SpectraMax the drawer will not open while the incubator is on: set `temperature_setpoint`
  null first.
- The Spark SiLA 2 route has no temperature command and no verified door identifiers; see the
  reference before relying on it.

## Resources

- `references/setup.md`: per-route install (comtypes/32-bit Python, pythonnet and the SoftMax SDK,
  sila2), config.json, first hardware test.
- `references/automation.md`: the commands of each interface, their sources, and what is unverified.
- `methods/`: one example read method (`_shared/abs_600`); `methods/save` adds the lab's.
- `config.example.json`: backend choice, host, protocol and export folders.
