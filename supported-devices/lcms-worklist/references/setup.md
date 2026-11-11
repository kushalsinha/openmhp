# Setting up

The package writes files; it needs no vendor library and no instrument connection. It runs on
any Windows, Linux or macOS machine that can write into a folder the acquisition PC reads. The
simplest place is the acquisition PC itself (`pip install openmhp`), writing into a local folder.

1. Decide the vendor: `masslynx` (Waters MassLynx 4.x), `sciexos` (SCIEX OS), `masshunter`
   (Agilent MassHunter Acquisition LC/TQ or LC/Q-TOF 10.x-12.x) or `xcalibur` (Thermo Xcalibur
   2.2 or later). One package instance serves one vendor; copy the folder for a second system.
2. Create the output folder (for example `C:\MassLynx\Worklists\openmhp`) and make sure the
   account running `mhp` can write to it and the person importing can open it from the vendor
   software.
3. Copy `config.example.json` to `config.json`: `vendor`, `output_dir`. The advanced keys are
   per vendor: `tune_file` (MassLynx `MS_TUNE_FILE`), `data_path` and `bracket_type` and
   `list_separator` (Xcalibur), `max_rows`.
4. `mhp serve pkg:<this folder> --http <port>` and read `connected` and `vendor`.
5. Save the project's method names once: `methods/save {name, project, action: build_worklist,
   params: {ms_method, lc_method}, compounds: [...]}`. The shipped example under
   `methods/demo-assay/` shows the record.

Method names must exist on the acquisition PC exactly as written; the package cannot check them.

## First hardware test

1. Build a one-row worklist of a blank injection (`sample_type: blank`, a real vial position, a
   method that exists), and open the written file in a text editor: header row, one data row.
2. Import it into the vendor software (MassLynx: File > Import Worksheet, file type "Comma
   Delimited (*.CSV, *.TXT)"; SCIEX OS: Batch, Open > Import from file; MassHunter: worklist
   right-click > Add/Append Samples from...; Xcalibur: Sequence Setup, File > Import Sequence)
   and check every column landed where the software expects it.
3. For SCIEX OS and Xcalibur, export a batch or sequence from the software itself and compare
   its header row with the one this package writes (`references/worklist_formats.md` says which
   names are reconstructed rather than verified). If they differ, tell the maintainer: the column
   list in `driver.py` `FORMATS` is the one thing to change.
4. Run the blank from the vendor software; confirm the data file name and method were taken.
5. Then a real list with a standard, a QC and samples.

## Status

Twin tested. The formats are written from the vendor documents and the Apache-2.0 LabMCP
ms-worklist server's notes (see `references/worklist_formats.md`); the files have not yet been
imported into MassLynx, SCIEX OS, MassHunter or Xcalibur by the package author.
