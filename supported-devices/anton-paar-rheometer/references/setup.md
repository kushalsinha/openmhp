# Setting up on the RheoCompass PC (Windows only)

RheoCompass runs on Windows 10/11 with a Microsoft SQL Server database (Anton Paar's system
requirements), and the job and export folders are local to it, so this package is served from
that PC: `pip install openmhp` in a Python 3.11 environment there. No vendor library is needed;
the package only writes and reads files.

1. With the RheoCompass administrator, set up the way jobs enter the rheometer. RheoCompass has
   no public automation interface; the choices are a Test Analysis Designer workflow whose
   actions read the job file and run the matching test definition with the sample name, an AP
   Connect task list (Anton Paar's lab execution server with a REST API; whether MCR rheometers
   are task-list instruments is for Anton Paar to confirm), or an operator routine. Whatever it
   is, it must read the job files this package writes (`references/rheocompass_files.md` gives
   the CSV) from `job_dir`, remove each file once taken, run the test, and export the result as
   `result_file` (ASCII) into `results_dir`. This mapping is site work; the package cannot do it.
2. Decide how the hood state reaches `hood_state_file`: a workflow step that writes `closed`
   before the test and `open` after, or a switch read by a small script. Without it the
   `hood_closed` interlock stays open and nothing queues.
3. Optionally have the workflow keep a live ASCII export of the running test in
   `live_export_file`; `temperature` reads its last Temperature value.
4. Copy `config.example.json` to `config.json`: `job_dir`, `results_dir`, `hood_state_file`,
   `live_export_file`; set `max_test_hours` to what the lab allows an agent.
5. `mhp serve pkg:<this folder> --http <port>`; read `connected`, `queue_depth`, `hood_closed`.
6. Save the project's test definitions once (`methods/save`): type, measuring system,
   temperature and the ramp or sweep. The example under `methods/demo-assay/` is a 0.1 to
   1000 1/s flow curve, 21 points of 10 s, CP50-1, 25 degC.
7. Set the `temperature_c` bounds in `descriptor.yaml` to the fitted temperature device and ship
   that as a package edit.

## First hardware test

1. Queue one test (`approved: true`) with the workflow disabled, open the job file in `job_dir`,
   and have the administrator confirm the mapping covers every column (sample name, test type,
   measuring system, temperature, ramp or sweep, export file name).
2. Cancel the job (the file is removed), or enable the workflow and let RheoCompass take it with
   the standard oil loaded.
3. Watch the job's progress rise once the file disappears; when `<sample_name>_<token>.txt`
   appears, compare `points`, `columns` and `summary.viscosity_pa_s` with the table in RheoCompass.
4. Open the export in a text editor and check the package's `columns` match its `Interval data:`
   line (the header wording of your RheoCompass version is unverified).
5. Then a real sample with the project's method.

## Status

Twin tested. The export reader is written from two open-source readers of real RheoCompass
exports (`references/rheocompass_files.md`) and the brochure facts for the MCR range; not yet
run against a rheometer. The job mapping (step 1), the hood file (step 2) and the exact export
header of the installed version are site-specific and unverified.
