---
mhp: "2026-09-12"
id: rigaku-smartlab-xrd-01
class: diffractometer
make: Rigaku
model: SmartLab / SmartLab SE / MiniFlex under SmartLab Studio II
location: ""
tags: [xrd, pxrd, diffractometer, rigaku, smartlab, miniflex, thin-film, powder]
description: A Rigaku SmartLab, SmartLab SE or MiniFlex X-ray diffractometer run by SmartLab Studio II on its Windows PC, with an ASC sample changer where one is fitted. Pick it to queue a 2theta scan (range, step, speed in deg/min) of a sample at a changer position with a project's saved scan recipe, and to get back the .ras or .rasx result with the number of points, the 2theta range and the tube conditions read from its header. Not for rocking curves, reciprocal-space maps, in-plane or non-ambient work, not for phase analysis (that is Studio II's Powder XRD plugin), and it cannot see the changer's own state.
driver: driver.py:RigakuSmartLab
sim: sim.py:SimRigakuSmartLab
---

# Rigaku SmartLab / MiniFlex under SmartLab Studio II

SmartLab Studio II owns the diffractometer: it aligns the optics, moves the ASC changer, opens the
shutter, runs the "General Measurement" part of a package and writes a `.ras` (text) or `.rasx`
(zip) file per scan. This package queues one scan per request by writing a job file into the
folder the lab's Studio II flow (or its Rigaku Automation Interface client) reads, waits for the
result file, and parses the pattern and the header out of it. Each queued scan is confirm-gated;
Studio II must be running with the X-rays on and the import flow enabled.

## Operating procedure

1. Read `connected` and `queue_depth`. Ask the person at the instrument whether Studio II is
   running, the X-rays are on and the job import flow is enabled; the package cannot tell.
2. Put the holder at a free changer position (the person or a handling robot, while the changer
   is idle) and note the position; `position: null` measures the holder already on the stage.
3. Find the project's scan recipe: `methods/find {compound, project}`. Invoke `queue_scan` with
   `method: {name, project}` and `params: {sample_id, position}`; `approved: true` after a person
   confirmed. The job file carries the range, step, speed and scan mode of the method.
4. Poll the job. Progress stays near 0.05 until the job file was taken, then rises with the
   expected scan time ((end - start) / speed, plus the changer cycle).
5. Read the result: `file` (the `.rasx` or `.ras`), `points`, `two_theta_range`, `target`,
   `voltage_kv`, `current_ma`, `scan_speed_deg_min`. Open the file in Studio II or any reader of
   the three-column Rigaku format for phase analysis.
6. To stop: cancel the job before it was taken (the file is removed); afterwards a person stops
   the measurement in Studio II.

## What to watch

- The job file is this package's own CSV (one header row, one scan row). Studio II publishes no
  import format: the lab's Studio II administrator maps it to a flow template, a Package Part run
  per changer position, or the Rigaku Automation Interface (see `references/rigaku_files.md`).
  Until that mapping is done and checked, nothing queued here runs.
- The `.ras` reader takes the first `*RAS_HEADER_START` block and the rows of the first
  `*RAS_INT_START` block (angle, intensity, attenuator factor); a multi-scan file reports the
  first scan only. The `.rasx` reader takes `Data0/Profile0.txt` and `Data0/MesurementConditions0.xml`.
- A scan whose point count or duration exceeds `max_points` / `max_scan_hours` is refused before
  anything is written. The 2theta limits here (2 to 145 deg) are the MiniFlex range; a SmartLab
  reaches further and the lab sets its own.

## Resources

- `references/setup.md`: Studio II, the folders, the Windows PC and the first test.
- `references/rigaku_files.md`: the job file, the `.ras` and `.rasx` formats, sources and unverified fields.
- `config.example.json`: job and results folders, changer size, scan bounds.
