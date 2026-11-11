---
mhp: "2026-09-12"
id: agilent-openlab-hplc-01
class: chromatograph
make: Agilent
model: 1260/1290 Infinity II under OpenLab CDS 2.x with Sample Scheduler
location: ""
tags: [hplc, uhplc, chromatography, analysis, openlab, sample-scheduler]
description: An Agilent 1260 or 1290 Infinity II HPLC under OpenLab CDS 2.x, reached through Sample Scheduler for OpenLab's file-based LIMS integration (a command file in a watched folder, results copied to a result folder). Pick it to inject a list of samples (positions, volumes, an acquisition method per sample) on the configured project and instrument and to wait for the report rows. Not for writing methods, not for stopping a run (a person does that in Sample Scheduler), and not for an OpenLab installation without Sample Scheduler.
driver: driver.py:Device
sim: sim.py:Sim
---

# Agilent OpenLab CDS HPLC (Sample Scheduler)

OpenLab CDS owns the instrument, the methods, the audit trail and the results. Sample Scheduler for OpenLab
accepts analyses from a LIMS as XML command files in a watched folder (default `C:\LIMS_Commands`) and,
with "Review for LIMS", copies the reports of finished analyses to a result folder. This package writes one
command file per sequence, watches what the scheduler does with it, and returns the report rows. No OpenLab
REST API is publicly documented, so none is used.

## Operating procedure

1. Read `connected` and `instrument_status`. `command` must not be `waiting` (a previous command the
   scheduler has not taken means Sample Scheduler is not running).
2. Find the method: `mhp_method op='find'` for the project. A saved method here is the acquisition and
   processing method names, injection volume and expected run time for a sample type.
3. Invoke `run_samples` with the sample list (`actions/invoke {name: run_samples, method: {...}}` or explicit
   `samples`). The package writes `<sequence_name>.xml`, waits for it to be taken, then for the report.
4. Read the job result: sequence name, the command's fate, the report files and their rows.
5. To stop a running analysis, a person uses Sample Scheduler (Stop / Stop instrument) or the OpenLab run queue.

## What to watch

- A command moved to `trash` means the scheduler rejected it: a method or vial name does not exist in the
  project, or the instrument name is wrong. The job fails with that reason.
- Without "Review for LIMS" copying reports to the result folder, no result ever appears: set
  `expected_run_min` so the job ends on time, and read results in OpenLab.
- `robot_access_ready` is true while no sequence from here is running, so a handling system may load or
  unload sampler trays then; sequences started from OpenLab itself are not seen.
- Injection volumes must suit the sampler's loop; the limits here are generic (0.1 to 100 uL).

## Resources

- `references/setup.md`: Sample Scheduler's LIMS folders, the share, Review for LIMS, config.json, first test.
- `references/sample_scheduler.md`: the command file parameters and the result folder, with sources and what is unverified.
- `config.example.json`: command and result folders, project, instrument.
- `methods/_shared/assay-c18.yaml`: an example method record.
