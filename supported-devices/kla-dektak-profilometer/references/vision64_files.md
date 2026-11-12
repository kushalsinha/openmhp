# Vision64 control, `.OPDx` datasets and the database CSV: documented, assumed, unverified

Searched 2026-11-11. "unverified" means not read in a Bruker or KLA document.

Sources read:

- Bruker, "DektakXT Stylus Profiler User Manual", P/N 980-365 (2011; university-hosted copies):
  measurement recipes (.visrcp per lab SOPs) with Scan Type, Range (6.5 um / 65.5 um / 524 um /
  1 mm), Profile (Hills, Valleys, Hills and Valleys), Stylus Type, Stylus Force (mg), Length (um),
  Duration (s), Resolution and Speed computed; Advanced Options with Auto Save File Name (a
  `$(Seq)` macro gives one file per repeat); datasets saved as `.OPDx`; Automation recipes
  (multi-site, "Completed script named ..."); Analyze > Database Setup > Create New CSV with
  selected metadata and analytical results, a row appended per measurement; the tower lowers
  at the start of every scan; the EMO box power-off button; tower travel 50 mm, samples to
  50 mm thick and 200 mm across.
- Bruker, DektakXT datasheets B516 Rev. A1 (2011) and Rev. B3 (2020): scan length 55 mm (200 mm
  stitched), stylus force 1-15 mg (0.03-15 mg with N-Lite+), vertical range 1 mm, 120,000 points
  per scan, step-height repeatability 4-5 A, stylus radii 50 nm to 25 um, Windows 7 / Windows 10;
  software options "Advanced Production Interface (API)" (an operator workflow, not a programming
  interface). Bruker's "upgrade your optical profilers" page: a "TCP/IP Runtime Control Server"
  option "allows external control of profilers through Vision's TCP/IP command set" and a
  MATLAB scripts option; the command set is not published and its availability for Dektak is
  not stated.
- Gwyddion file module `dektakvca.c` (Dektak OPDx) and SurfaceTopography's OPDx reader: the
  12-byte header `VCA DATA` 01 00 00 55, named typed items (4-byte LE name length, name, 1-byte
  type, payload), containers giving `/MetaData/...` and `/1D_Data/Raw/Array` paths.
- KLA-Tencor, "Alpha-Step D-500 and D-600 User Manual" 9019320-000 Rev. AC: scan length 30/55 mm,
  speed 0.01-0.4 mm/s with a 3 s minimum scan time, force 0.03-15 mg, vertical range 1200 um,
  `.rcp` scan recipes, sequences, auto-save (XML) and auto-export (CSV); no remote interface.
- University SOPs (UC Davis, USC, Notre Dame, Caltech, EPFL, UF, Montana State, Texas A&M) for
  the recipe field names, the stylus-crash warnings and the right-click CSV export of a profile.

## The assumed command channel (config.json `commands`) -- every string unverified

A line-oriented ASCII protocol over TCP, CRLF-terminated, one reply line per command, `OK ...`
or `ERR ...`. Bruker's actual command set replaces every row.

| key | placeholder | role |
|---|---|---|
| status | STATUS | the status signal (reply words idle / scanning / tower / error are mapped) |
| load_recipe | LOAD_RECIPE {path} | load a .visrcp |
| set | SET {field} {value} | fields SampleID, Length (um), Duration (s), Force (mg), Range (um), Profile, AutoSaveFileName |
| run | RUN | lower the tower and scan |
| abort | ABORT | stop a scan |
| tower_up | TOWER_HOME | raise the tower to home |

## The `.OPDx` dataset (read from `data_dir/<sample_id>_<token>.OPDx`)

Only the 12-byte header is checked (verified: Gwyddion). The profile itself is not parsed: the
step height comes from Vision64's own analysis via the database CSV, which is what a lab
compares against. The CSV profile export Vision64 offers is a manual right-click action and its
column layout is not public.

## The database CSV (read from `db_csv`)

Verified mechanism: Vision64 appends one row per measurement with the columns the lab selected
at Database Setup. The package reads the header row, finds the row whose `Sample ID` column
(config `columns.sample`) equals `<sample_id>_<token>`, and takes the `ASH` column
(`columns.step_height`, the average step height result) in `step_height_unit` (nm by default;
um and A are converted). The column names and the unit are the lab's choices and unverified.

## The twin

The fake server answers the placeholder commands, runs a scan for Duration plus 5 s (scaled),
then writes the .OPDx header plus a small payload and appends a database row with a step
height of about 500 nm (lower by 0.4 % per mg above 3 mg, 1.5 nm noise).
