---
mhp: "2026-09-12"
id: lcms-worklist-01
class: mass_spectrometer
make: Waters, SCIEX, Agilent or Thermo
model: LC-MS sample queue under MassLynx, SCIEX OS, MassHunter or Xcalibur
location: ""
tags: [lcms, mass-spectrometry, worklist, sample-list, masslynx, xcalibur]
description: An LC-MS sample queue written as the import file of the vendor acquisition software (Waters MassLynx 4.x sample list, SCIEX OS batch, Agilent MassHunter Acquisition worklist or Thermo Xcalibur sequence; one vendor per package instance). Pick it to turn a list of samples, vial positions, injection volumes and method names into the file a person imports and starts; it never starts an acquisition and reads no data. Not for writing MS or LC methods, and not for instruments whose software has a real API.
driver: driver.py:LCMSWorklist
sim: sim.py:SimLCMSWorklist
---

# LC-MS worklist builder

The vendor acquisition software owns the mass spectrometer, the LC, the methods and the data.
This package does one thing it cannot: it builds the sample queue from a request and writes it
in the exact import format of the configured vendor (`vendor` in config.json), into the folder
the vendor PC reads. A person imports the file and presses start. Each file is read back after
writing, so the result reports rows the vendor import will see.

## Operating procedure

1. Read `connected` and `vendor`. `connected` is false when config.json names no vendor or the
   output folder is missing or read-only.
2. Find the project's method: `methods/find {compound, project}` returns the saved MS and LC
   method names (a method here is the pair of method names, not the samples).
3. Invoke `build_worklist` with `method: {name, project}` and `params: {samples: [...]}` in run
   order: name, vial position in the vendor's notation, injection volume, sample type. Blanks
   and standards are rows like any other. With no saved method, pass `ms_method` and
   `lc_method` explicitly and save them afterwards.
4. Read the result: `file` is the full path; tell the person which file to import and where
   (MassLynx: File > Import Worksheet, "Comma Delimited"; SCIEX OS: batch Open > Import from
   file; MassHunter: worklist row > Add/Append Samples from...; Xcalibur: Sequence Setup, File >
   Import Sequence).
5. Nothing to stop: the run is started and stopped in the vendor software.

## What to watch

- Method names are written as given and are not checked against the vendor PC; a wrong name
  fails at import or at the first injection. Vial positions are written as given, too.
- Data file names must be unique within one file; generated names carry the date and job id.
- A file with the same name is never overwritten; pick another `worklist_name`.
- SCIEX OS and Xcalibur header rows are reconstructed from documentation, not from a vendor
  export; the first import on a new system should be checked against a batch or sequence
  exported there (see `references/worklist_formats.md`).

## Resources

- `references/setup.md`: the folder, the vendor and the first test.
- `references/worklist_formats.md`: the four formats, column by column, with sources and what is unverified.
- `config.example.json`: vendor, output folder and the advanced per-vendor fields.
