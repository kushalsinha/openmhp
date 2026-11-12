---
mhp: "2026-09-12"
id: kla-dektak-profilometer-01
class: profilometer
class_ref: CHMO:0001994
make: Bruker
model: Dektak XT / XT-A under Vision64 (KLA Alpha-Step D-500/D-600 by the same shape)
location: ""
tags: [profilometer, stylus, step-height, dektak, vision64, thin-film, template]
description: A template for a Bruker Dektak XT or XT-A stylus profilometer run by Vision64 on its Windows PC (and, by the same shape, a KLA Alpha-Step D-500/D-600), driven through a command channel to Vision64 that Bruker offers as a "TCP/IP Runtime Control Server" option for its profilers but does not document publicly, so every command here is unverified. Pick it to run one stylus scan of a typed length, force and speed with a saved Vision64 recipe, and to get back the .OPDx dataset Vision64 auto-saved and the step height its analysis recipe logged to the database CSV. Not for 3D maps, stitching or stage automation; the sample is placed and the stylus positioned over it by a person.
driver: driver.py:DektakVision
sim: sim.py:SimDektakVision
---

# Bruker Dektak XT under Vision64 (template)

Vision64 owns the profiler: it holds the measurement recipe (scan length, duration, stylus
force, range, profile type), lowers the tower, scans, raises the tower, auto-saves the dataset as
`.OPDx` and runs the analysis recipe whose results it appends to a database CSV. Bruker documents
in-GUI automation (multi-site recipes on the motorised stage) and, for its profilers, an optional
"TCP/IP Runtime Control Server" with a command set that is not public, so this package is a
**template**: `VisionBackend` holds every command against the shape such a channel must have,
each command string is configurable in `config.json` and marked unverified, and the twin runs
the same driver against a fake server.

## Operating procedure

1. Read `connected` and `status`. A person places the sample on the stage, positions the stylus
   over the start point with the live video and Vision64's stage controls, and steps clear.
2. Find the project's recipe record: `methods/find {compound, project}`; invoke `scan` with
   `method: {name, project}` and `params: {sample_id}`; `approved: true` after a person confirmed.
   The package loads the Vision64 recipe, sets length, duration (from speed), force, range and
   profile, sets the auto-save file name, and runs the scan.
3. Poll the job; `status` reads `scanning` while the tower is down. Scans take seconds.
4. Read the result: `file` (the `.OPDx`), `step_height_nm` (from the database CSV row Vision64
   logged for this scan), `db_file`.
5. `tower_up` raises the stylus at any time; `safety/estop` aborts a scan and raises the tower.
   The instrument's own EMO box cuts power and must be reset by a person.

## What to watch

- Nothing here runs until the command strings in `config.json` `commands` are corrected from
  Bruker's command set documentation and the database CSV columns match the lab's analysis recipe
  (`references/vision64_files.md`).
- A stylus crash (tower down with nothing under it, a sample taller than the clearance, moving
  the stage with the stylus down) breaks a stylus; `scan` is confirm-gated for that reason and
  the package never moves the stage.
- `force_mg` is bounded 1 to 15 mg (the standard LIS 3 sensor; 0.03 mg with the N-Lite+ option),
  `length_um` 50 to 55000, speed so that the duration stays within `max_duration_s`.

## Resources

- `references/setup.md`: Vision64, the control server option, the Windows PC and the first test.
- `references/vision64_files.md`: what Bruker documents, the assumed commands, the .OPDx header and database CSV, unverified items.
- `config.example.json`: host and port, data folder, database CSV, command strings, column names.
