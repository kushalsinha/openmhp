---
mhp: "2026-09-12"
id: empower-hplc-01
class: hplc
make: Waters
model: HPLC/UPLC system under Empower 3
location: ""
tags: [hplc, uplc, chromatography, analysis, empower]
description: An HPLC or UPLC chromatographic system controlled by Waters Empower 3, reached through the Empower Web API. Pick it to inject a list of samples (vial positions, injection volumes, an Empower instrument method per sample) and run them on the configured node and system, and to follow the system status until the sample set finishes. Not for writing instrument methods from scratch, and processing and results stay in Empower unless an export folder is configured.
driver: driver.py:EmpowerHPLC
sim: sim.py:SimEmpowerHPLC
---

# Waters Empower HPLC

Empower owns the instrument, the methods, the audit trail and the results. This package logs
into the Empower Web API as an Empower user and does what that user could do in Run Samples:
build a sample set method from a list of samples, run it on one node and chromatographic system,
and watch its status. Every change lands in Empower's audit trail with the comment given.

## Operating procedure

1. Read `connected` and `system_status`. The system must be idle (not acquiring) before a new
   sample set; Empower itself refuses to start on a system that is running.
2. Find the method: `mhp_method op='find'` for the project. A saved method here is the Empower
   instrument method (method set) name plus run mode, plate type and injection volume.
3. Invoke `run_samples` with the sample list. The package writes a sample set method named
   after the job, starts it, and polls the system until it is idle again.
4. Read the job result: sample set name, lines run, final status, and any exported result files.
5. To stop a running sample set, a person uses Empower's Run Samples window; the Web API calls
   used here have no abort.

## What to watch

- `system_status` reporting an error or "Not ready" (pump pressure, lamp, sample manager) needs a
  person at Empower.
- Injection volumes must suit the loop and the sample manager; the limits here are generic.
- Results (peak areas, amounts) are produced by Empower processing; with run mode RunAndProcess
  and an export method writing to `export_dir`, the job result includes the exported rows.

## Resources

- `references/setup.md`: Web API, user and password (keyring), config.json, first test.
- `references/web_api.md`: the Empower Web API calls this package makes.
- `config.example.json`: server address, project, node, system, plate types.
