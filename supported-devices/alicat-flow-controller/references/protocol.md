# Alicat ASCII serial protocol, as used by this package

Sources read: Alicat Scientific "Serial Communications Primer", Rev 2 (February 2023), https://documents.alicat.com/Alicat-Serial-Primer.pdf; "Operating Manual for Standard Flow and Pressure Devices, Models M, MC, P, PC, L, LC" (DOC-MANUAL-MPL), https://documents.alicat.com/manuals/DOC-MANUAL-MPL.pdf; "Operating Manual for Pressure Controllers" (DOC-MANUAL-PC, 2020); Alicat's online serial communication tutorial. Cross-checked against replies captured from real MC-500SCCM-D and MCR-200SLPM-D units published in the MIT-licensed `alicatlib` test fixtures and the MIT-licensed `numat/alicat` driver. The table is in our words.

## Link

| Item | Value |
|---|---|
| Physical | RS-232, RS-485 (multi-drop, up to 26 units) or USB virtual COM port |
| Serial | 19200 baud default (2400 to 115200 selectable), 8 data bits, no parity, 1 stop bit, no flow control |
| Command | `<unit id><command>` + CR; commands are case-insensitive; a space between command and value is optional (`AS 1.5` and `AS1.5`) |
| Reply | one line terminated CR (no LF observed in any capture; CR LF unverified) |
| Unit id | one letter A..Z, factory A; a device answers only commands bearing its own letter and stays silent otherwise |
| Modes | polling (factory): the device speaks only when asked. Streaming: unit id `@`, a frame every 50 ms by default without the leading letter; `@@=A` stops streaming and makes the device unit A. `A@=B` renames unit A to B (no reply). |

## The data frame (reply to `A` and to most set commands)

Space-separated fields, no units transmitted; `A??D*` prints the column list with units.

| Device | Columns |
|---|---|
| Mass flow controller (MC, MCR, MCS, ...) | unit id, absolute pressure (PSIA), temperature (degC), volumetric flow, mass flow, setpoint, [totalizer], gas, [status codes] |
| Mass flow meter (M, MW, ...) | as above without the setpoint |
| Pressure controller (PC, PCD, ...) | unit id, pressure, setpoint, [status codes] |
| Liquid controller (LC) | unit id, gauge pressure, temperature, volumetric flow, setpoint |

Example from a 10v20 MC-500SCCM-D: `A +014.62 +021.89 +000.00 +000.00 +078.95     N2`. The gas name is right-justified in a 6-character field. Numbers are signed fixed-width decimals whose width and precision depend on the device (`+014.70`, `+01.234`, `+0000.1`); older firmware prints the setpoint unsigned.

Status codes appended after the gas, in this order: `ADC` (internal ADC/communication error), `OPL` (overpressure limit), `POV`/`P2O` pressure over range, `TOV` temperature over range, `VOV`/`MOV` volumetric/mass flow over range (above about 128 % of full scale), `TMF` totalizer missed flow, `OVR` totalizer rollover, `COM` serial idle too long, `HLD` valve hold, `EXH` exhaust, `GTA` autotune in progress, `LCK` display locked.

## Commands this package uses (unit A; driver.py substitutes the configured letter)

| Command | Reply | Meaning |
|---|---|---|
| `A` | data frame | poll |
| `AS<x>` | data frame with the new setpoint | setpoint in the current engineering unit; `AS0` closes the valve. Negative values only on bidirectional units. |
| `AHC` | data frame with `HLD` | hold the valve(s) closed |
| `AC` | data frame without `HLD` | cancel hold, resume control |
| `AV` | data frame with flow zeroed | tare flow (no flow present!) |
| `AVE` | `A   10v20.0-R24 Jan  9 2025,15:04:07` | firmware version (older GP firmware: `A GP`) |

Not used but useful on a terminal: `A??D*` (data-frame description with units), `A??M*` (manufacturer info: model, serial number, calibration date), `A??G*` (gas list), `AGS<n>` / `AG<n>` (select gas by number: 0 Air, 1 Ar, 2 CH4, 3 CO, 4 CO2, 6 H2, 7 He, 8 N2, 11 O2, ...), `ALS` (query setpoint with its unit code), `AHP` (hold valve at its current position), `AE` (exhaust, dual-valve pressure controllers), `AP` / `APC` (tare gauge / absolute pressure), `AT` (reset totalizer), `AL` / `AU` (lock / unlock the display), `ASR` (setpoint ramp rate), `ADCU` (engineering units), `ANCB` (baud), `AW91=<ms>` (streaming interval), `A@=@` (start streaming), `@@=A` (stop streaming).

Failed or unknown commands answer `?` (some firmware prefixes it with the unit id or an empty line). Commands with another unit id, controller-only commands sent to a meter, and gas commands sent to a pressure device get no reply at all.

## Units

Mass flow is standard flow referenced to 25 degC and 14.696 psia (Alicat default; STP is configurable). Default units: SCCM on small devices, SLPM on larger ones, PSIA for absolute pressure, degC for temperature. This package declares L/min and [psi]; the setup note says what to change if the device reports otherwise.

## Parsing notes

`pressure` ... `setpoint_actual` are fields 1 to 5 of the frame by number position (the unit letter and the gas name carry no digits; a gas name such as `N2` comes after field 5 and does not disturb the count). `frame` is the raw line. The bare-number setpoint form `A<integer>` (0 to 64000 counts of full scale) is deliberately not used.

## Unverified

- Reply terminator: CR only in every capture and in Alicat's HyperTerminal advice; no Alicat document states it.
- Exact `?` error reply format per firmware version.
- Whether `AS` with a space (`AS 1.5`) and without (`AS1.5`) are both accepted on GP-era firmware (both are shown in Alicat documents for current firmware; this package sends `AS1.5`).
- The 128 % of full scale threshold for the `MOV` flag.
