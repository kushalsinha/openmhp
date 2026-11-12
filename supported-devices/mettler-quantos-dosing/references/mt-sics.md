# MT-SICS commands used by this package

Source for the balance commands: METTLER TOLEDO, *Reference Manual: MT-SICS Interface Commands for XPR
and XSR Balances* (mt.com, library of user manuals; the PDF named Reference_Manual_MT-SICS-XPR_EN),
sections 2 (command formats, error messages) and 3 (commands and responses). Level 0/1 commands are
the same as in the balance package (supported-devices/mettler-toledo-balance, written from the
Excellence manual 11780711 D).

Frame: ASCII, parameters separated by spaces, CR LF terminated; the factory interface setting is 9600
baud, 8 data bits, no parity, 1 stop bit. A reply with a weight is `<ID> <Status> <Value> <Unit>` with
status S (stable) or D (dynamic). Command-specific errors are `<ID> +` overload, `<ID> -` underload,
`<ID> L` logical error (parameter not allowed), `<ID> I` internal error (not ready); general errors
are `ES` syntax, `ET` transmission, `EL` logical.

## Verified (from the XPR/XSR manual)

| Command | Meaning | Reply | Used as |
|---|---|---|---|
| `S` | next stable weight | `S S <value> <unit>`; `S I`, `S +`, `S -` | signal `mass_stable` |
| `SI` | weight immediately | `S S` or `S D <value> <unit>` | signal `mass_immediate` |
| `T` | tare on next stable weight | `T S <tare> <unit>`; `T I` | action `tare` |
| `TA` | query the tare memory | `TA A <tare> <unit>` | signal `tare_value` |
| `TAC` | clear the tare memory | `TAC A` | action `clear_tare` |
| `Z` | zero | `Z A`; `Z I` | action `zero` |
| `@` | abort every pending command, restart without zeroing | `I4 A "<serial>"` | action `reset`, e-stop |
| `I2` | device data (type and capacity) | `I2 A "<type> <capacity> <unit>"` | signal `balance_data` |
| `I3` | software version and type definition number | `I3 A "<version> <tdnr>"` | signal `software_version` |
| `I4` | serial number | `I4 A "<serial>"` | signal `serial_number` |
| `C3` | start adjustment with the built-in weight | `C3 B` then `C3 A`; `C3 I`; `C3 L` | action `internal_adjustment` |
| `A10 <No> <Value> <Unit>` | set target weight (No 0), + tolerance (1), - tolerance (2); unit g, mg, or % for tolerances | `A10 A`; `A10 L` too many decimals or bad parameter; `A10 I` not now | settings `target_mass`, `tolerance_plus`, `tolerance_minus`; the first three commands of `dose` |
| `A10` (query) | target and tolerances | three lines `A10 B 0 <value> <unit>`, `A10 B 1 ...`, `A10 A 2 ...` | not used: the driver reads one line per command and the other two would desynchronise the port |
| `C0` | adjustment setting (query/set) | per manual | not used: it reports the configured adjustment mode, not the last adjustment's date or result |
| `I0` | list of implemented commands | one line per command | not used here; send it by hand to learn whether your balance knows a dosing command |

Unverified detail: `A10 0 <value> mg` is sent with the unit `mg`; the manual's examples use `g` and
`%` and say the unit depends on the balance's tolerance profile. If the balance answers `A10 L`,
change the unit to `g` in descriptor.yaml and divide `target_mg` by 1000 in the command (or set the
profile to mg at the balance).

## Placeholders (not in any public document)

| Command | Intended meaning | Twin reply | Status |
|---|---|---|---|
| `QDS` | start the dosing head toward the A10 target | `QDS B` started, `QDS L` no head or no target | **unverified placeholder** |
| `QDR` | read the result of the last dose | `QDR A <mass> mg OK|OUT`; `QDR I` still dosing; `QDR L` none | **unverified placeholder** |
| `QDH` | dosing head present and its RFID data | `QDH A 1 "<substance>" "<lot>" <doses left>` or `QDH A 0` | **unverified placeholder** |

The Quantos operating instructions (11781172K, May 2013) state that control via external commands
is arranged with Mettler Toledo on request, and the XPR/XSR manual lists no dosing command; LabX is
Mettler's own route. Replace the three placeholders with the commands Mettler supplies and keep the
reply shapes the driver parses (`QDR A <number>` for the dispensed mass).
