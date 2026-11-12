# Files this package writes and reads

## Sources

- *QuantStudio Design and Analysis Software 2 User Guide*, v2.8, Thermo Fisher publication
  MAN0018200 Rev. M (15 October 2025):
  - "Import a plate setup file (samples)" (p. 36): file types TXT and CSV; Plate Setup tab, More
    Options > Import Plate Setup (96-well 0.2 mL, 96-well 0.1 mL, 384-well, TaqMan Array Card);
    the plate setup is overwritten. "Export a plate setup file" (p. 53): the same two types.
  - "Paste samples into the plate layout" (p. 37): column headers must match the Samples table.
  - "Export data" (p. 78): Actions > Export; Export Name, File Format, Destination, Export Settings.
    "View or edit export settings" (p. 98): each of Results, Amplification Data, Multicomponent,
    Raw Data and Replicate Group Result is exported as a separate file; options include "Use two
    digits in well position" and a section header.
  - Well Table fields (p. 80): Well, Sample, Target, Task, Cq, Cq Confidence, Amplification Score,
    Amplification Status; Replicate Group Results: Sample, Target, Number of Replicates, Cq Mean,
    Cq Standard Deviation. Amp Status values (p. 59): Amp, No Amp, Inconclusive, N/A.
- Thermo Fisher QuantStudio 5 FAQ (product A28139): a run set up in the cloud Design and Analysis
  application is started at the instrument touchscreen with "Open Template"; monitoring is possible
  from the touchscreen, the desktop software, Thermo Fisher Connect or the Instrument Connect app.
  No source describes a remote start from the desktop software on a QuantStudio 5.
- University protocol (Bridges lab, "Set up qPCR Run on Thermo Cloud and QuantStudio"): a plate
  layout exported from the software and filled with Sample Name, Target Name, Task, Reporter,
  Quencher per well, then imported with Import Plate Setup.

## Plate setup file (written by this package): `import_dir/mhp_<job>_plate_setup.txt`

Tab-separated, one header line and one row per used well:

```
Well	Sample Name	Target Name	Task	Reporter	Quencher
A1	calibrator mhp_job_1a2b3c4d	GAPDH	UNKNOWN	FAM	NFQ-MGB
A3	NTC mhp_job_1a2b3c4d	GAPDH	NTC	FAM	NFQ-MGB
```

The user guide confirms TXT/CSV import and the Samples-table fields; the exact header spellings
(`Well` versus `Well Position`, `Sample Name`, `Target Name`, `Task`, `Reporter`, `Quencher`) are
taken from the university protocol and are **unverified** against an export from v2.8. The lab's
first test exports a plate setup from the software and compares headers. Task values UNKNOWN,
STANDARD, NTC, POSITIVE are the software's; STANDARD wells need a quantity the file does not
carry (set it in the template or in the software). Reporter and quencher come from config.json.

## Request (written by this package): `import_dir/mhp_<job>.json`

```json
{"token": "mhp_job_1a2b3c4d", "plate_id": "QS5-2026-0142", "template": "GAPDH_TaqMan_fast.edt",
 "plate_setup_file": "mhp_job_1a2b3c4d_plate_setup.txt",
 "program": {"stages": [{"steps": [{"temp": 95, "hold_s": 20}], "cycles": 1},
                        {"steps": [{"temp": 95, "hold_s": 1}, {"temp": 60, "hold_s": 20}], "cycles": 40}]},
 "export": "mhp_job_1a2b3c4d_Results.csv", "written": 1760000000.0}
```

`program` is informative: the template holds the real run method; the person starting the run
checks they match. Both files are deleted by whoever starts the run; `queue_depth` counts those
left; an e-stop deletes them. Template files are `.edt` (experiment template) and data files
`.eds` (experiment document), as the software names them.

## Results export (read by this package): `results_dir/*mhp_<job>*.csv` or `.txt`

Lines before the first one starting with `Well` are skipped (the export's metadata block and
section header). Assumed columns (**unverified** spellings; the parser matches loosely):

```
Well,Well Position,Sample Name,Target Name,Task,Reporter,Quencher,CT,Ct Mean,Ct SD,Quantity,Amp Status
1,A1,calibrator mhp_job_1a2b3c4d,GAPDH,UNKNOWN,FAM,NFQ-MGB,26.512,26.512,0.12,10234.1,Amp
3,A3,NTC mhp_job_1a2b3c4d,GAPDH,NTC,FAM,NFQ-MGB,Undetermined,,,,No Amp
```

- well: `Well Position` if present, else `Well`; sample: `Sample Name` or `Sample`; target:
  `Target Name` or `Target`.
- Cq: `CT`, `Cq` or `Ct` (v2 names it Cq; v1 and older exports CT); `Undetermined`, blank or N/A
  become null.
- quantity: `Quantity` when present; amplification status: `Amp Status` or `Amplification Status`.
- Rows whose sample name lacks the job token are ignored; the token is stripped from `sample`.

## Twin

The twin's fake PC "starts" the plate as soon as the request lands (`run_state` reads `running`),
waits the program's time (20 s ramp per step plus holds, times cycles; 65 min when no program is
given) scaled by `OPENMHP_SIM_TIME_SCALE`, then writes `mhp_<job>_Results.csv` in the layout above:
Cq near 26.5 for UNKNOWN, 22 for POSITIVE, Undetermined/No Amp for NTC.
