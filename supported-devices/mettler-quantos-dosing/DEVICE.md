---
mhp: "2026-09-12"
id: mettler-quantos-dosing-01
class: dispenser
make: Mettler Toledo
model: Quantos QB1 / QS30 and XPR automatic powder dosing (XPR/XSR balance with a dosing module) over MT-SICS
location: ""
tags: [powder-dosing, dispenser, balance, mt-sics, serial, template]
description: Mettler Toledo automatic powder dosing heads (Quantos QB1/QS30 modules and the XPR automated powder dosing option) driven over the balance's RS-232 or USB port with MT-SICS, written as a TEMPLATE. The balance commands (S, SI, T, Z, A10 target and tolerance, I2/I3/I4, C3, @) come from Mettler's MT-SICS reference manual for XPR/XSR balances and are verified; the dosing-head commands (start a dose, read the result, head information) are not in any public document and are placeholders marked unverified. Pick it to weigh out a target mass of powder into a tared vial with a tolerance and get the dispensed mass back; not for liquids and not for manual dosing heads.
driver: driver.py:Device
sim: sim.py:Sim
---

# Mettler Toledo Quantos / XPR powder dosing (MT-SICS template)

An analytical balance with a motorised powder dosing head: the host sets a target mass and
tolerances with the balance's `A10` command, starts the dosing head, and reads back the mass the
head actually dispensed. The balance half of that is MT-SICS level 0/1 plus `A10`, documented in
Mettler's reference manual for XPR/XSR balances and shared with the balance package in this
repository. The dosing half (start, result, head data) is handled by Quantos through LabX or
through commands Mettler supplies on request ("if you need to control your instrument via
external commands, contact Mettler Toledo", the Quantos operating instructions say); no public
document lists them, so the three dosing commands in `descriptor.yaml` are **placeholders**
marked unverified in `references/mt-sics.md`. Everything else behaves as on an XPR balance.

## Operating procedure

1. Read `serial_number`, `balance_data` and `head_present`; the head must be mounted and its
   RFID read before a dose can start.
2. Place the tared vial on the pan (or let the sample changer do it), invoke `tare` and wait for
   `T S`.
3. Invoke `dose {target_mg: 25, tolerance_pct: 2}`. The driver writes the target and both
   tolerances with `A10`, starts the head and polls the result; the job's `returns` carries the
   replies and `dispensed_mg` parsed from the last one. A dose of a few tens of milligrams takes
   10-60 s depending on the powder's flow.
4. Read `mass_stable` to confirm the net mass on the pan, and `last_dose_result` for the
   head's own report.
5. Between powders, change the head (a person) and read `head_present` again. Invoke `zero` with
   an empty pan between series.

## What to watch

- The balance speaks in its host unit; `A10` is sent in mg here, which the XPR accepts as a
  unit string. If `A10 L` comes back the balance's tolerance profile refuses the decimals: set
  `resolution` on `target_mg` to what your model allows.
- `S I`, `S +`, `S -` replies carry no number and are reported as failed reads.
- The placeholders: a `QD` reply of `ES` means the balance does not know the command, which is
  expected until the dosing command set from Mettler is written into `descriptor.yaml`.
- Nothing here heats or moves fast: e-stop sends `@` (abort every pending command), which stops a
  running dose and restarts the balance software without zeroing.
- Calibration: the XPR has no public command that reports the date of its last adjustment, so
  `calibration_status` is the lab's record; `internal_adjustment` (C3) runs one on request.

## Resources

- `references/mt-sics.md`: the verified MT-SICS commands and the placeholder dosing commands, with the source document.
- `references/setup.md`: cable, port, balance interface settings, first hardware test, status.
