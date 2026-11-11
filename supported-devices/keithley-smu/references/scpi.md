# SCPI commands used by the keithley-smu package

Source: Keithley Model 2400 Series SourceMeter User's Manual, document 2400S-900-01 (Rev. K,
Keithley Instruments / Tektronix), sections 17 (SCPI command reference) and 18 (SCPI command
summary); cross-checked against the command names in pymeasure's MIT-licensed `Keithley2400`
driver. Commands are sent with a trailing LF; the instrument answers queries with a line and
answers nothing to writes.

| Command | Used for | Meaning |
|---|---|---|
| `*IDN?` | probe | identification; contains "KEITHLEY INSTRUMENTS" |
| `*RST`, `*CLS` | `reset` | power-on defaults (output off); clear status and error queue |
| `:SOUR:FUNC VOLT\|CURR` / `?` | `source_function` | select the source function |
| `:SOUR:VOLT:MODE FIX`, `:SOUR:CURR:MODE FIX` | `source_voltage`, `source_current` | fixed (not sweep) source mode |
| `:SOUR:VOLT <v>` / `?` | `voltage_setpoint` | programmed source voltage |
| `:SOUR:CURR <i>` / `?` | `current_setpoint` | programmed source current |
| `:SENS:CURR:PROT <i>` / `?` | `compliance_current` | current compliance (sourcing voltage) |
| `:SENS:VOLT:PROT <v>` / `?` | `compliance_voltage` | voltage compliance (sourcing current) |
| `:OUTP ON\|OFF\|1\|0` / `:OUTP?` | `output_on` | source output enable; query answers 0 or 1 |
| `:READ?` | `measure` | trigger and fetch one reading with the current configuration; error +803 with the output off |
| `:FETC?` | `voltage`, `current` | the most recent reading, no trigger, no change to the output |
| `:MEAS:VOLT?`, `:MEAS:CURR?` | (not used) | :ABORt, :CONFigure, :READ? in one; the :CONFigure step can turn the source on, so a read signal must not use it |
| `:SYST:BEEP:STAT ON\|OFF` | `beeper_on` | front-panel beeper |
| `:SYST:ERR?` | `last_error` | oldest error-queue entry, `0,"No error"` when empty |
| `:ABOR` | estop | abort a triggered measurement, trigger model to idle |

Reading format: with the default `:FORM:ELEM VOLT,CURR,RES,TIME,STAT` a reading is five
comma-separated numbers, `voltage,current,resistance,time,status`; `9.91E+37` stands for a
quantity that is not being measured. The package takes field 1 for `voltage` and field 2 for
`current`. The status word is a bit field; bit 14 (16384) flags compliance.

Ranges (manual, specifications): 2400/2401 source ±210 V, ±1.05 A; 2410 ±1100 V, ±1.05 A;
2420 ±63 V, ±3.15 A. The descriptor ships ±20 V and ±0.1 A as placeholders.

Unverified (not checked on an instrument):

- Whether `:MEAS:VOLT?` / `:MEAS:CURR?` with the output off turn the source on (the manual's
  description of `:MEAS?` includes `:CONFigure`) or answer error +803 as `:READ?` does. The
  package avoids them for that reason; the twin models them as turning the output on.
- What `:FETC?` answers before any reading has been taken since power-on (the twin answers a
  zero reading; the instrument may answer an error, which would block `safety/reset` until a
  person takes one reading). Whether `:ABOR` or `:OUTP OFF` clears the last reading.
- Whether `:OUTP?` answers `0`/`1` or `OFF`/`ON` on every firmware; the boolean map accepts both.
- RS-232 terminator: the generic route sends LF and reads to LF; the manual's TERMINATOR menu
  default is `<CR+LF>` on some firmware, which also parses.
