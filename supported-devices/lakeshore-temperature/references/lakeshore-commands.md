# Lake Shore commands used by the lakeshore-temperature package

Sources: Lake Shore Model 335 Temperature Controller User's Manual (P/N 119-050, chapter 6
"Computer interface operation", 6.6 "Command summary") and Model 336 User's Manual (P/N
119-064, same chapter), cross-checked against the command names in Lake Shore's own
`lakeshore` Python package (MIT) and pymeasure's `LakeShore335/336` classes. The 350 shares
the command set. Commands end with CR LF; queries answer one line; commands answer nothing.

| Command | Used for | Meaning |
|---|---|---|
| `*IDN?` | probe | `LSCI,MODEL335,<serial>,<firmware>` |
| `KRDG? <input>` | `temperature_a`, `temperature_b` | kelvin reading of input A/B (C/D on 336/350); 0 when the input is off or the sensor is faulted |
| `CRDG? <input>` | (reference only) | the same reading in Celsius; not used, cryo users think in kelvin |
| `SETP? <output>` / `SETP <output>,<value>` | `setpoint_1_actual`, `setpoint_1`, `go_to_temperature` | control setpoint in the output's preferred units (kelvin here) |
| `RANGE? <output>` / `RANGE <output>,<range>` | `heater_range_1`, `heaters_off`, estop | heater range: 0 off, 1 low, 2 medium, 3 high on outputs 1 and 2; outputs 3 and 4 of the 336 use 0/1 |
| `HTR? <output>` | `heater_output_1` | heater output in percent of the selected range |
| `RAMP? <output>` / `RAMP <output>,<on>,<rate>` | `ramp_enabled_1`, `ramp_rate_1_actual`, `ramp_rate_1`, `set_ramp_1` | setpoint ramp on/off and rate, 0.1 to 100 K/min |
| `OUTMODE? <output>` | `output_mode_1` | `mode,input,powerup`: 0 off, 1 closed loop PID, 2 zone, 3 open loop (4/5 monitor out, warmup on the 336) |

Not used but worth knowing: `HTRSET` (heater resistance and max current, the lab's), `PID`,
`ZONE`, `INTYPE`, `INCRV` (input configuration, a person's job), `TUNEST?` (autotune status).

Interfaces, from the manuals: Ethernet TCP port 7777 (336/350); GPIB default address 12; USB
virtual COM port 57600 baud, 7 data bits, odd parity, 1 stop bit (all three).

Unverified (not checked on an instrument):

- Line terminator on the Ethernet port: the package sends CR LF, which the manuals list for
  serial and GPIB; the socket link also accepts replies ending in LF alone.
- Whether `RANGE 2,<n>` on a 335 with output 2 configured as an analog voltage output is
  accepted or ignored; the package sends it in `heaters_off` and the e-stop regardless, since
  an ignored command does no harm.
- The exact power-on `RAMP` rate; the twin assumes 1.0 K/min, ramping off.
