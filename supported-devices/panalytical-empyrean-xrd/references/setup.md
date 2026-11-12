# Setting up on the Data Collector PC (Windows only)

Data Collector (and the Aeris Instrument Suite on newer Aeris units) is a Windows-only
application (Windows 8.1/10 64-bit per the vendor's page, Windows 10/11 for 7.x), and the job
and result folders are local to it, so this package is served from that PC: `pip install
openmhp` in a Python 3.11 environment there. No vendor library is needed; the package only
writes and reads files.

1. With the Data Collector administrator, set up the way jobs enter the instrument: an
   Operator Interface job list (Empyrean/X'Pert option; jobs are prepared offline and the
   sample id can be carried in the XRDML file name), a batch built by a script from the job file,
   or the Universal Automation Interface (UAI, TCP/IP) client the lab's automation uses on an
   Aeris. Whatever it is, it must read the job files this package writes
   (`references/xrdml_files.md` gives the XML) from `job_dir`, remove each file once taken, run
   the named `.xrdmp` program (or its default) with the job's scan range, and save the result as
   `ResultFile` into `results_dir`. This mapping is site work; the package cannot do it.
2. Copy `config.example.json` to `config.json`: `job_dir`, `results_dir`, `programs_dir`; set
   `changer_positions` (6 or 67 on an Aeris) and the scan bounds `max_points` and
   `max_scan_hours` to what the lab allows an agent.
3. `mhp serve pkg:<this folder> --http <port>`; read `connected` and `queue_depth`.
4. Save the project's scan programs once (`methods/save`): axis, range, step, time per step and
   the `.xrdmp` they are based on. The example under `methods/demo-assay/` is a 5-60 deg Gonio
   scan at 0.026 deg and 0.5 s per step (about 18 min on a point detector; the package's duration
   check multiplies points by time per step, so for a scanning-detector program whose counting
   time per point is tens of seconds set `max_scan_hours` to match).
5. Raise the 2theta bounds in `descriptor.yaml` for an Empyrean (the shipped 2-142 deg is the
   Aeris range) and ship that as a package edit.

## First hardware test

1. Queue one scan (`approved: true`) with the shutter closed or the import disabled, open the
   job file in `job_dir`, and have the administrator confirm the import maps every field (sample
   id, position, program file, scan axis, mode, start, end, step, counting time, result file name).
2. Cancel the job (the file is removed), or enable the import and let Data Collector take it
   with the Si or LaB6 standard in the named position.
3. Watch the job's progress rise once the file disappears; when `<sample_id>_<token>.xrdml`
   appears, compare `points`, `two_theta_range` and `counting_time_s` with the scan in Data
   Collector, and check `status` reads `Completed`.
4. Open the same file in HighScore to confirm it is the scan the package reported.
5. Then a real sample with the project's method.

## Status

Twin tested. The `.xrdml` reader is written from the public XRDML schemas (1.0-2.1) and real
files from Empyrean, X'Pert and Aeris instruments listed in `references/xrdml_files.md`; not yet
run against a diffractometer. The job import mapping (step 1) is site-specific and unverified:
Data Collector publishes the `.xrdmp` program schema but no job or batch import format.
