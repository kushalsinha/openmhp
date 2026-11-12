# Setting up

MITS Pro runs on the Windows PC connected to the cycler; this route is **Windows-only** in practice
because the request and results folders live on that PC (a share of them can be served from another
machine, but someone at the MITS Pro console does the starting and exporting). The package itself is
pure Python; the simulated twin runs anywhere. **Status: template.**

Needed:

- MITS Pro (version 8 was the reference for the export columns) with the lab's schedules (`.sdu`)
  saved in its schedule library. No SDK, licence or option: the console and SDK are under NDA and
  this package does not use them.
- Two folders on that PC, for example `C:\OpenMHP\arbin\requests` and `C:\OpenMHP\arbin\results`,
  writable by the account that serves the package.
- Someone to start each test: open the request, select the channel in MITS Pro, Start Channel(s)
  with the named schedule and the test name from the request, then delete the request. When the
  test ends, export that channel's data as CSV named after the test name into the results folder.
  A helper that drives the console may do the same; nothing here depends on how.

Steps:

1. `pip install openmhp` on the serving machine.
2. Copy `config.example.json` to `config.json`: `request_dir`, `results_dir`, `software`,
   `allowed_schedules`, the chemistry caps `voltage_max_v` and `current_max_a`, and the timeouts
   (`result_wait_s` 1209600 s = 14 days covers a formation test).
3. `mhp serve pkg:<this folder> --http <port>` and read `connected`.

## First hardware test

1. Read `connected` and `queue_depth` (0; delete stale `mhp_*` files from the request folder otherwise).
2. Write a short schedule in MITS Pro (CC charge 60 s, rest 60 s, CC discharge 60 s) on a dummy cell
   and save it as `Short_test.sdu`.
3. Invoke `start_protocol` with the first example, `schedule` "Short_test.sdu" and `time_limit_s` 60 on
   each step, and confirm it. Watch the request folder for `mhp_<job>.json`.
4. In MITS Pro: Start Channel(s) on that channel with `Short_test.sdu` and the test name from the
   request; delete the request. When it ends, export the channel's data as CSV named after the test
   name into the results folder.
5. The job should finish within a minute of the export and report `cycles_completed` 1,
   `last_capacity_ah` and `final_voltage_v`. If it fails with "results columns not recognised",
   compare the export's header with `references/file_formats.md` and adjust the export settings.

## Status

Template. Written from Arbin's public pages and the MITS Pro 3.0 manual's table of contents for the
workflow, and from public descriptions of the MITS Pro CSV export for the columns; the request file
is this package's own layout and the export column names are unverified against the lab's version.
Not run against the instrument. Windows-only route (the MITS Pro PC).
