# Setting up

The vendor route is Windows-only: Compass for iCE runs on the Windows PC attached to the Maurice,
and that PC (or a share of two of its folders) is what this package talks to. The package itself
is pure Python and can be served from that PC or from any machine that can write to the two
folders; the simulated twin runs anywhere.

Needed on the instrument PC:

- Compass for iCE (the version installed with the Maurice; 21 CFR Part 11 options are not
  needed). No vendor library, licence or API option exists for this route.
- Two folders, for example `C:\OpenMHP\maurice\batches` and `C:\OpenMHP\maurice\results`,
  writable by the account that serves the package.
- Something that turns a batch file into a run and an export:
  1. A person: opens `batches\mhp_<job>.csv`, builds the batch in Compass with those samples,
     positions, method and injection count (or imports the table if their Compass version offers
     a sample-table import: see `references/file_formats.md`), starts the run, and when it is
     analysed exports the peak table as CSV into the results folder.
  2. A helper script written by the lab that does the same by driving Compass's user interface.
     Nothing in this package depends on how it is done, only on the files.

Steps:

1. `pip install openmhp` on the serving machine.
2. Copy `config.example.json` to `config.json`: `import_dir`, `results_dir`, the Compass
   version for the record, `allowed_methods` (Compass method names an agent may queue; empty
   allows any) and the timeouts (`result_wait_s` 7200 s covers a CE-SDS batch with replicates and
   a slow import).
3. `mhp serve pkg:<this folder> --http <port>` and read `connected`.

## First hardware test

1. Read `connected` and `queue_depth` (0; delete stale `mhp_*.csv` batch files otherwise).
2. Put a system-suitability sample (the cIEF standard that ships with the kit) in A1 and fit the
   cIEF cartridge.
3. Invoke `queue_run` with the first example (position A1, your cIEF method name, 2 replicates)
   and confirm it. Watch `batches\` for `mhp_<job>.csv`.
4. Build and run the batch in Compass from that file. When the run is analysed, export the peak
   table as CSV into `results\`. The job should finish within seconds of the file appearing and
   report `peaks` with pI positions and `main_peak_pct`.
5. If the job fails with "peak table columns not recognised", open the CSV and compare its header
   with `references/file_formats.md`; the parser accepts several spellings but Compass's real ones
   must be confirmed on the first export.

## Status

Driver written from the Maurice user manual and Bio-Techne application notes; the sample-table
import and the peak-table export columns could not be verified against the Compass for iCE user
guide (not reachable while writing). Not yet run against the instrument. Status: twin tested.
