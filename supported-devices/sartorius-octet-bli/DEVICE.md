---
mhp: "2026-09-12"
id: sartorius-octet-bli-01
class: biosensor
make: Sartorius (ForteBio)
model: Octet RH16 / RH96 (R8 unverified)
location: ""
tags: [bli, biosensor, kinetics, binding, quantitation, pharma-biologics]
description: Sartorius Octet RH16 or RH96 bio-layer interferometry system driven through the Octet automation interface of Octet BLI Discovery (TCP/IP socket command protocol). Pick it to run a saved kinetics or quantitation method on a barcoded sample plate with a named biosensor tray, follow the run to completion and learn where the experiment folder is, to present and close the stage for a handling robot, and to set the plate temperature. Not for writing methods or analysing data (Octet Analysis Studio), and not verified for the 8-channel R8.
driver: driver.py:OctetBLI
sim: sim.py:SimOctetBLI
---

# Octet BLI (automation interface)

Octet BLI Discovery owns the instrument, the methods and the data. Its automation interface is a
small line protocol over a socket: this package sends `Run` with a method file and barcodes, polls
`Status` until the run is over, and reads the experiment path from `GetRunInfo`. `Present` and
`Close` move the stage for a handling robot.

## Operating procedure

1. Read `connected` and `status`. `status` must be `OK` before anything starts.
2. For a handling robot: `plate_out` (Present), wait for `robot_access_ready`, place the sample plate
   and the sensor tray, then `plate_in` (Close).
3. Find the method for the assay: `methods/find` with the analyte and project; a saved method here is
   the .fmf file name. Then `actions/invoke {name: run_experiment, method: {name, project},
   params: {sample_plate_id, sensor_tray_id}}`.
4. The job lasts the run (25 minutes to a few hours); progress follows `Running (nn%)`. Cancelling
   sends Stop. The result names the experiment folder for Analysis Studio.
5. Write `temperature_setpoint` (whole degrees) before loading a plate and let it settle; the
   interface cannot read the temperature back, so watch the instrument screen the first time.

## What to watch

- `status` starting with `Error`: a person must look at Octet BLI Discovery.
- `LoadSensors` mid-run means the method needs another sensor tray; this package fails the job rather
  than wait, so run multi-tray methods with a person.
- `plate_in` is this package's own record of Present/Close; a run started from the Octet software
  itself is only visible through `status`.

## Resources

- `references/setup.md`: enabling the automation interface, port, method folder, first hardware test.
- `references/automation_api.md`: the command protocol, status words and sources, and what is unverified.
- `methods/`: one example method (`_shared/mab_kinetics_proa`); `methods/save` adds the lab's.
- `config.example.json`: host, port, method folder.
