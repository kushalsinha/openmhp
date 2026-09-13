---
mhp: "2026-09-12"
id: gc-01
class: gc
make: SimChrom
model: GC-7 FID
location: bay 2, fume hood 1
tags: [chromatography, gc, separation, analysis, solvents]
description: Gas chromatograph with split/splitless inlet and flame ionisation detector, 40 to 320 degC oven. Use for separating and quantifying volatile compounds (solvents, residual monomers, fragrance components) by running a saved method per injection. Not for non-volatile or thermally unstable samples.
driver: driver.py:SimGC
sim: sim.py:SimGC
---

# GC-01

Sits in fume hood 1 of bay 2 with the autosampler on its left. Every injection runs one **method**:
an oven program (start temperature, ramps, holds), the injection volume, and optionally a carrier
flow for that run. Methods are owned by projects, not by this package: look them up by compound
with `mhp_method op='for_compound'`, and save new ones with `op='save'`, which checks them against
this instrument's limits before they are stored.

## Operating procedure

1. Read `detector_ready`. If false, the FID is not lit or not at temperature; `run_method` is
   refused until it is. Read `carrier_flow` and `oven_temperature` to see the instrument is idle.
2. Pick the method: `mhp_method op='for_compound' compound=<name> project=<project>`. If several
   match, ask the person which one; in an autonomous loop, take the one filed under the project.
3. Run it: `mhp_method op='run' device='gc-01' method=<name>`, or from a script
   `run_method(dev, methods.get(name))`. The job result holds the peaks, the resolution between
   neighbouring peaks and a compact chromatogram. `last_result` is pushed to subscribers the moment
   the run finishes, so a run script or the bridge sees it without polling.
4. To adapt between runs, change a parameter within the limits (a lower `carrier_flow_ml_min`
   separates close peaks better at the cost of run time; a slower ramp does the same) and pass it as
   an override without saving a new method until the person is satisfied.
5. Save the final parameters as a new version of the method (`op='save'` with the same name) so
   the next run of that compound starts from what worked.

## What to watch

- Resolution below 1.5 between neighbouring peaks means they are not baseline-separated; the
  result flags them in `unresolved`.
- Oven steps outside 40 to 320 degC, ramps outside 1 to 50 degC/min and programs longer than
  60 minutes are refused, in dry runs too.
- `bakeout` is confirm-gated and takes 30 minutes; nothing else can run during it.
- A failed run leaves the device in `fault`; read `oven_temperature` and `detector_ready`, then
  `safety/reset` after a person agrees the cause is understood.

## Resources

- `references/methods.md`: how method parameters affect retention, resolution and run time on this column.
