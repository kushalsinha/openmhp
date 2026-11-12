# Serial command reference: Retsch PM 100 / PM 200 / PM 400 (TEMPLATE, unverified)

**Status of this table: every command below is a placeholder invented for this package.** No
Retsch command set was available to read. What the public documents say:

- *Retsch PM 400 operating manual*, document GB 98.535.9999 (08.02.2012), "Serial interfaces"
  (p. 12 of 36): the RS-485 socket "Sc 1" is inactive and meant for optional data communication
  with an external device after a software update; the RS-232 socket "Sc 2" is for updating the
  mill's software; cables longer than 2.5 m cause transmission errors. No command is named.
- *Retsch PM 100 / PM 200 operating instructions* (current issue 03.03.2025, version 0006, and
  the older "BA 062000 3438 e" issue): the RS-232 port connects to a PC for updating the control
  or display software. Retsch's product listings give the interface as RS-232/RS-485. No remote
  command protocol is described.
- Retsch's interface description ("Schnittstellenbeschreibung"), which the task brief says exists
  for some models, was not found online; ask Retsch service for it, quoting the serial number.

Until that document is in hand the `serial:` block of `descriptor.yaml` is a template: the baud
rate (9600 8N1), the line ending (`\r\n`), every command name, every reply word and the error
text are **unverified**.

## Placeholder command table used by descriptor.yaml

| Package name | Command sent | Expected reply | Meaning | Verified |
|---|---|---|---|---|
| speed | `SPEED?` | number | sun-wheel speed, rpm | unverified |
| speed_setpoint_actual | `SPEEDSP?` | number | speed setpoint held | unverified |
| time_remaining | `REMAIN?` | number | seconds left on the timer | unverified |
| running | `STATUS?` | `RUN` / `STOP` | drive turning or at standstill | unverified |
| lid_closed, robot_access_ready | `LID?` | `CLOSED` / `OPEN` | lid switch | unverified |
| speed_setpoint | `SPEED <n>` | `OK` | set speed, rpm | unverified |
| run_time | `TIME <n>` | `OK` | set timer, seconds | unverified |
| run | `SPEED <n>`, `TIME <n>`, `START` | `OK` each | start the grind | unverified |
| stop, e-stop | `STOP` | `OK` | brake to standstill | unverified |
| (unknown command) | | `ERR` | error text | unverified |

Ranges used for the limits (from Retsch's data sheets, which are public): PM 100 and PM 200
100-650 rpm, PM 400 30-400 rpm; the timer reaches 99 h 59 min 59 s. The package caps the timer
at 10 h as a placeholder. Direction reversal, interval grinding and the PM 400's four-station
balancing rules stay at the front panel: no placeholder commands were invented for them.

## What to confirm from the interface description

1. Which socket (RS-232 Sc 2 or RS-485 Sc 1) carries remote control on the lab's unit and
   firmware, and whether a software update is needed first (the PM 400 manual says it is).
2. Baud, framing, line ending and whether commands are echoed.
3. The exact read, write, start and stop commands, their reply words, and the error text; then
   rewrite `serial.read`, `serial.write`, `serial.actions`, `serial.estop`, `serial.booleans`
   and the sim's `_FakePort` to match, and remove the word "template" from DEVICE.md.
