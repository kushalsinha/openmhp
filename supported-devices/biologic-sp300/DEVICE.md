---
mhp: "2026-09-12"
id: biologic-sp300-01
class: potentiostat
make: BioLogic
model: SP-300
location: ""
tags: [electrochemistry, potentiostat, galvanostat, co2rr, pulsed-electrolysis]
description: BioLogic SP-300 potentiostat/galvanostat wired to a three-electrode electrochemical cell. Pick it to run static or pulsed constant-current electrolysis (alternating a reduction and an oxidation current, as in pulsed CO2 reduction), cyclic voltammetry, or an open-circuit reading, and to get back the potential-time trace. Not for impedance yet, and it cannot tell whether electrolyte is flowing, so establish flow first.
driver: driver.py:SP300
sim: sim.py:SimSP300
---

# BioLogic SP-300

Connected to the bench PC by USB or Ethernet. Potentials reported
here are versus the cell's reference electrode, uncorrected. Currents are in mA (total, not per cm2): multiply the
current density you want by the electrode area before calling.

## Operating procedure

1. Read `connected`. Confirm from the pressure controller that electrolyte is flowing through
   the cell; never apply current to a dry or stagnant cell.
2. Optional: invoke `ocv` for 30-60 s to check the cell is wired and wetted (a stable potential).
3. Optional: invoke `cv` before and after electrolysis to see the Cu oxidation-state peaks.
4. Invoke `cp_pulsed` (reduction and oxidation currents, their durations, total time) or
   `cp_static`. These are long jobs: poll the job, or subscribe to the `live` signal, which is
   pushed every few seconds with the latest potential, current and per-phase averages.
5. Read the job result (or `last_result`): mean potential in each phase, charge passed, and the
   path of the CSV trace on the bench PC.
6. To stop early, cancel the job; the channel is stopped and the data so far is kept.

## What to watch

- `live.ewe_V` drifting more negative at the same current means the cathode is losing activity
  or CO2 is depleted. The driver aborts the run if the potential leaves the safe window.
- A job that fails leaves the device in fault; read `last_result` and `connected` before a reset.
- Oxidation current that is too high or too long dissolves the copper catalyst.
- Emergency stop opens the cell (stops the channel) immediately.

## Resources

- `references/setup.md`: installation on the bench PC and config.json.
- `config.example.json`: instrument address, channel, safe potential window, data folder.
