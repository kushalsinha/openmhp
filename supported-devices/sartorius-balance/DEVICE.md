---
mhp: "2026-09-12"
id: sartorius-balance-01
class: balance
make: Sartorius
model: SBI balances (Entris II, Secura, Quintix, Practum, Cubis, Cubis II in SBI mode)
location: ""
tags: [weighing, balance, pharma, serial, sbi]
description: Sartorius laboratory balance driven over RS-232 or USB with the SBI (Sartorius Balance Interface) command set (ESC P print, ESC T tare, ESC V zero, ESC x1_ model). Reads the mass from a print frame, tares, zeros, locks and unlocks the keys. Use for weighing on any Sartorius balance set to SBI mode, from Entris II to Cubis II; it does not run adjustment unless the balance has an internal weight (ESC Z).
driver: driver.py:Device
sim: sim.py:Sim
---

# Sartorius balance (SBI)

Any Sartorius balance whose interface is set to SBI mode: a command is the ESC character followed by
one letter (`ESC P` prints the weight, `ESC T` tares) or by `x<n>_` for identity queries. The balance
answers a print command with a fixed 16- or 22-character frame; control commands get no answer. Put the
port under `port` in `config.json` (see `references/setup.md`). The balance must be in SBI mode with a
framing the driver can open (8 data bits, no parity); see the setup note, the factory setting is 7 bits odd parity.

## Operating procedure

1. Read `model` and `serial_number` to confirm the link and the balance.
2. Place the empty container, invoke `tare`, then read `mass` (expect 0).
3. Add the sample and read `mass`. The print command answers at once; if the reading has not settled the
   frame carries no unit (see `mass_frame`), so read `mass_frame` and check the unit is there before trusting
   `mass`, or read again after a second.
4. Invoke `zero` between series with the pan empty.
5. `lock_keys` while a sequence runs so nobody tares by hand; `unlock_keys` after.

## What to watch

- `mass` is parsed from the print frame: sign, value, unit. The value is in the balance's display unit (grams
  unless changed on the balance); `mass_frame` is the raw frame for checking the unit and stability.
- The balance prints only one frame per `ESC P`; if "auto print" is enabled in the balance menu the port fills
  with unsolicited frames and `ESC P` toggles that instead of printing once. Keep auto print off.
- The balance has nothing to stop: `safety.estop` is false and a silent controller merely loses its lease.
- Calibration: no SBI command reports the last adjustment, so `calibration_status` comes from the lab's record.
  `internal_adjustment` (ESC Z) needs an internal weight and a person's confirmation.

## Resources

- `references/setup.md`: cable, port, balance menu settings, framing, first hardware test.
- `references/sbi.md`: the SBI commands and frame format this package uses, from the Sartorius interface note.
