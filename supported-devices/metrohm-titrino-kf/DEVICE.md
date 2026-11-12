---
mhp: "2026-09-12"
id: metrohm-titrino-kf-01
class: titrator
make: Metrohm
model: 870 KF Titrino plus (or 758 KFD / 784 KFP / 787 KF Titrino) over RS-232
location: ""
tags: [titrator, karl-fischer, water-content, serial, metrohm]
description: Metrohm volumetric Karl Fischer titrator (870 KF Titrino plus through its RS-232/USB box, or a 7xx KF Titrino over its RS-232 port) driven with Metrohm's documented remote-control commands. Pick it to determine the water content of a weighed sample with a stored KF method (one method per sample type), to wait for the cell to condition, and to read the result, titrant consumption and drift. Not for coulometers, Titrandos or tiamo/OMNIS systems, which use USB and their own software, and not for weighing or injecting the sample.
driver: driver.py:Device
sim: sim.py:Sim
---

# Metrohm KF Titrino (RS-232)

The Titrino runs its own KF methods and conditions its cell between determinations. This package speaks
the instrument's remote-control protocol: on the 870 KF Titrino plus the synchronous `$G/$S/$H/$D/$L/$Q`
commands through the RS-232/USB box on COM2; on the older 7xx Titrinos the object-tree commands
(`&Mode $G`, `&UserMeth.Recall`, `&SmplData...`, `&Info.TitrResults...`). `config.json` picks the dialect.

## Operating procedure

1. Read `connected`, `titrator_status` and `cell_conditioned`. After a reagent change the cell needs a few
   minutes of conditioning; invoke `condition` to wait for it.
2. Weigh the sample; write `sample_mass_g` (or pass it to `determine`). On the plus dialect the mass is
   only recorded here, so the method must take its sample size from the balance or a fixed value.
3. Find the method for the sample type (`methods/find {compound: "..."}`) and invoke `determine`; inject
   the sample when the instrument starts titrating (`titrator_status` reads Busy). The job ends when the
   status returns to Ready or Cond and reads the result.
4. Read the result: water content in the method's unit, titrant volume, duration, drift (classic dialect).
5. `stop` or `estop` ends a running titration.

## What to watch

- `cell_conditioned` false for more than 20 minutes means a leak (vessel stopper, septum, drying tubes) or
  exhausted reagent; the `condition` job fails after its timeout.
- A result far below the drift-corrected expectation means the sample was injected before the titration
  started; check the sequence of `$G` and the injection.
- `drift_ug_min` is null on the plus dialect (no documented variable); read the drift on the display.

## Resources

- `references/setup.md`: the RS-232/USB box, COM2, baud, the dialect, config.json, first test.
- `references/rs232.md`: the commands and variables used, by dialect, with sources and the unverified parts.
- `methods/_shared/kf-std.yaml`: an example method record.
