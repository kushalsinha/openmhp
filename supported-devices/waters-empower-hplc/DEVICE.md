---
mhp: "2026-09-12"
id: empower-hplc-01
class: chromatograph
make: Waters
model: HPLC/UPLC system under Empower 3
location: ""
tags: [hplc, uplc, chromatography, analysis, empower]
description: An HPLC or UPLC chromatographic system controlled by Waters Empower 3, reached through the Empower Web API or the Empower Toolkit. Pick it to inject a list of samples (vial positions, injection volumes, an Empower instrument method per sample) and run them on the configured node and system, and to follow the system status until the sample set finishes. Not for writing instrument methods from scratch, and processing and results stay in Empower unless an export folder is configured.
driver: driver.py:EmpowerHPLC
sim: sim.py:SimEmpowerHPLC
---

# Waters Empower HPLC

Empower owns the instrument, the methods, the audit trail and the results. This package logs
into Empower as an Empower user and does what that user could do in Run Samples: build a sample
set method from a list of samples, run it on one node and chromatographic system, and watch its
status. Every change lands in Empower's audit trail with the comment given.

It reaches Empower one of two ways, reported by the `backend` signal: the Empower Web API over HTTPS
from any machine, or the Empower Toolkit (Waters' COM SDK) on an Empower client PC. Left on `auto`,
the package uses the Toolkit when the PC it runs on has it and the Web API otherwise, so the lab
installs whichever is easier and the agent sees the same device. The Toolkit route can also stop a
running sample set and read results back; the signal says which route is live and why.

## Operating procedure

1. Read `connected` and `system_status`. The system must be idle (not acquiring) before a new
   sample set; Empower itself refuses to start on a system that is running.
2. Find the method: `mhp_method op='find'` for the project. A saved method here is the Empower
   instrument method (method set) name plus run mode, plate type and injection volume.
3. Invoke `run_samples` with the sample list. The package writes a sample set method named
   after the job, starts it, and polls the system until it is idle again.
4. Read the job result: sample set name, lines run, final status, and any exported result files.
5. To stop a running sample set: on the Toolkit route, cancel the job (`jobs/cancel`); Empower
   aborts the sample set and the job ends cancelled once the system is idle. On the Web API route
   there is no abort: a person stops it in Empower's Run Samples window, and a cancel fails the job
   saying so.

## What to watch

- `system_status` reporting an error or "Not ready" (pump pressure, lamp, sample manager) needs a
  person at Empower.
- `robot_access_ready` is true while no sample set from here is running, so a handling system may
  load or unload autosampler trays then; it does not see runs started from Empower itself.
- Injection volumes must suit the loop and the sample manager; the limits here are generic.
- Results (peak areas, amounts) are produced by Empower processing with run mode RunAndProcess
  or RunAndReport. The Toolkit route fetches them into the job result (`results_from: "toolkit"`);
  the Web API route needs an export method writing to `export_dir` (`results_from: "export_dir"`).

## Resources

- `references/setup.md`: choosing the route, user and password (keyring), config.json, first test.
- `references/web_api.md`: the Empower Web API calls the `web_api` backend makes.
- `references/toolkit.md`: the Toolkit objects the `toolkit` backend uses, and what to check first.
- `config.example.json`: backend, server address or database, project, node, system, plate types.
