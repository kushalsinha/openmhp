# SCPI commands used by the bench-power-supply package

Source: Rigol DP800 Series Programmable Linear DC Power Supply Programming Guide, document
PG-DP800 (Rigol Technologies; chapter 2 "Command system": `:MEASure`, `:OUTPut`, `:SOURce`,
`:INSTrument`, `:SYSTem`), cross-checked against the command names in pymeasure's
MIT-licensed `RigolDP832` driver. Commands end with LF; queries answer one line; writes answer
nothing; errors go to the queue.

| Command | Used for | Meaning |
|---|---|---|
| `*IDN?` | probe | `RIGOL TECHNOLOGIES,DP832,<serial>,<firmware>` |
| `:INST:NSEL <n>` | (not used) | select the current channel for commands that take none; the package addresses channels explicitly instead |
| `:SOUR<n>:VOLT <v>` | `voltage_setpoint_chN`, `configure_ch1` | voltage setpoint of channel n |
| `:SOUR<n>:CURR <i>` | `current_limit_chN`, `configure_ch1` | current limit of channel n |
| `:MEAS:VOLT? CH<n>` | `voltage_chN` | measured voltage |
| `:MEAS:CURR? CH<n>` | `current_chN` | measured current |
| `:MEAS:POWE? CH<n>` | `power_chN` | measured power |
| `:OUTP CH<n>,ON\|OFF` | `enable_chN`, `disable_chN`, `all_off`, estop | output enable |
| `:OUTP? CH<n>` | `output_chN` | answers `ON` or `OFF` |
| `:OUTP:OVP CH<n>,ON\|OFF` | `enable_chN` | over-voltage protection enable |
| `:OUTP:OVP:VAL CH<n>,<v>` | `ovp_chN` | over-voltage protection value |
| `:OUTP:OCP CH<n>,ON\|OFF` | `enable_chN` | over-current protection enable |
| `:OUTP:OCP:VAL CH<n>,<i>` | `ocp_chN` | over-current protection value |
| `:SYST:ERR?` | `last_error` | oldest error, `0,"No error"` when empty |

Channel ratings (user guide): DP832 CH1/CH2 0-30 V, 0-3 A, CH3 0-5 V, 0-3 A; OVP 0.01-33 V
(CH3 0.01-5.5 V), OCP 0.001-3.3 A. DP831: 8 V/5 A, 30 V/2 A, -30 V/2 A. DP821: 60 V/1 A, 8 V/10 A.
DP811: 20 V/10 A or 40 V/5 A (one channel). Programming resolution 10 mV / 10 mA on the DP832,
1 mV / 1 mA on the DP832A; the descriptor uses the coarser grid.

Unverified (not checked on an instrument):

- Whether `:OUTP CH1,1` would be accepted as well as `ON` (the guide lists only `ON|OFF`, which
  is why the output enable is an action rather than a boolean setting).
- The exact error text the DP800 reports for a protection trip (the twin invents
  `-224,"Protection tripped"`; the guide lists the SCPI standard codes only).
- `:MEAS:POWE?` as the power query (the guide spells it `:MEASure:POWEr?`; the four-letter
  short form is `POWE`).
