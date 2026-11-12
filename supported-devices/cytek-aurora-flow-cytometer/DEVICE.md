---
mhp: "2026-09-12"
id: cytek-aurora-flow-cytometer-01
class: flow_cytometer
make: Cytek Biosciences
model: Aurora / Northern Lights under SpectroFlo
location: ""
tags: [flow-cytometry, spectral, immunophenotyping, viability, fcs, biologics]
description: Cytek Aurora or Northern Lights full-spectrum flow cytometer under SpectroFlo, reached through a watched folder that takes a one-row worklist (tube or well, sample name, stop criteria, flow rate) and the FCS 3.1 file plus optional statistics CSV SpectroFlo exports. Pick it to queue one sample's acquisition against a saved experiment template (viability, immunophenotyping, bead assays) and read the event count, parameter names and file paths back. Not for unmixing, gating, QC or panel design; those stay in SpectroFlo. A BD FACSymphony or FACSCanto under FACSDiva is the usual alternative and is not driven by this package.
driver: driver.py:Device
sim: sim.py:Sim
---

# Cytek Aurora flow cytometer

SpectroFlo owns the cytometer, the experiment templates, the daily QC and the data, and has no API.
This package does what a person at the acquisition PC is asked to do by a note: it drops a one-row
worklist (`mhp_<job>.csv`) into a watched folder, waits for the FCS 3.1 file with the job's token in
its name that SpectroFlo exports, reads the file's TEXT segment ($TOT, $PAR, $PnN) and reports it.
A helper script may act on the worklist unattended, or a person does; the FCS file is what counts.

## Operating procedure

1. Read `connected` (both folders reachable), `queue_depth` (worklists nobody has acquired yet) and
   `sheath_level_ok` (null unless the lab writes a status file; then ask the person).
2. Find the method: `methods/find` with the panel and project. A saved method here names the
   experiment template, the stopping rule and the flow rate for one panel;
   `methods/_shared/viability-7aad.yaml` is the example.
3. Make sure the sample is on the loader at the position you will name (or the tube is on the
   sample injection port), that SpectroFlo's daily QC has passed and that the template's reference
   controls exist. The package cannot check any of these.
4. Invoke `queue_acquisition` with the method (`actions/invoke {method: {name, project, overrides:
   {sample_name, position}}}`) or explicit params; a person confirms. 10,000 events at medium flow
   rate take under a minute plus loader time, plus however long the helper takes.
5. Read the result: `events`, `parameters`, `channels`, the FCS path and, when exported, the
   statistics CSV path. Gating and unmixing happen in SpectroFlo or in the analysis software of the
   lab; this package only verifies the file is a complete FCS 3.1 data set.

## What to watch

- A job that fails with "no FCS file ... within result_wait_s" left its worklist in the watched
  folder on purpose; a person sees what was asked.
- `events` far below `stop_events` means the time criterion stopped the acquisition, or a clog
  (SpectroFlo's event rate drops): check `stats_file` and the person's notes.
- A DATA-segment length that does not match $TOT and $PAR fails the job as an incomplete export;
  wait for SpectroFlo to finish writing and retry.
- Sheath low (yellow in SpectroFlo gives about five minutes), waste full and the SIT flush between
  samples are the person's; an e-stop here only withdraws worklists not yet taken.

## Resources

- `references/setup.md`: the folders, the helper or the person, config.json, Windows, first test.
- `references/file_formats.md`: the worklist this package writes, the FCS 3.1 layout it reads
  (from the ISAC normative reference) and the statistics CSV, with what is verified and what is not.
- `config.example.json`: worklist and export folders, allowed templates, timeouts.
