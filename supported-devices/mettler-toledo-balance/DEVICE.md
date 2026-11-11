---
mhp: "2026-09-12"
id: mettler-toledo-balance-01
class: balance
make: Mettler Toledo
model: MT-SICS balances (Excellence XP/XS/XA, XPR/XSR, MS, ML and others)
location: ""
tags: [weighing, balance, pharma, serial, mt-sics]
description: Mettler Toledo laboratory balance driven over RS-232 or USB with the MT-SICS level 0/1 command set (S, SI, T, Z, @, I2, I4, D). Reads the stable and the immediate mass in the balance's host unit, tares, zeros, presets a tare and writes a line to the display. Use for weighing on any MT-SICS balance from a microbalance to a precision balance; it does not run adjustment unless the balance supports the level 2 C3 command.
driver: driver.py:Device
sim: sim.py:Sim
---

# Mettler Toledo balance (MT-SICS)

Any Mettler Toledo balance that speaks MT-SICS: the balance answers `S` with the next stable weight,
`SI` with the current one, `T` tares, `Z` zeros. Put the port under `port` in `config.json` (see
`references/setup.md`). Nothing needs to be enabled on the balance beyond its interface being set to
`Host` at 9600 baud, 8 data bits, no parity (the factory setting).

## Operating procedure

1. Read `serial_number` and `balance_data` to confirm the link and that the port answers the balance you expect.
2. Place the empty container, invoke `tare`. The balance waits for stability and answers with the tare value.
3. Add the sample and read `mass_stable`. The read blocks until the balance reports stability (a few
   seconds; it fails with a message if the balance times out, in which case close the draft shield and read again).
4. For a quick, possibly unstable value read `mass_immediate`.
5. Invoke `zero` between series, with the pan empty, so the tare memory is cleared too.

## What to watch

- `mass_stable` and `mass_immediate` are in the balance's host unit, grams on every balance this package was
  written for; the reply carries the unit and the sim answers `g`. Check `balance_data` (type and capacity) once.
- `S I`, `S +` and `S -` replies (not executable, overload, underload) carry no number and are reported as a
  failed read, not as a value.
- The balance has nothing to stop: `safety.estop` is false and a silent controller merely loses its lease.
- Calibration: MT-SICS level 0/1 has no query for the last adjustment, so `calibration_status` comes from the
  lab's record. `internal_adjustment` (C3) exists on balances with a built-in weight and needs a person's confirmation.

## Resources

- `references/setup.md`: cable, port, balance interface settings, first hardware test.
- `references/mt-sics.md`: the MT-SICS commands and reply formats this package uses, from the reference manual.
