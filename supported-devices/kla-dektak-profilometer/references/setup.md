# Setting up on the Vision64 PC (Windows only)

Vision64 runs on Windows 7/10 64-bit (Bruker's Dektak XT datasheets), so this package runs on
the instrument PC (or on a PC that reaches its control server over TCP/IP). Windows-only on
the Vision64 side; the package itself is pure Python.

1. Ask Bruker whether the "TCP/IP Runtime Control Server" option (listed for Bruker's profilers
   under Vision64) is available for your Dektak XT licence, and obtain its command set document.
   For a KLA Alpha-Step D-500/D-600, ask KLA for any remote interface; its manual documents only
   `.rcp` scan recipes, sequences and auto-save/auto-export.
2. `pip install openmhp`.
3. Correct every command string in `config.example.json` `commands` from that document (every
   shipped string is a placeholder), set `host`, `port`, `data_dir`, `db_csv`, `recipes_dir`, and
   copy it to `config.json`.
4. In Vision64: save each measurement recipe an agent may run into `recipes_dir` (`.visrcp`),
   set its Advanced Options > Auto Save File Name into `data_dir`; in the analysis recipe set
   Analyze > Database Setup > Create New CSV at `db_csv` with the sample id and the step-height
   result (ASH) selected and logging enabled; set `columns` in `config.json` to those names.
5. Lower `force_mg`, `length_um` and `max_duration_s` to the stylus and samples in use and ship
   that as a package edit.

## First hardware test

1. `mhp serve pkg:<this folder> --http <port>`; read `connected` and `status` (idle).
2. Invoke `tower_up` and confirm the tower homes.
3. With the VLSI step-height standard on the stage and the stylus positioned over it, run `scan`
   (`approved: true`) with the standard's recipe, 1000 um at 100 um/s, 3 mg; confirm the tower
   lowers, the scan runs and the tower rises.
4. Compare `step_height_nm` with Vision64's analysis and open `file` in Vision64.
5. Start a scan and `safety/estop`; confirm the scan aborts and the tower rises.

## Status

Template. No Vision64 command set is public; every command here is unverified and the status
and error replies are assumed. The .OPDx header check and the database CSV mechanism are from
Bruker's manual and Gwyddion's reader (`references/vision64_files.md`). Not yet run on hardware.
