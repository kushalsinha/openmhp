# Setting up

The vendor route is Windows-only: SpectroFlo runs on the Windows PC attached to the Aurora, and that
PC (or a share of two of its folders) is what this package talks to. The package itself is pure
Python and can be served from that PC or from any machine that can write to the two folders; the
simulated twin runs anywhere.

Needed on the acquisition PC:

- SpectroFlo (3.x; the version installed with the instrument). No vendor library, licence or API
  option exists for this route. Experiment templates for the panels an agent may queue saved in
  the library, with their reference controls.
- Two folders: one the package writes worklists into (for example `C:\OpenMHP\aurora\worklists`)
  and one SpectroFlo exports into (its Export folder, `C:\CytekbioExport` by default, or a
  subfolder set in Storage Preferences), writable by the account that serves the package.
- Something that turns a worklist row into an acquisition and an export:
  1. A person: opens `worklists\mhp_<job>.csv`, opens the named template (Acquisition >
     Experiments > Template), names the tube or well as the row says, sets the stopping rule
     (events, time) and flow rate, records, and makes sure the FCS file (SpectroFlo writes FCS 3.1
     to the Export folder) carries the token in its name; optionally exports the worksheet
     statistics box as CSV with the same token.
  2. A helper script written by the lab that drives SpectroFlo's user interface the same way.
     Nothing here depends on how; only on the files.

Steps:

1. `pip install openmhp` on the serving machine (no vendor library; the FCS reader is in the driver).
2. Copy `config.example.json` to `config.json`: `import_dir`, `results_dir`, the SpectroFlo
   version for the record, `allowed_templates`, and the timeouts (`result_wait_s` 3600 s covers a
   plate well with a slow loader and a slow helper).
3. `mhp serve pkg:<this folder> --http <port>` and read `connected`.

## First hardware test

1. Read `connected` and `queue_depth` (0; delete stale `mhp_*.csv` worklists otherwise). Run
   SpectroFlo's daily QC first.
2. Put a tube of SpectroFlo QC beads (or any stained control) on the sample injection port.
3. Invoke `queue_acquisition` with the second example (`position: T1`, `template: null`, 5000
   events or 120 s, low flow rate) and confirm it. Watch `worklists\` for `mhp_<job>.csv`.
4. Acquire the tube in the open experiment as the row says and export (or rename) the FCS file to
   `mhp_<job>.fcs` in the export folder. The job should finish within seconds and report `events`
   (5000, or fewer if 120 s came first), `parameters` and the `channels` list starting with Time,
   FSC-A, SSC-A and the detector channels.
5. If the job fails with "not an FCS file" or a DATA-length mismatch, open the file in any FCS
   reader; a SpectroFlo file is FCS 3.1 with float data, which is what the reader expects. Report
   the TEXT keywords if they differ from `references/file_formats.md`.

## Status

Driver written from the Cytek Aurora User's Guide (52-70001-0C) and the ISAC FCS 3.1 normative
reference; the worklist import and the statistics export columns are marked unverified in
`references/file_formats.md`. Not yet run against the instrument. Status: twin tested.
