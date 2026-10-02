---
mhp: "2026-09-12"
id: sri-8610c-gc-01
class: gas_chromatograph
make: SRI Instruments
model: 8610C (PeakSimple)
location: ""
tags: [gc, gas-analysis, co2rr, products, hydrogen, ethylene]
description: SRI 8610C gas chromatograph with a gas sampling valve on the electrolysis cell's gas outlet, run through PeakSimple. Pick it to quantify gas products of CO2 reduction (H2, CO, CH4, C2H4) by injecting the current gas stream with a saved PeakSimple method and getting back the peak table. It does not see liquid products (ethanol, formate), and its oven, detector and valve timing live in the method file and cannot be changed from here.
driver: driver.py:SRI8610C
sim: sim.py:SimSRI8610C
---

# SRI 8610C gas chromatograph

USB to the bench PC, with PeakSimple running. The cell's gas outlet
flows continuously through the sample loop; starting a run fires the gas sampling valve as
programmed in the PeakSimple control file (the method), so a run always analyses the gas that is
in the loop at that moment.

## Operating procedure

1. Read `connected` (PeakSimple is running and answering) and `running` (false before a new run).
2. Find the method: `mhp_method op='find'` with the project. A method here is a PeakSimple
   control file name (run time is read from the file). If there is none, ask the person for both and save it.
3. Electrolysis must have been running long enough for the gas line to reach steady state
   (typically 10 minutes or more) before the injection means anything.
4. Invoke `run_method`. The job lasts the method's run time; then the driver reads the newest
   result file PeakSimple wrote and returns the peak table.
5. Read the job result or `last_result`: component, retention time, area and, if the method is
   calibrated, concentration.

## What to watch

- A result with no peaks, or no result file, usually means the method does not save results
  after the run (PeakSimple post-run actions), or carrier gas is off. Tell a person.
- Wait for one run to finish before the next; the device is busy until then.
- Emergency stop ends data acquisition only. Heaters and gases stay as they are; a person makes
  the GC safe at the instrument.

## Resources

- `references/setup.md`: installation on the bench PC, config.json and what must be set in PeakSimple.
- `config.example.json`: connector path, method and result folders, channel.
