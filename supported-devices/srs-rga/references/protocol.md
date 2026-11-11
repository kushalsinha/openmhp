# SRS RGA RS-232 command set, as used by this package

Sources read: Stanford Research Systems, "Operating Manual and Programming Reference, Models RGA100, RGA200 and RGA300 Residual Gas Analyzer", revision 1.9, chapter 6 "RGA Programming" (RS-232 interface, command syntax, command set, error byte definitions) and chapter 3 (ionizer, filament protection), https://www.thinksrs.com/downloads/pdfs/manuals/RGAm.pdf. Cross-checked against `srsinst.rga` (SRS's own Python package, MIT) and `pyrga` (MIT). The table is in our words.

## Link

| Item | Value |
|---|---|
| Serial | 28800 baud fixed, 8 data bits, no parity, 1 stop bit; RTS/CTS hardware handshake (CTS is the ECU's "ready" output, RTS throttles it). The connector is DCE: straight cable. |
| Command | two-letter mnemonic (case-insensitive) + parameter + CR. `?` queries, `*` sets the default. A lone LF is ignored, so CR LF is tolerated. 14 characters without a CR is a "command too long" error. |
| Reply | ASCII text terminated LF CR for everything except ion currents, which are 4-byte little-endian signed integers in 1e-16 A with no terminator. Hardware commands (`FL`, `EE`, `IE`, `VF`, `HV`, `IN`, `CA`, `CL`, `DG`) answer with the STATUS byte as decimal text when the action is complete. No character echo. |
| Scans | any command received during `SC`/`HS`/`DG` aborts it and flushes the transmit buffer. |

## Commands this package uses

| Command | Parameter | Reply | Meaning |
|---|---|---|---|
| `ID?` | | `SRSRGA200VER0.24SN12345` | model (100/200/300), firmware, serial |
| `FL<x>` / `FL?` | 0, or 0.02 to 3.50 mA | STATUS byte / actual emission | filament emission; 0 switches it off and grounds repeller and focus. STATUS arrives when emission is established. |
| `EE<n>` / `EE?` | 25 to 105 | STATUS / integer | electron energy, eV (default 70) |
| `IE<n>` / `IE?` | 0 or 1 | STATUS / 0 or 1 | ion energy 8 or 12 eV (default 1) |
| `VF<n>` / `VF?` | 0 to 150 | STATUS / integer | focus-plate bias magnitude, V (default 90) |
| `HV<n>` / `HV?` | 0, or 10 to 2490 | STATUS / integer | CDEM bias; 0 = Faraday cup. Bad-command error on heads without the option. |
| `NF?` | | integer 0..7 | noise floor / scan speed (the `NF<n>` set sends no reply; not used) |
| `MO?` | | 0 or 1 | multiplier option present |
| `IN0` | | STATUS | flush buffers, clear the communications error, re-run supply/electrometer/RF checks |
| `IN2` | | STATUS | IN0 + factory defaults + filament and CDEM off (standby) |
| `CA` | | STATUS, when done (up to 120 s) | calibrate all: rezero the detector, correct the RF scan parameters, RF off at the end |
| `ER?` | | integer | STATUS byte |
| `EF?` | | integer | FIL_ERR |
| `EC?` | | integer | RS232_ERR; reading clears it and STATUS bit 0 |

Not used (binary replies, no replies, or long waits): `MR<m>` single mass (4-byte current, `MR0` turns the RF off), `TP?` total pressure (4-byte current), `SC`/`HS` scans, `AP?`/`HP?` point counts, `MI`/`MF`/`SA`/`NF` sets (no reply), `DG<n>` degas (STATUS only at the end), `CL` electrometer calibration, `ED?`/`EP?`/`EQ?`/`EM?` (detailed error bytes), tuning commands.

## Status and error bytes

STATUS (`ER?`), 0 = no error: bit 0 communications (read `EC?`), bit 1 filament (`EF?`), bit 3 electron multiplier (`EM?`), bit 4 RF supply (`EQ?`), bit 5 electrometer (`ED?`), bit 6 24 V supply (`EP?`).

FIL_ERR (`EF?`): bit 0 single-filament operation, bit 5 chamber pressure too high, bit 6 unable to set the requested emission, bit 7 no filament detected. Set by the head's background filament protection, which shuts the filament (and the multiplier) off; cleared only by a later successful `FL`.

RS232_ERR (`EC?`): bit 0 bad command, bit 1 bad parameter, bit 2 command too long, bit 3 receive overflow, bit 4 transmit overflow, bit 5 jumper-protected parameter, bit 6 parameter conflict.

## Pressure limits

Maximum operating pressure 1e-4 Torr for the filament; the multiplier should not be biased above about 5e-6 Torr. The head has no pressure gauge: the protection acts on emission regulation after the fact. This package therefore asks a person to confirm every filament or multiplier switch-on.

## Parsing notes

`filament_ok` is `EF?` mapped through a boolean table: `0` is true, every combination of bits 0, 5, 6 and 7 is false. Replies end in LF CR; pyserial's `readline` stops at the LF, and the trailing CR is stripped as the prefix of the next reply.

## Unverified

- Exact digit format of `FL?`, `EE?` and similar replies (the manual gives no examples; the driver parses the first number).
- Whether `ER?`/`EF?` replies end in LF only (the manual says LF for those two, LF CR everywhere else); harmless either way.
- Operation without pyserial `rtscts`: both open-source drivers enable it; the short replies here should not fill the ECU's buffer, but this is not demonstrated on hardware.
- The HV upper limit: manual 2490 V, `srsinst.rga` caps at 2290; this package caps at 2000.
