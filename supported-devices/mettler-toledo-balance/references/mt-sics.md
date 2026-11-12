# MT-SICS commands used by this package

Source: METTLER TOLEDO "MT-SICS Reference Manual for Excellence Balances" (Standard Interface Command
Set for XP/XS/XA balances), document 11780711, revision D (the PDF named Excellence-SICS-BA-en-11780711D
on mt.com). Level 0 and 1 commands are common to every MT-SICS balance; level 2 commands (C3) depend on
the model.

Serial (manual, `COM` command): factory setting 9600 baud, 8 data bits, no parity, 1 stop bit, no
handshake; commands and replies end with CR LF. A reply with a weight value is `<ID> <Status>
<WeightValue> <Unit>`: the status is `S` (stable) or `D` (dynamic), the value is right-aligned in 10
characters with a minus sign directly before the first digit, the unit is the host unit. The numeric
parser here takes the first number on the line, so the status letters do not disturb it.

| Command | Level | Meaning (manual) | Reply | Used as |
|---|---|---|---|---|
| `S` | 0 | send the next stable net weight | `S S <value> <unit>`; `S I` timeout/busy; `S +` overload; `S -` underload | signal `mass_stable` |
| `SI` | 0 | send the current weight at once | `S S` or `S D <value> <unit>`; `S I`, `S +`, `S -` | signal `mass_immediate` |
| `SIR` | 0 | send weights continuously | repeated `S S`/`S D` lines until S, SI, SR or @ | not used (the driver reads one line per command) |
| `T` | 1 | tare on the next stable weight | `T S <tare> <unit>`; `T I`; `T +`; `T -` | action `tare` |
| `TA` | 1 | query the tare memory | `TA A <tare> <unit>` | signal `tare_value` |
| `TA <value> <unit>` | 1 | preset a tare value | `TA A <tare> <unit>`; `TA L` bad parameter | setting `tare_preset` |
| `TAC` | 1 | clear the tare memory | `TAC A` | action `clear_tare` |
| `Z` | 0 | zero (tare memory cleared too) | `Z A`; `Z I`; `Z +`; `Z -` | action `zero` |
| `@` | 0 | cancel and restart as after power-on, no zeroing | `I4 A "<serial>"` | action `reset` |
| `I2` | 0 | balance type and capacity | `I2 A "<type> <capacity> <unit>"` | signal `balance_data` |
| `I3` | 0 | software version and type definition number | `I3 A "<version> <tdnr>"` | signal `software_version` |
| `I4` | 0 | serial number | `I4 A "<serial>"` | signal `serial_number` |
| `D "<text>"` | 1 | write text to the display | `D A`; `D I`; `D L` | action `display_text` |
| `DW` | 1 | show the weight on the display again | `DW A` | action `show_weight` |
| `C3` | 2 | start internal adjustment | `C3 B` started, then `C3 A` done or `C3 I` aborted; `C3 L` no internal weight | action `internal_adjustment` |
| `C2` | 2 | start external adjustment (prompts to load the weight) | `C2 B`, `C2 "<weight>"` prompts, `C2 A` | not used: needs a person at the balance |
| `I1` | 0 | MT-SICS level and versions | `I1 A "<levels>" ...` | not used |

Error replies (manual): `ES` syntax error, `ET` transmission error (framing or parity), `EL` logical
error (cannot execute). They carry no number, so a read that gets one fails with a message.

Calibration status: no level 0 or 1 command reports the date or result of the last adjustment. `M27`
(adjustment history) is level 2 and Excellence-only, so this package keeps `calibration_status` on the
lab's record. Unverified: `TA <value> g` is written with a space between value and unit as in the
manual's syntax line; the example prints `TA100.00g` without spaces. Both are stated as accepted
(spaces are not significant in MT-SICS commands); check on hardware.
