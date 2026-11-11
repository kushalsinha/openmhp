# Setting up

QuantStudio Design & Analysis Software 2 runs on the Windows PC connected to the instrument (or on
the instrument's touchscreen computer); the two folders this package uses live there or on a share
of it. The package itself is pure Python and can be served from any machine that can write to the
folders; the simulated twin runs anywhere.

Needed:

- QuantStudio Design & Analysis Software 2 (v2.8 was read for this package) with the run templates
  (`.edt`) the lab uses saved in its library, and an export setting that includes the Results table
  (Actions > Export > Export Settings; the default includes it). No licence or option is needed.
  With security (SAE) enabled, the user importing and exporting needs the Edit Export Destination
  permission.
- Two folders, for example `\\QS5-PC\OpenMHP\plates` and `\\QS5-PC\OpenMHP\results`, writable by
  the account that serves the package.
- Someone to start the run. On a QuantStudio 5 the run is started at the touchscreen (Thermo
  Fisher's FAQ: a run set up in the cloud application is opened on the instrument with "Open
  Template" and started there); on a QuantStudio 7 Pro the connected software starts it. A helper
  that drives the software's user interface may do the same; nothing here depends on how.

Steps:

1. `pip install openmhp` on the serving machine.
2. Copy `config.example.json` to `config.json`: `import_dir`, `results_dir`, `wells` (96 or 384),
   `reporter` and `quencher` as the plate setup file must carry them (FAM / NFQ-MGB for TaqMan,
   SYBR / None for SYBR), `allowed_templates`, and the timeouts (`result_wait_s` 14400 s covers a
   long run and a slow export).
3. `mhp serve pkg:<this folder> --http <port>` and read `connected`.

## First hardware test

1. Read `connected` and `queue_depth` (0; delete stale `mhp_*` files from the plate folder otherwise).
2. Seal a plate with three wells (calibrator, a sample, an NTC) for one TaqMan assay.
3. Invoke `queue_run` with the first example, naming the template the lab uses for that assay, and
   confirm it. Watch the plate folder for `mhp_<job>_plate_setup.txt` and `mhp_<job>.json`.
4. In the software: open the template, Plate Setup tab, More Options > Import Plate Setup, pick
   the TXT file, check Reporter and Quencher, save the plate file to the instrument and start the
   run at the touchscreen.
5. When the run is analysed: Actions > Export, CSV, named `mhp_<job>_Results.csv`, into the results
   folder. The job should finish within a minute and report three `results` rows with `ct` values
   (null for the NTC) and `amp_status`. If it fails with "results columns not recognised", compare
   the export's header with `references/file_formats.md` and adjust the export setting.

## Status

Driver written from the QuantStudio Design & Analysis Software 2 User Guide (MAN0018200 Rev. M) and
Thermo Fisher's QuantStudio 5 FAQ; the exact plate setup column headers and the Results export
column names are marked unverified in `references/file_formats.md`. Not yet run against the
instrument. Status: twin tested.
