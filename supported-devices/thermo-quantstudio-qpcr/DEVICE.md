---
mhp: "2026-09-12"
id: thermo-quantstudio-qpcr-01
class: real_time_pcr_machine
make: Applied Biosystems (Thermo Fisher Scientific)
model: QuantStudio 5/7 under QuantStudio Design & Analysis Software 2
location: ""
tags: [qpcr, real-time-pcr, taqman, sybr, quantstudio, biologics]
description: Applied Biosystems QuantStudio 5 or 7 real-time PCR system under QuantStudio Design & Analysis Software 2, reached through a watched folder that takes a plate setup file plus a request naming the run template, and the Results export the software writes. Pick it to queue a 96-well qPCR plate (residual DNA, copy number, gene expression, mycoplasma) against a saved template and read Cq, quantity and amplification status per well back. Runs start at the instrument's touchscreen unless the lab's helper starts them; not for building templates or analysis settings, which stay in the software.
driver: driver.py:Device
sim: sim.py:Sim
---

# QuantStudio 5/7 qPCR

QuantStudio Design & Analysis Software 2 owns the templates, the run method and the data. It imports a
plate setup file (TXT or CSV: Well, Sample Name, Target Name, Task, Reporter, Quencher) into a plate
file and exports analysed results per plate; a run on a QuantStudio 5 or 7 is started at the
instrument's touchscreen ("Open Template") or from the software connected to it. This package writes
the plate setup file and a request naming the template, waits for the Results export carrying the
job's token in the sample names, and turns it into a result.

## Operating procedure

1. Read `connected` (both folders reachable), `queue_depth` (plates nobody has started yet) and
   `run_state` (`queued` while a request waits; the instrument's own state is not exported).
2. Find the method: `methods/find` with the assay and project. A saved method here names the run
   template and the cycling program it is expected to hold; `methods/_shared/taqman-fast-40.yaml` is
   the example. Overrides supply the plate id and the plate setup.
3. Make sure the sealed plate is on the block (or will be placed by the handling system) and that the
   named template exists in the software's library. The package cannot check either.
4. Invoke `queue_run` with the method (`actions/invoke {method: {name, project, overrides: {plate_id,
   plate_setup}}}`) or explicit params; a person confirms. A 40-cycle fast run takes about an hour;
   the job waits for the export (`result_wait_s`, 4 h by default).
5. Read the result: one row per well and target with Cq (`ct`, null when Undetermined), quantity and
   amplification status; `file` is the export for everything else (Cq mean and SD, raw data).

## What to watch

- A job that fails with "no results export ... within result_wait_s" left the plate setup file and
  the request in the watched folder on purpose; a person sees what was asked.
- `ct` null with `amp_status` "No Amp" in an NTC is right; in a sample it is a question for the
  person. `Inconclusive` rows need the amplification plot in the software.
- The heated cover is hot after a run and the block's plate-access cover state is not exported: a
  handling system must take that state from elsewhere before it unloads.
- The instrument's Stop is the only stop; an e-stop here withdraws plates not yet started.

## Resources

- `references/setup.md`: the folders, who starts the run, config.json, first hardware test.
- `references/file_formats.md`: the plate setup file and request this package writes, the Results
  export it reads, and what is verified against the Design & Analysis user guide.
- `config.example.json`: plate and results folders, block size, reporter and quencher, timeouts.
