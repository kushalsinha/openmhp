# Setting up on the TRIOS PC (Windows only)

TRIOS runs only on the instrument's Windows PC and the run-list and export folders are local
to it, so this package is served from that PC: `pip install openmhp` in a Python 3.11
environment there. No vendor library is needed; the package writes and reads files.

1. With the TRIOS administrator, set up how runs enter the queue: the TRIOS Auto / autoloader
   run queue import that the installed TRIOS version offers (the "run list" import of the
   Discovery autoloader), or a person importing the run list. It must read the run-list files
   this package writes from `run_dir` (`references/trios_files.md` gives the columns), remove
   each file once read, and run the procedure. TA publishes no run-list import format, so this
   mapping is site work and the first test below checks it.
2. Set TRIOS' end-of-run export to write a text export (Export > Text/LIMS, tab-separated,
   header lines then `[step]` blocks) named as the run list's "Export File" column into
   `export_dir`. Optionally a live re-export of the running curve to one file (`live_export_file`).
3. Copy `config.example.json` to `config.json`: `run_dir`, `export_dir`, `live_export_file`;
   set `pan_positions`, `max_temperature_c` per instrument and `max_run_hours` to what the lab
   allows an agent.
4. `mhp serve pkg:<this folder> --http <port>`; read `connected` and `queue_depth`.
5. Save the project's temperature programs once (`methods/save`): instrument and segments.
   The example under `methods/demo-assay/` is a 10 K/min DSC ramp to 300 degC.

## First hardware test

1. Queue one run (`approved: true`) with the import disabled, open the run list in `run_dir`,
   and have the administrator confirm every column maps (sample, instrument, pan position,
   mass, procedure segments, data file, export file).
2. Cancel the job (the file is removed), or enable the import and let TRIOS take it with an
   indium standard in the named position (DSC) or an empty pan (TGA).
3. Watch the progress rise once the file disappears; when `<token>.txt` appears in
   `export_dir`, compare `points` with the export's rows and `onset_c` / `peak_c` with TRIOS'
   own analysis of the indium melt (156.6 degC onset): they are estimates and will differ by
   a little; large differences mean the columns were not recognised.
4. Check `sample_temperature` follows the live export when one is configured.
5. Then a real sample with the project's program.

## Mettler STARe

A Mettler STARe workstation is not supported by this package: STARe has its own experiment
queue and exports text (`.txt`) through its own evaluation window with different header lines.
The same route (write a run file, wait for an export, parse it) applies; a STARe package would
reuse the driver's structure with STARe's run-file columns and a parser for its export, once
those are read from the STARe documentation.

## Status

Twin tested. Written from the TRIOS text export as third-party readers (hermes-rheo,
RheoJAX) document it and TA's TRIOS export notes; not yet run against a DSC or TGA. The
run-list import mapping (step 1) is site-specific and unverified.
