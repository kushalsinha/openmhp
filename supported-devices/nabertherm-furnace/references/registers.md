# Register reference: Nabertherm series 400/500 controllers, Modbus TCP

Source: Nabertherm GmbH, *Operating Instructions: Communication Module for Nabertherm Series 400/500
Controllers, Communication to superordinate systems via Modbus TCP*, document M03.0021 English,
revision 2024-11 (nabertherm.com, downloads). Sections 7.3 (read access), 8 (program start and
segment jump), 8.3 (program input), 8.6 (setpoint control). Applies to B400/B410, C440/C450,
P470/P480 from firmware 1.51 and to the series 500 (B500/B510, C540/C550, P570/P580).

Transport: Modbus TCP, port 502, holding registers only (function 03 to read, 16 "multiple
register" to write; the manual's PLC example uses 06 for single writes). Addresses below are the
manual's decimal "slave register" numbers (0-based, as pymodbus sends them; a PLC that shows
4xxxx numbers adds 40001). Temperatures are in tenths of a degree in the controller's unit, so
the package scales by 0.1 and assumes Celsius (register 151 = 0).

## Read (section 7.3)

| Signal | Register | Type | Scale | Meaning | Verified |
|---|---|---|---|---|---|
| temperature | 100 | int16 | 0.1 | active actual value of the control zone | from the manual |
| charge_temperature | 101 | int16 | 0.1 | charge thermocouple | from the manual |
| (zones) | 102-110 | int16 | 0.1 | cooling zone, zones 1-4, documentation zones 1-4; not declared | from the manual |
| temperature_setpoint | 111 | int16 | 0.1 | program setpoint | from the manual |
| (setpoints) | 113-118 | int16 | 0.1 | charge, cooling TC, zone 1-4 setpoints; not declared | from the manual |
| output_power | 119 | uint16 | 0.1 | control-zone output, % | from the manual |
| (powers) | 120-124 | uint16 | 0.1 | cooling power, zone 1-4 power; not declared | from the manual |
| status_code | 125 | uint16 | 1 | 0 off, 1 wait, 2 run, 3 pause, 4 end, 5 autotune, 6 error, 7 external setpoint | from the manual |
| program_number | 126 | uint16 | 1 | loaded/running program; 51 = transferred over Modbus | from the manual |
| segment | 127 | uint16 | 1 | active segment 1-39 | from the manual |
| program_time_remaining | 128+129 | uint32 (128 low word) | 1 | remaining program time; **unit not stated in the manual, minutes assumed: unverified** | address verified |
| (extra relay) | 130 | uint16 | | bit array; not declared | from the manual |
| alarm1_active, alarm2_active | 131, 132 | uint16 | | alarm status words, non-zero = active (bit meaning per furnace) | from the manual |
| warnings_code | 133+134 | uint32 (133 low) | | warning bit array | from the manual |
| malfunction_code | 135 | uint16 | | current malfunction | from the manual |
| controller_type_code | 136 | uint16 | | 0 B400 ... 11 P580 (table in descriptor) | from the manual |
| max_temperature | 137 | int16 | 0.1 | furnace maximum | from the manual |
| serial_number | 138-147 | ASCII, 10 registers | | controller serial number | from the manual |
| temperature_unit_code | 151 | uint16 | | 0 C, 1 F | from the manual |
| program_transferred | 404 | uint16 | | 1 once a transferred program was accepted | from the manual |

`program_running` is not a register: the driver answers it as `status_code == 2`.

## Write: program commands (section 8)

| Register | Values | Used by | Verified |
|---|---|---|---|
| 148 controller command | 1 start, 2 stop, 3 pause; reset to 0 after the controller reacted | run_program, pause_program, stop_program, estop | from the manual (sample process 8.1) |
| 149 select and load program | 1-50 | run_program {program} | from the manual |
| 150 segment jump | -40..40, reset to 0 | segment_jump | from the manual (8.2) |

## Write: program transfer (section 8.3, P-controllers only)

| Registers | Meaning | Used as |
|---|---|---|
| 200-238 | target temperature of segment 1-39, whole degrees | target_c |
| 240-278 | time (min) or rate (degC/h) of segment 1-39 | dwell_min, or ramp_c_per_min * 60 with the rate flag |
| 280-318 | extra functions per segment, bit array | not written (0) |
| 320-358 | holdback value per segment | written 0 |
| 360-398 | flags per segment: bit 0 controlled cooling, bit 1 rate instead of time | bit 1 on ramp segments with a rate |
| 400 | start temperature | written 0 |
| 401 | program flags (repeat, Fahrenheit, holdback, charge control) | written 0 |
| 402 | number of segments, 1-40 (39 on these controllers) | len of the unrolled rows |
| 403 | release write command, 1 then back to 0 | the transfer handshake |
| 404 | program transferred completely (read) | waited for, 20 s |

Each typed segment `{target_c, ramp_c_per_min, dwell_min}` becomes a rate-ramp row (flag bit 1,
rate in degC/h) and, when dwell_min > 0, a time row at the same target. A ramp of 0 is written as
time 0 with no rate flag, which the manual's example uses for "cool as fast as possible". The
manual states the controller does not check plausibility, so the descriptor bounds every value.
Transfer is refused on B and C controllers (the manual: "possible only with the P-Controller").

## Write: external setpoint control (section 8.6)

| Register | Meaning | Used as |
|---|---|---|
| 405 | 0 stop, 1 start external setpoint control | start/stop_external_setpoint, estop (0) |
| 406 | external program setpoint, whole degrees | external_setpoint setting |
| 407, 408, 409 | release controlled cooling, charge control, extra relays | not used |

Firmware needed: B400/C440/P470 from 1.51 for setpoint control, communication module from 1.8;
program transfer needs module 1.14 and operating unit 1.79. Marked unverified: the unit of
registers 128/129, and the behaviour of register 148 = 1 while status is 3 (pause); the manual's
sample processes always start from status 0 or 4.
