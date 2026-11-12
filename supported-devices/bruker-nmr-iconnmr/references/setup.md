# Setting up on the spectrometer workstation

The package needs no vendor library and no network connection to the spectrometer: it writes
files into a folder ICON-NMR reads and reads files TopSpin writes. Run it on the TopSpin
workstation (Windows or Linux/CentOS as Bruker ships it) with `pip install openmhp`, or on any
machine with the same two folders mounted.

1. Create (or pick) an ICON-NMR user for the agent, for example `openmhp`, in ICON-NMR
   Configuration > User Settings, with the experiments and solvents it may use and the data
   directory it files into. Note the data directory (`data_dir`) and the user name (`user`).
2. Enable the automation import in ICON-NMR Configuration > Automation and note the folder it
   reads (`import_dir`). On systems where ICON-NMR offers only the spreadsheet import
   (File > Import Spreadsheet .csv file), the job file this package writes can be imported by
   hand with the same columns: see `references/iconnmr_files.md`.
3. Copy `config.example.json` to `config.json`: `import_dir`, `data_dir`, `user`; set `holders`
   to the changer size (SampleCase 24, SampleXpress 60; SampleJet racks are addressed as holder
   numbers in ICON-NMR too) and, if the lab wants, `allowed_experiments`.
4. `mhp serve pkg:<this folder> --http <port>`; read `connected` and `queue_depth`.
5. Save the project's methods once (`methods/save`): experiment, solvent, `ns`, `d1_s`. The
   example under `methods/demo-assay/` shows the record.

ICON-NMR's automation run must be started by a person (the green Start in ICON-NMR) and stays
running; this package only adds jobs to it.

## First hardware test

1. With ICON-NMR's run stopped, invoke `queue_experiment` once (PROTON, a holder with a known
   sample, CDCl3) with `approved: true`, then open the job file written to `import_dir` and
   compare its header with what ICON-NMR's import expects (ICON-NMR manual, "Automation"
   chapter; the Bruker manual's csv batch example). Adjust `JOB_COLUMNS` in `driver.py` if the
   words differ and tell the maintainer.
2. Cancel the job (the file is removed) or let ICON-NMR import it with its run started.
3. Watch ICON-NMR pick the job up: the holder is loaded, lock and shim run, the experiment
   acquires. The package's progress rises once the job file disappears.
4. When the job finishes, check the result's `dataset`/`expno` and `acqus` NS against the
   ICON-NMR history window, and open the dataset in TopSpin.
5. Then a C13CPD with the project's `ns` and `d1_s`, and confirm `duration_s` is sensible.

## Status

Twin tested. Written from the ICON-NMR and TopSpin documentation listed in
`references/iconnmr_files.md`; not yet run against a spectrometer. The job file header words
are unverified until step 1 above has been done on a real system.
