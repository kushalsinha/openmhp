---
mhp: "2026-09-12"
id: bruker-nmr-iconnmr-01
class: nmr
make: Bruker
model: Avance NEO / III HD under TopSpin with ICON-NMR
location: ""
tags: [nmr, bruker, topspin, iconnmr, 1h, 13c, structure]
description: A Bruker Avance NMR spectrometer with a sample changer, run by TopSpin and ICON-NMR automation. Pick it to queue a standard experiment (PROTON, C13CPD, HSQC, COSY...) on a tube already in a changer holder, in a given solvent, with the number of scans and relaxation delay a project uses, and to get back the dataset path and acquisition parameters once ICON-NMR has acquired and processed it. Not for interactive shimming, pulse calibration or non-standard pulse programs, and it cannot see the changer's own state.
driver: driver.py:BrukerIconNMR
sim: sim.py:SimBrukerIconNMR
---

# Bruker NMR under ICON-NMR

ICON-NMR owns the spectrometer: it reads a queue of jobs, drives the sample changer, locks,
shims, acquires, processes and files the dataset under the TopSpin data directory. This package
only adds a job to that queue by writing a job file into the folder ICON-NMR's automation import
watches, and waits for the dataset folder to be complete. A person has confirmed each queued
experiment (the action is confirm-gated) and ICON-NMR's run must be started and left running by
the person at the spectrometer.

## Operating procedure

1. Read `connected` and `queue_depth`. Ask the person at the spectrometer whether ICON-NMR's
   automation run is started and the import is enabled; the package cannot tell.
2. Put the sample in a free holder (the person or a handling robot, while the changer is idle)
   and note the holder number.
3. Find the project's method: `methods/find {compound, project}` gives the experiment, solvent,
   `ns` and `d1_s`. Invoke `queue_experiment` with `method: {name, project}` and
   `params: {holder, title}` (and `dataset`/`expno` if the project files datasets by name).
   The call needs `approved: true` after a person confirmed it.
4. Poll the job. Progress stays near 0.05 until ICON-NMR has read the job file, then rises with
   the estimated acquisition time (lock and shim about 3 minutes, then `ns` scans).
5. Read the result: `dataset`, `expno`, the files written, and the `acqus` subset (NS, SW, O1,
   TD). The processed spectrum is `<dataset>/<expno>/pdata/1/1r` under the data directory;
   open it in TopSpin or any Bruker-format reader (nmrglue reads the folder).
6. To stop: cancel the job before ICON-NMR reads the file (the file is removed); afterwards a
   person stops the run in ICON-NMR or types `halt` in TopSpin.

## What to watch

- The job file's header words and the parameter columns are reconstructed from documentation,
  not from a Bruker file (`references/iconnmr_files.md`): the first job on a new system must
  be checked against what ICON-NMR actually imports before anything is queued unattended.
- `sample_changer_position` is the holder this package asked for, not a readback.
- Long experiments (C13CPD with 1024 scans is about an hour) are bounded by `result_wait_s`;
  a timeout fails the job with `retry_after` and leaves the job file in place to be seen.
- Solvent names must be TopSpin's (`CDCl3`, `DMSO`, `D2O`...); the lock fails on a wrong one.

## Resources

- `references/setup.md`: ICON-NMR configuration, folders, user and the first test.
- `references/iconnmr_files.md`: the job file, the dataset folder and `acqus`, with sources and unverified fields.
- `config.example.json`: import folder, data directory, ICON-NMR user, holders, allowed experiments.
