# Register reference: Eurotherm 2400 series (2416, 2404, 2408) over Modbus

Source: Eurotherm, *Series 2000 Communications Handbook: 2000 Series MODBUS and EI-BISYNCH Digital
Communications Handbook*, part no. HA026230, Issue 3, June 2011 (eurothermonline.com instrument
manuals). Chapter 3 (Modbus/JBUS protocol), chapter 5 (parameter address lists: Home, Run, Alarm,
Autotune lists for 2400 version 3) and section 5.9 (ramp/dwell programmer data). The 2416 is a
2400-series instrument and shares this map; the 2404/2408 add more programs.

Transport: Modbus RTU, 8 data bits, no parity, 1 stop bit (parity selectable in the comms list),
9600 or 19200 baud, EIA-485 2-wire or EIA-232. Every parameter is a holding register read with
function 03 and written with 06/16; the handbook's addresses are 0-based register numbers as
pymodbus sends them. Values are scaled integers in the controller's display resolution (an
instrument showing one decimal place sends 1234 for 123.4); the IEEE 32-bit region at
0x8000 + 2 x address carries the same parameters as floats on version 3 firmware (not used here).

## Read (chapter 5, Home and Run lists)

| Signal | Address | Meaning (handbook mnemonic) | Verified |
|---|---|---|---|
| temperature | 1 | Process variable PV | from the handbook |
| target_setpoint_actual | 2 | Target setpoint SP (read back; writable) | from the handbook |
| output_power | 3 | % output level OP | from the handbook |
| temperature_setpoint | 5 | Working setpoint w.SP (read only) | from the handbook |
| program_number | 22 | Current program running / active program number (Prg) | address from the handbook; **write to select is unverified** |
| program_status_code | 23 | Program status StAt: 1 reset, 2 run, 4 hold, 8 holdback, 16 complete | from the handbook |
| segment_type_code | 29 | Current segment type StYP: 0 end, 1 ramp rate, 2 ramp time, 3 dwell, 4 step, 5 call | from the handbook |
| segment_time_remaining | 36 | Segment time remaining SEGt | from the handbook (units per program) |
| segment | 56 | Current segment number SEG | from the handbook |
| program_time_remaining | 58 | Program time remaining PrGt | from the handbook (units per program) |
| cycles_remaining | 59 | Program cycles remaining CYC | from the handbook |
| alarm_active | 75 | Summary output SO | from the handbook |
| segment_target | 160 | Target setpoint of the current segment tGt | from the handbook |
| ramp_rate | 161 | Ramp rate of the current segment rAtE | from the handbook |
| programmer_setpoint | 163 | Programmer setpoint PSP | from the handbook |
| manual_mode | 273 | Auto/manual select m-A: 0 auto, 1 manual | from the handbook |

`program_running` is not a register: the driver answers it as status code 2 or 8.

## Write

| Address | Values | Used by | Verified |
|---|---|---|---|
| 2 | target setpoint in display units | target_setpoint setting | from the handbook |
| 22 | program number to run | run_program (select) | address from the handbook; the Run list calls it "current program running"; its use to select the next program before Run is **unverified** and may need the 2416's PrG parameter instead |
| 23 | 1 reset, 2 run, 4 hold | run_program, hold_program, reset_program, estop (1) | from the handbook (program status is writable on programmer models) |
| 273 | 1 manual | estop | from the handbook |
| 3 | output power, writable in manual mode only | estop (0) | from the handbook (OP writable in manual) |

## Programmer data (section 5.9, 2400 series only)

Program n starts at 8328 + 136 x (n - 1) (program 0 at 8192 is the running copy, editable only
in Hold). Each program is 17 blocks of 8 words: block 0 general data, blocks 1-16 the segments.

| Offset in the general block | Meaning | Written as |
|---|---|---|
| 0 | holdback type (0 none, 1 low, 2 high, 3 band) | 0 |
| 1 | holdback value | 0 |
| 2 | ramp units (0 s, 1 min, 2 h) | 1 |
| 3 | dwell units (0 s, 1 min, 2 h) | 1 |
| 4 | program cycles | 1 |

| Offset in a segment block | Step | Dwell | Ramp (rate) | Ramp (time) | Call | End |
|---|---|---|---|---|---|---|
| 0 | type 4 | type 3 | type 1 | type 2 | type 5 | type 0 |
| 1 | target | - | target | target | - | end power |
| 2 | - | duration | rate | duration | - | - |
| 3 | - | - | - | - | program number | end type |
| 4 | logic outputs | logic outputs | logic outputs | logic outputs | call cycles | logic outputs |

A typed segment `{target_c, ramp_c_per_min, dwell_min}` is written as a ramp-rate segment (type
1, target, rate per minute) followed, when dwell_min > 0, by a dwell (type 3, duration minutes);
an End segment (type 0) closes the program. End power and end type (offsets 1 and 3 of the End
block) are left as stored; their codes are not listed in HA026230 (**unverified**). The handbook
states writes to parameters not relevant to a segment type are rejected; the twin does the same
for writes while a program runs.

## Controllers with another map

The 3216, 3508/3504 and nanodac use different addresses (the parameter lists are shown by
Eurotherm iTools and in their own communications manuals, e.g. HA028014 for the 3500 series).
Rewrite the `modbus:` block from that document; keep the signal names.
