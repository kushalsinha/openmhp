---
mhp: "2026-09-12"
id: crystal16-solubility-01
class: reactor
make: Technobis
model: Crystal16 under CrystalClear
location: ""
tags: [solubility, crystallisation, clear-point, cloud-point, turbidity, file-based]
description: Technobis Crystal16 parallel crystalliser (16 vials in four temperature blocks, a turbidity probe per vial) under CrystalClear, reached through files on the CrystalClear PC, a temperature program the software imports and the data report CSVs it exports. Pick it to measure clear and cloud points (solubility and metastable zone width) for up to 16 compositions with one heat/cool program per compound. A person imports and starts the program in CrystalClear; there is no API and no remote stop. Not for the 8-vial Crystalline, whose exports differ.
driver: driver.py:Device
sim: sim.py:Sim
---

# Technobis Crystal16 (CrystalClear, file based)

CrystalClear on the instrument PC runs the temperature program and logs, per block, the setpoint, actual
temperature and the four reactors' transmission. This package writes a program file in the software's own
step vocabulary (unverified as an import format: see `references/files.md`), waits for the export per block,
and turns each transmission trace into a clear point (heating) and a cloud point (cooling).

## Operating procedure

1. Read `connected`. Fill the vials (0.5 to 1.0 mL, a stirrer bar each), place them in the blocks, and type
   each vial's content into CrystalClear's reactor descriptions; they come back in the result.
2. Find the compound's program (`methods/find {compound: "..."}`) or write one: `program.steps` of heat, cool
   and hold with rates in K/min, `program.cycles`, `program.stirrer_rpm` (or write the `stirrer_rpm` setting).
3. Invoke `run_program`. The package writes `<name>.csv` into `program_dir`; a person imports it in CrystalClear
   and starts the run (the job reports phase `temperature program` meanwhile).
4. When CrystalClear has exported the data reports into `export_dir` (one per block, auto-export or a manual
   export named after the program), the job parses them and returns clear and cloud points per reactor.
5. To stop a program, a person stops it in CrystalClear.

## What to watch

- A reactor with `clear_point_c` null never reached 90 percent transmission: too concentrated, or the probe
  is dirty. `cloud_point_c` null means it never nucleated on cooling (oiling out, or too slow a cycle).
- The clear point is the upper bound of solubility at that heating rate; slower rates (0.1 to 0.5 K/min)
  give values closer to equilibrium. The metastable zone width is clear minus cloud.
- Exports older than the program start are ignored; name the export after the program so the job finds it.
- Sealed vials heated above the solvent's boiling point are under pressure; keep the program within the
  limits set for this solvent.

## Resources

- `references/setup.md`: the two shared folders, auto-export, config.json, first test.
- `references/files.md`: the export CSV layout (documented), the program file this package writes (unverified), and the point detection.
- `methods/_shared/mszw-screen.yaml`: an example heat/cool program.
