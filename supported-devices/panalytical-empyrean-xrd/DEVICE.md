---
mhp: "2026-09-12"
id: panalytical-empyrean-xrd-01
class: diffractometer
make: Malvern Panalytical
model: Empyrean / Aeris under Data Collector
location: ""
tags: [xrd, pxrd, diffractometer, panalytical, empyrean, aeris, xrdml, powder]
description: A Malvern Panalytical Empyrean or Aeris X-ray diffractometer run by Data Collector (or the Aeris Instrument Suite) on its Windows PC, with a sample changer where one is fitted. Pick it to queue a Gonio 2theta scan (range, step, time per step) of a sample at a changer position with a project's saved scan program, and to get back the .xrdml result with the number of points, the 2theta range, the counting time and the measurement status. Not for reciprocal-space maps, stress, texture or non-ambient work, not for phase analysis (that is HighScore), and it cannot see the changer's own state.
driver: driver.py:PanalyticalXrd
sim: sim.py:SimPanalyticalXrd
---

# Malvern Panalytical Empyrean / Aeris under Data Collector

Data Collector owns the diffractometer: it runs measurement programs (`.xrdmp`) and batches,
moves the sample changer, opens the shutter and writes one `.xrdml` XML file per measurement.
This package queues one scan per request by writing a job file into the folder the lab's import
(Operator Interface job list, a batch built by a script, or the Universal Automation Interface
client) reads, waits for the `.xrdml` result, and parses the scan out of it. Each queued scan is
confirm-gated; Data Collector must be running with the X-rays on and the import enabled.

## Operating procedure

1. Read `connected` and `queue_depth`. Ask the person at the instrument whether Data Collector is
   running, the tube is at its operating kV/mA and the job import is enabled; the package cannot tell.
2. Put the holder at a free changer position (the person or a handling robot, while the changer
   is idle) and note the position; `position: null` measures the holder already on the stage.
3. Find the project's scan program: `methods/find {compound, project}`. Invoke `queue_scan` with
   `method: {name, project}` and `params: {sample_id, position}`; `approved: true` after a person
   confirmed. The job file carries the axis, range, step and time per step of the method and the
   optional `.xrdmp` program it is based on.
4. Poll the job. Progress stays near 0.05 until the job file was taken, then rises with the
   expected scan time (points times time per step, plus the changer cycle).
5. Read the result: `file` (the `.xrdml`), `points`, `two_theta_range`, `counting_time_s`,
   `status` (`Completed`, `Aborted` or `Not finished` as Data Collector wrote it). Open the
   file in HighScore or any XRDML reader for phase analysis.
6. To stop: cancel the job before it was taken (the file is removed); afterwards a person stops
   the measurement in Data Collector.

## What to watch

- The job file is this package's own XML (sample id, position, program file, scan). Data
  Collector publishes the `.xrdmp` program schema but no job or batch import format: the lab's
  administrator maps the job file to an Operator Interface job, a batch, or the Universal
  Automation Interface (see `references/xrdml_files.md`). Until that mapping is done and
  checked, nothing queued here runs.
- The `.xrdml` reader takes the namespace from the root tag (schema 1.0 to 2.x), the first
  `scan` of the first `xrdMeasurement`, `positions axis="2Theta"` start/end (or a position list),
  and `intensities` (schema 1.x) or `counts` (2.x); multi-scan files report the first scan only.
- A scan whose point count or duration exceeds `max_points` / `max_scan_hours` is refused before
  anything is written. The 2theta limits here (2 to 142 deg) are the Aeris range; an Empyrean
  reaches 168 deg and the lab sets its own.

## Resources

- `references/setup.md`: Data Collector, the folders, the Windows PC and the first test.
- `references/xrdml_files.md`: the job file, the `.xrdml` schema and the `.xrdmp` program, sources and unverified fields.
- `config.example.json`: job and results folders, changer size, scan bounds.
