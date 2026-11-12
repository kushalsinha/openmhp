---
mhp: "2026-09-12"
id: bruker-d8-pxrd-01
class: diffractometer
make: Bruker AXS
model: D8 Advance / D8 Discover under DIFFRAC.SUITE
location: ""
tags: [pxrd, xrd, diffractometer, bruker, diffrac, polymorph, form-screen]
description: A Bruker D8 Advance or D8 Discover powder X-ray diffractometer with a sample changer, run by DIFFRAC.SUITE (DIFFRAC.MEASUREMENT CENTER) on its Windows PC. Pick it to queue a powder pattern of a sample already in a changer position with a project's scan program (2theta range, step, time per step, optional .bsml method), and to get back the .brml raw file and .xy export with the number of points and range. Not for single-crystal work, stage scans, non-ambient chambers or evaluating phases (that is DIFFRAC.EVA), and it cannot see the changer's own state.
driver: driver.py:BrukerD8
sim: sim.py:SimBrukerD8
---

# Bruker D8 PXRD under DIFFRAC.SUITE

DIFFRAC.SUITE owns the diffractometer: the measurement centre's job controller runs a queue of
measurement jobs, moves the sample changer, opens the shutter and writes a `.brml` raw file per
scan. This package adds a job to that queue by writing a job file into the folder the lab has
set up as the job import, waits for the result file, and parses the pattern out of the `.brml`
(and the `.xy` text export where the lab's post-processing writes one). Each queued scan is
confirm-gated; the measurement centre must be running with its job import enabled.

## Operating procedure

1. Read `connected` and `queue_depth`. Ask the person at the instrument whether the measurement
   centre is running, the X-rays are on and the job import is enabled; the package cannot tell.
2. Put the sample holder at a free changer position (the person or a handling robot, while the
   changer is idle) and note the position.
3. Find the project's scan program: `methods/find {compound, project}`. Invoke `queue_scan`
   with `method: {name, project}` and `params: {sample_id, position}`; `approved: true` after a
   person confirmed. The job file carries the range, step and time per step of the method.
4. Poll the job. Progress stays near 0.05 until the job was imported, then rises with the
   expected scan time (points times time per step, plus the changer cycle).
5. Read the result: `file` (the `.brml`), `xy_file`, `points` and `two_theta_range`. Evaluate
   the pattern in DIFFRAC.EVA or from the `.xy` (two columns, 2theta and counts).
6. To stop: cancel the job before it was imported (the file is removed); afterwards a person
   stops the scan in DIFFRAC.MEASUREMENT CENTER.

## What to watch

- The job file is this package's own XML (sample id, position, method file, scan). DIFFRAC.SUITE's
  job import format is not published: the lab's DIFFRAC.SUITE administrator maps it to a job
  template, a DIFFRAC.COMMANDER script or the LIMS connection the installed version offers (see
  `references/diffrac_files.md`). Until that mapping is done and checked, nothing queued here runs.
- The `.brml` reader takes the first `RawData*.xml` of the zip and reads 2theta and counts from
  each `Datum`; files with several data routes or non-coupled scans may need the `.xy` export.
- A scan whose point count or duration exceeds `max_points` / `max_scan_hours` is refused before
  anything is written. The 2theta limits here (2 to 70 deg) are generic; the lab sets its own.

## Resources

- `references/setup.md`: DIFFRAC.SUITE, the folders, the Windows PC and the first test.
- `references/diffrac_files.md`: the job file, the `.brml` and `.xy` formats, sources and unverified fields.
- `config.example.json`: job, results and export folders, changer size, scan bounds.
