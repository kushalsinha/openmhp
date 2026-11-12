---
mhp: "2026-09-12"
id: ta-dsc-tga-01
class: thermal_analyzer
make: TA Instruments
model: Discovery / Q-series DSC and TGA under TRIOS
location: ""
tags: [dsc, tga, thermal-analysis, trios, melting-point, polymorph, decomposition]
description: A TA Instruments Discovery (or Q-series) DSC and/or TGA run by TRIOS on its Windows PC, with the pan robot. Pick it to queue a temperature program (ramps and isotherms) on a weighed pan in a rack position, with a project's program per material, and to get back the TRIOS text export with the number of points and a simple estimate of the onset and peak (DSC) or the mass loss (TGA). Not for modulated DSC analysis, TRIOS' own integration and reporting, or instruments without a TRIOS export, and it cannot see the pan robot's state. Mettler STARe is noted in the setup note, not supported.
driver: driver.py:TADscTga
sim: sim.py:SimTADscTga
---

# TA Instruments DSC / TGA under TRIOS

TRIOS owns the calorimeter and the thermobalance: it loads the pan from the rack, runs the
temperature program, records the curve and exports it. This package adds a run to the queue the
lab's TRIOS automation reads, by writing a run-list file, then waits for the exported text file
and parses it. Every queued run is confirm-gated; TRIOS must be running with the automation
(TRIOS Auto / autoloader run queue, or a person importing the run list) enabled.

## Operating procedure

1. Read `connected` and `queue_depth`. Ask the person at the instrument whether TRIOS is
   running, the purge gas is on and the run-list import is active; the package cannot tell.
2. Weigh the sample into a pan, crimp or leave open as the method says, place it in a free rack
   position (the person or a handling robot, while the pan robot is idle), and note the position
   and mass.
3. Find the material's program: `methods/find {compound, project}`. Invoke `queue_run` with
   `method: {name, project}` and `params: {sample_name, pan_position, mass_mg}`; `approved: true`
   after a person confirmed. The instrument (dsc or tga) is part of the method.
4. Poll the job. Progress stays near 0.05 until TRIOS read the run list, then rises with the
   program's duration plus loading and equilibration; `sample_temperature` follows the live
   export when one is configured.
5. Read the result: `file` (the export), `points`, `onset_c`, `peak_c`, `mass_loss_pct`. These
   are estimates from the curve (`references/trios_files.md`); for a reportable value, analyse
   the run in TRIOS.
6. To stop: cancel before TRIOS read the file (it is removed); afterwards a person stops the
   run in TRIOS.

## What to watch

- The run-list columns and the segment text are this package's own, reconstructed from how
  TRIOS shows procedures; TA publishes no run-list import format. The lab's TRIOS administrator
  maps the file to the automation the installed version offers before anything runs unattended.
- The export parser expects TRIOS' text export (header lines, `[step]`, column names, units,
  tab-separated rows) with a Temperature column and a Heat Flow (DSC) or Weight (TGA) column.
- The DSC temperature limit here is 600 degC and the TGA limit 1000 degC; the lab's own limits
  go in `max_temperature_c` and `max_run_hours` of config.json.

## Resources

- `references/setup.md`: TRIOS, the folders, the Windows PC, the first test, Mettler STARe notes.
- `references/trios_files.md`: the run list, the export format, the onset/peak estimate, sources and unverified fields.
- `config.example.json`: run-list and export folders, live export file, limits.
