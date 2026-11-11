# ICON-NMR job files and TopSpin datasets

What the package writes and reads, with the source for each detail. "unverified" marks what was
reconstructed rather than read in a Bruker document; the first hardware test checks those.

Sources read:

- Bruker "TOPSPIN, IconNMR, and Assure-RMS in Automation" user manual (document B7150, the
  IconNMR 4.6 / TopSpin 3 era), sections "IconNMR Configuration", "Running IconNMR" and 6.4
  "Example csv File for Batch Submission" (the example itself is an image in the PDF; its caption
  says the first line must contain some character and may not be a sample row, i.e. a header
  row is required). Data path given in the same manual as
  `<drive>:/Bruker/TOPSPIN/data/<user>/nmr/<filename>/<expno>/pdata/<procno>/1r`.
- UCL NMR facility, "Common problems": ICON-NMR File > Import Spreadsheet .csv file, columns are
  chosen at import time; avoid spaces in dataset names.
- Oxford Chemistry Research Laboratory, "Use of ICON-NMR for Automated NMR Operation" (Feb 2025)
  and the 2013 edition: the submission fields (holder, name, number, solvent, experiment,
  parameters such as NS via the parameter icon, title via the notepad icon), Start / Pause / Stop
  of the run, `halt` in TopSpin to end an experiment early.
- Carleton College IconNMR guide (2018): "No." is the EXPNO in TopSpin.
- TopSpin parameter file format: `acqus` and `procs` are JCAMP-DX-like text with `##$NAME= value`
  lines (`##$NS= 16`, `##$TD= 65536`, `##$SW= 20.0`, `##$O1= 2470.0`, arrays as
  `##$D= (0..63)` followed by the values). Widely documented (nmrglue's bruker reader,
  Bruker TopSpin Acquisition Commands and Parameters manual).

## The job file (written to `import_dir/<token>.txt`)

One job per file, tab-separated, CRLF, a header row then one row. ICON-NMR removes or renames a
file it has imported, which the package uses to tell "waiting" from "acquiring".

| column | value | status |
|---|---|---|
| USER | config `user` | header word unverified; the field exists in the submission window |
| NAME | dataset name (`dataset` param or `mhp_<date>_<job>`) | unverified word; the "Name" field of the submission |
| HOLDER | holder number | unverified word; the "Holder" column of the submission window |
| EXPNO | experiment number (next free or given) | unverified word; the "No." field |
| SOLVENT | TopSpin solvent name | unverified word; the "Solvent" field |
| EXPERIMENT | parameter set name | unverified word; the "Experiment" field |
| TITLE | title text | unverified word; the notepad "Title" |
| NS, D1 | only when `ns` / `d1_s` were given | parameter overrides as the submission window's parameter editor exposes them; the column convention is unverified |

The automation import folder and whether ICON-NMR reads tab-separated files from it (as opposed
to the interactive spreadsheet import) is the part of this route with the thinnest documentation:
the ICON-NMR manual's "Automation" chapter for the installed version is the authority, and the
setup note's first test compares this file with it. The CSV spreadsheet import (File > Import
Spreadsheet) lets a person map columns at import time, so the same file imports by hand.

## The dataset (read from `data_dir/<dataset>/<expno>/`)

| file | use | status |
|---|---|---|
| `acqus` | acquisition parameters; the package returns NS, SW (ppm), O1 (Hz), TD | verified format |
| `pdata/1/1r` | processed real spectrum (binary int32, or float when `##$DTYPP=` says so); its presence marks the experiment as processed | verified location |
| `pdata/1/title` | the title text | verified location |
| `pdata/1/procs` | processing parameters (`##$SI=`, `##$LB=`...) | verified format, not read |
| `fid`, `audita.txt`, `pulseprogram` | raw data, audit trail, pulse program | not read |

Completion is detected as "acqus and pdata/1/1r both exist": ICON-NMR processes automatically
after acquisition, so 1r appears last. A system with processing disabled would never satisfy
it; enable automatic processing for the ICON-NMR user.

The data path: TopSpin 3 and older file `<DIR>/<user>/nmr/<dataset>/<expno>`; TopSpin 4 files
`<DIR>/<dataset>/<expno>`. `data_dir` is whichever folder sits directly above `<dataset>`.

## The twin

The twin writes `acqus` (NS, DS, TD, SW, O1, D array, SOLVENT, PULPROG, EXP, SFO1), `title`, a
`procs` and a placeholder `1r` (a text note, not binary data) after a scaled wait of about
180 s plus `ns x (scan time + D1)`, and deletes the job file 2 s (scaled) after it was written.
