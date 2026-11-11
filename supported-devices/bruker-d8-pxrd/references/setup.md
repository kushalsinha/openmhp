# Setting up on the DIFFRAC.SUITE PC (Windows only)

DIFFRAC.SUITE (DIFFRAC.MEASUREMENT CENTER, DIFFRAC.COMMANDER, Result Manager) runs only on the
instrument's Windows PC, and the job import and result folders are local to it, so this package
is served from that PC: `pip install openmhp` in a Python 3.11 environment there. No vendor
library is needed; the package only writes and reads files.

1. With the DIFFRAC.SUITE administrator, set up the way jobs enter the measurement centre:
   a job template in the JOBLIST / START JOBS plug-ins, a DIFFRAC.COMMANDER script, or the LIMS
   connection ("automation interface") the installed version offers. Whatever it is, it must
   read the job files this package writes (`references/diffrac_files.md` gives the XML) from
   `job_dir`, remove each file once imported, and write the result as
   `<ResultFile>` into `results_dir`. This mapping is site work; the package cannot do it.
2. Optionally, have the Result Manager (or the script) export each result as a two-column `.xy`
   text file with the same base name into `xy_dir`.
3. Copy `config.example.json` to `config.json`: `job_dir`, `results_dir`, `xy_dir`; set
   `changer_positions` (9 on the standard changer) and the scan bounds `max_points` and
   `max_scan_hours` to what the lab allows an agent.
4. `mhp serve pkg:<this folder> --http <port>`; read `connected` and `queue_depth`.
5. Save the project's scan programs once (`methods/save`): range, step, time per step and the
   `.bsml` method they are based on. The example under `methods/demo-assay/` is a 3-40 deg
   form screen at 0.02 deg and 0.5 s.

## First hardware test

1. Queue one scan (`approved: true`) with the X-rays off or the import disabled, open the job
   file in `job_dir`, and have the administrator confirm the import maps every field (sample id,
   position, method file, start, stop, increment, time per step, result file name).
2. Cancel the job (the file is removed), or enable the import and let the measurement centre
   take it with a corundum or silicon standard in the named position.
3. Watch the job's progress rise once the file disappears; when `<sample_id>_<token>.brml`
   appears, compare `points` and `two_theta_range` with the scan in DIFFRAC.EVA.
4. Check the `.xy` export (if configured) opens in DIFFRAC.EVA with the same pattern.
5. Then a real sample with the project's method.

## Status

Twin tested. Written from the DIFFRAC.SUITE product documentation and the open-source `.brml`
readers listed in `references/diffrac_files.md`; not yet run against a diffractometer. The job
import mapping (step 1) is site-specific and unverified; the `.brml` reader follows GSAS-II.
