# Setting up on the SmartLab Studio II PC (Windows only)

SmartLab Studio II is a Windows-only suite (Windows 10/11 Pro 64-bit, Microsoft SQL Server
backend, CodeMeter licence dongle on the instrument PC), and the job and result folders are
local to it, so this package is served from that PC: `pip install openmhp` in a Python 3.11
environment there. No vendor library is needed; the package only writes and reads files.

1. With the Studio II administrator, set up the way jobs enter the instrument. Rigaku's
   supported route for external control is the Rigaku Automation Interface (RAI, part of
   LabLinc Studio: TCP/IP client-server with a Python API and a "CSV-based scripting" mode);
   without it, a flow template with the ASC measurement Package Part (General Measurement (BB))
   run per changer position by the operator. Whatever it is, it must read the job files this
   package writes (`references/rigaku_files.md` gives the CSV) from `job_dir`, remove each file
   once taken, and save the measurement as `result_file` into `results_dir` as `.rasx` (Studio
   II's native format) or `.ras`. This mapping is site work; the package cannot do it.
2. Copy `config.example.json` to `config.json`: `job_dir`, `results_dir`; set
   `changer_positions` (6, 8, 10 or 48 for the ASC fitted) and the scan bounds `max_points` and
   `max_scan_hours` to what the lab allows an agent.
3. `mhp serve pkg:<this folder> --http <port>`; read `connected` and `queue_depth`.
4. Save the project's scan recipes once (`methods/save`): range, step, speed and mode. The
   example under `methods/demo-assay/` is a 5-60 deg scan at 0.02 deg and 10 deg/min.
5. Raise the 2theta bounds in `descriptor.yaml` for a SmartLab (the shipped 2-145 deg is the
   MiniFlex range) and ship that as a package edit.

## First hardware test

1. Queue one scan (`approved: true`) with the X-rays off or the import flow disabled, open the
   job file in `job_dir`, and have the administrator confirm the import maps every column
   (sample id, position, axis, mode, start, stop, step, speed, result file name).
2. Cancel the job (the file is removed), or enable the import and let Studio II take it with the
   Si or LaB6 standard in the named position.
3. Watch the job's progress rise once the file disappears; when `<sample_id>_<token>.rasx`
   appears, compare `points`, `two_theta_range`, `voltage_kv` and `current_ma` with the scan in
   Studio II.
4. Save the same scan as `.ras` once and check the package reads it too (`format: ras`).
5. Then a real sample with the project's method.

## Status

Twin tested. The `.ras` and `.rasx` readers are written from public Studio II files and the
open-source readers listed in `references/rigaku_files.md`; not yet run against a diffractometer.
The job import mapping (step 1) is site-specific and unverified: Studio II publishes no job file
format and RAI's CSV scripting columns are not public.
