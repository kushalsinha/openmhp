# Setting up

The package only needs the two Sample Scheduler folders, so it runs from any Linux, macOS or Windows
machine that mounts them. OpenLab CDS and Sample Scheduler themselves are Windows.

## What you need

- OpenLab CDS 2.x with **Sample Scheduler for OpenLab** installed and connected to the CDS (it is a
  separate Agilent product; the plain CDS has a manual sequence import but no watched folder).
- In Sample Scheduler Configuration > LIMS: the XML command mode with a **Command folder** (default
  `C:\LIMS_Commands`; a UNC path is allowed) and a processed-command folder. If the SQL mode is
  configured for that connection, XML files are ignored.
- A project report (csv or txt) and **Review for LIMS** configured to copy it to the **Result folder**
  (for example `C:\LIMS_Results`), so results come back as files.
- Both folders shared to the machine serving this package, writable (command) and readable (result)
  by the account that runs `mhp`.

## Install

1. `pip install openmhp`
2. Copy `config.example.json` to `config.json`: `command_dir`, `result_dir`, `project`, `instrument` exactly
   as Sample Scheduler shows them, the sampler's injection volume range and, if you want to restrict the
   agent, `allowed_methods`. `injection_source` is the sampler as the scheduler names it.
3. Optional `methods_dir`: a share of the project's method folder, so `list_methods` can list files.
4. `mhp serve pkg:<this folder> --http <port>` and read `connected`.

## First hardware test

1. Read `connected` and `instrument_status`.
2. Invoke `run_samples` with one blank injection (the example with one sample, 1 uL) and
   `expected_run_min` set; watch the command file appear in the command folder, then move to the processed
   folder (or to `trash`, in which case the job fails with the reason: fix the method or vial name).
3. In Sample Scheduler, watch the analysis go Submitted, In Progress, Ended.
4. When Review for LIMS has copied the report, read the job result and check the rows against the report.
5. Run a second sequence and stop it from Sample Scheduler; the job ends on `expected_run_min`.

## Status

twin tested. Written from Agilent's Sample Scheduler online help (see `references/sample_scheduler.md`);
the command file's element layout is unverified and not yet run against a Sample Scheduler.
