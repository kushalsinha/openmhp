# Serial reference: Laurell 650 controller (TEMPLATE, unverified)

**Status of this command set: every frame below is a placeholder.** Laurell's *WS-650 Series Spin
Processor Operations Manual* (WS-650_TS/BT series, revision 8/2016; a 2011 WS-650 Lite revision and
the WS-400 Lite manual say the same) documents the 650 controller's keypad, LCD, programs (20 of up
to 51 steps), the lid and vacuum interlocks and the Spin 3000 PC software, which downloads programs
and sets the vacuum threshold, sensor actions and valve names over RS-232/USB. The manual does not
print the serial protocol; Laurell supplies it (support@laurell.com) with Spin 3000. Obtain it,
rewrite the `serial:` block in descriptor.yaml and this table, and confirm on hardware.

## What the manual states (used for limits and behaviour)

- Programs: 20 resident programs of up to 51 steps in the controller; more in Spin 3000.
- Per step: speed set point (rpm), acceleration/deceleration (rpm/s, up to 30,000 on the HPD-2
  drive), time, rotation direction and agitation (HPD-2 only), valve and sensor actions.
- Motor: standard drive (650M) and high-performance HPD-2 (650H); chucks spin in excess of 10,000
  rpm (the WS-650 data sheets give 12,000 rpm maximum).
- Lid interlock: the motor and dispense valves are disabled with the lid open; a run stops and shows
  LID OPEN, and resumes from the keypad after the lid is closed.
- Vacuum interlock: a run cannot start below the preset chuck vacuum (15 inHg from the factory, set
  in Spin 3000), shows NEED VACUUM, and halts with LOW VACUUM if it drops; vacuum is not released
  until the chuck has stopped, and is dropped after 10 minutes unused or when the lid opens.
- Power: an over-current circuit breaker on the housing is the ON/OFF switch and the physical stop.

## Placeholder command set used by descriptor.yaml

Framing assumed: ASCII, 9600 8N1, CR-terminated, one reply line per command. **All unverified.**

| Command | Intended meaning | Twin reply | Used as |
|---|---|---|---|
| `?RPM` | actual chuck speed | `RPM <n>` | signal `speed_rpm`, `chuck_still` |
| `?SP` | current step set point | `SP <n>` | signal `speed_setpoint` |
| `?LID` | lid state | `LID 1` closed, `LID 0` open | signal `lid_closed` |
| `?VOK` | vacuum at or above the preset | `VOK 1` / `VOK 0` | signal `vacuum_ok` |
| `?VAC` | chuck vacuum in inHg | `VAC <x.x>` | signal `vacuum_inhg` |
| `?RUN` | a program is running | `RUN 1` / `RUN 0` | signal `running` |
| `?PRG` | selected program slot | `PRG <n>` | signal `program` |
| `?STEP` | current step | `STEP <n>` | signal `step` |
| `PRG <n>` | select program slot 1-20 | `OK` | setting `program`, run_recipe |
| `STEP <slot> <n> <rpm> <rpm/s> <s>` | write step n of a slot (n = 1 clears the slot) | `OK` | run_recipe |
| `RUN` | start the selected program | `OK`, `ERR LID OPEN`, `ERR NEED VACUUM`, `ERR EMPTY` | run_recipe, start_program |
| `STOP` | stop the run, decelerate | `OK` | stop, e-stop |
| `VAC 1` / `VAC 0` | chuck vacuum valve on / off | `OK`, `ERR SPINNING` | vacuum_on, vacuum_off |

Derived by the driver, not commands: `chuck_still` (speed reads 0) and `robot_access_ready` (lid
open and chuck still). Checksums: none assumed; if Laurell's frames carry one, add
`checksum: {kind: xor|sum8, ...}` to the `serial:` block (the driver supports it).
