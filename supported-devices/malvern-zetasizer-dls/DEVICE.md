---
mhp: "2026-09-12"
id: malvern-zetasizer-dls-01
class: particle_analyzer
make: Malvern Panalytical
model: Zetasizer Ultra / Pro (ZS Xplorer); Nano ZS by the same shape
location: ""
tags: [dls, zeta-potential, particle-size, formulation, aggregation, pharma-biologics]
description: Malvern Panalytical Zetasizer Ultra or Pro under ZS Xplorer, driven through the vendor's .NET SDK on the instrument PC (Windows; SDK member names unverified and configurable). Pick it to measure the size distribution (Z-average, PDI, intensity peaks) or the zeta potential of a sample in a cuvette with a saved SOP per sample type, with the cell temperature and equilibration time settable. A person loads the cuvette. Not for writing SOPs, for the autotitrator, or for measurements without a SOP.
driver: driver.py:Zetasizer
sim: sim.py:SimZetasizer
---

# Zetasizer (ZS Xplorer SDK)

ZS Xplorer owns the optics, the SOPs and the measurement records. This package drives it through
its .NET SDK on the instrument PC: it loads a SOP, starts a measurement on a named sample, waits
for it, reads the headline numbers and exports the record. Member names of the SDK could not be
verified from public sources and sit in `config.json` (`sdk`) so they can be corrected without
code changes.

## Operating procedure

1. Read `connected`, `status` and `cell_temperature`.
2. A person loads the cuvette (size: DTS0012 or a low-volume cell; zeta: DTS1070 folded capillary)
   and closes the cell cover.
3. Write `temperature_setpoint` and `equilibration_s` if the SOP does not fix them; wait for
   `cell_temperature` to settle.
4. Find the SOP for the sample type: `methods/find` with the material and project; a saved method
   here is the SOP file name. Then `actions/invoke {name: measure_size, method: {name, project},
   params: {sample_name}}`, or `measure_zeta` with a zeta SOP.
5. The job lasts the measurement (two to five minutes); cancelling aborts. Read `z_average_nm`,
   `pdi` and `peaks`, or `zeta_mv`, `conductivity_ms_cm` and `quality`, and the export path.

## What to watch

- An attenuator of 11 means a very weak signal (dilute or small); 1-3 means dust, aggregates or a
  too-concentrated sample; look at the peaks before trusting the Z-average.
- PDI above 0.3: the cumulants fit is poor; report the peaks instead.
- Zeta in buffers above about 5 mS/cm needs the SOP's diffusion-barrier or low-voltage settings;
  a `quality` other than good says so.
- Open the cell cover only when `busy` is false; the instrument shutters the laser itself.

## Resources

- `references/setup.md`: ZS Xplorer SDK, pythonnet, SOP folder, first hardware test (Windows).
- `references/sdk.md`: what was found about the Zetasizer SDKs and every member name assumed here.
- `methods/`: one example SOP method (`_shared/mab_size_25c`); `methods/save` adds the lab's.
- `config.example.json`: SOP and export folders, SDK member names.
