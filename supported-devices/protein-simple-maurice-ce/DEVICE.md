---
mhp: "2026-09-12"
id: protein-simple-maurice-ce-01
class: electrophoresis
make: ProteinSimple (Bio-Techne)
model: Maurice (cIEF and CE-SDS) under Compass for iCE
location: ""
tags: [cief, ce-sds, capillary-electrophoresis, charge-variants, purity, biologics]
description: ProteinSimple Maurice imaged cIEF and CE-SDS system under Compass for iCE, reached through a watched folder on the instrument PC that takes a sample table and the peak-table CSV Compass exports. Pick it to queue a charge-variant (cIEF, pI and % area per peak) or purity (CE-SDS, apparent MW and % area) run of a sample already in the 96-well plate, with a saved Compass method, and to read the peak table back. Not for method development, cartridge changes or raw electropherograms; those stay in Compass. The SCIEX PA 800 Plus is the usual alternative and is not driven by this package.
driver: driver.py:Device
sim: sim.py:Sim
---

# ProteinSimple Maurice

Compass for iCE owns the instrument, the methods and the data, and offers no API. This package does
what the person at the Compass PC is asked to do by a note: it drops a sample table (`mhp_<job>.csv`)
into a watched folder, waits for the peak table Compass exports with the job's token in the sample
name, and turns it into a result. A helper script may import and start the batch unattended, or a
person does; the exported peak table is what counts.

## Operating procedure

1. Read `connected` (both folders reachable), `queue_depth` (batches nobody has imported yet) and
   `cartridge_present` (null unless the lab writes a status file: then ask the person).
2. Find the method: `methods/find` with the product and project. A saved method here names the
   Compass method and the replicate count for one product and assay;
   `methods/_shared/cief-charge-variants.yaml` is the example.
3. Make sure the sample is in the plate at the position you will name, and that the right cartridge
   (cIEF or CE-SDS) is fitted. The package cannot check either.
4. Invoke `queue_run` with the method (`actions/invoke {method: {name, project}}`, overriding
   `sample_name` and `position`) or explicit params; a person confirms. A cIEF injection takes about
   10 min and a CE-SDS injection about 35 min, plus the time until someone imports the batch.
5. Read the result: the peak table (label, pI or kDa, area, % area), `main_peak_pct`, and the path of
   the export for the full table.

## What to watch

- A job that fails with "no peak-table export ... within result_wait_s" left its batch file in the
  watched folder on purpose; a person sees what was asked. Run it by hand or delete it, then retry.
- `main_peak_pct` is the Main-labelled peak when Compass labelled one, otherwise the largest peak:
  check `peaks` before trusting it for a specification.
- The cartridge's injection count, the pI-marker fit and the MW ladder are Compass's business; a
  drifting pI or a missing marker shows up as odd `position` values here.
- Compass's Abort and the instrument's cover interlock are the stops; an e-stop here only withdraws
  batches not yet imported.

## Resources

- `references/setup.md`: the folders, the helper or the person, config.json, Windows, first test.
- `references/file_formats.md`: the sample table this package writes and the peak-table export it
  reads, with what is verified and what is not.
- `config.example.json`: batch and results folders, allowed methods, timeouts.
