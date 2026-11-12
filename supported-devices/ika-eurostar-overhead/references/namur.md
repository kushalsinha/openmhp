# NAMUR commands used by this package

Source: IKA EUROSTAR 60 control / EUROSTAR 100 control operating instructions, document 20000003965c,
revision EUROSTAR_032018 (March 2018), section "Interfaces and outputs". The command table there is the
whole interface description; it does not show reply lines.

Serial interface (manual): RS-232 (V24) or USB virtual COM port with the same syntax; 9600 bit/s;
1 start bit, 7 data bits, even parity, 1 stop bit; no flow control; the station transmits only when asked.
Commands are upper case; command and parameter are separated by a space; each command and each
response ends with blank CR LF (0x20 0x0D 0x0A); maximum 80 characters; decimal separator is a dot.
This package sends `<command> CR LF` (the blank before CR LF is not sent; the station tolerated that in
the sibling C-MAG HS 7 package but it is unverified here).

| Command | Meaning (manual) | Used as |
|---|---|---|
| `IN_NAME` | read device name | signal `device_name` |
| `IN_PV_3` | read PT1000 temperature probe value | not used (no probe assumed) |
| `IN_PV_4` | read current speed | signal `stir_rpm_actual` |
| `IN_PV_5` | read current torque | signal `torque` |
| `IN_SP_4` | read rated (set) speed | signal `stir_rpm_setpoint_actual` |
| `IN_SP_5` | read the torque limit | signal `torque_limit` |
| `IN_SP_6` | read the speed limit | signal `speed_limit` |
| `IN_SP_8` | read the safety speed | signal `safety_speed` |
| `OUT_SP_4 n` | set the rated speed | setting `stir_rpm` |
| `OUT_SP_5 n` | set the torque limit | setting `torque_limit` |
| `OUT_SP_6 n` | set the speed limit | setting `speed_limit` |
| `OUT_SP_8 n` | set the safety speed | not used |
| `START_4` | start the motor | action `start_stirring` |
| `STOP_4` | stop the motor | action `stop_stirring`, estop |
| `RESET` | switch to normal operating mode | action `release_to_local` |
| `OUT_MODE_n` (n = 1, 2) | change direction of rotation | not used |
| `IN_MODE` | read direction of rotation | not used (reply format unknown) |

Ranges (manual, technical data): speed 0 / 30-2000 rpm (EUROSTAR 60 control), 0 / 30-1300 rpm
(EUROSTAR 100 control); max torque at the shaft 60 Ncm (60 control), 100 Ncm (100 control); speed
setting accuracy ±1 rpm; torque measurement deviation ±6 Ncm. Factory menu values: speed limit 2000 /
1300 rpm, torque limit 60 / 100 Ncm, safe speed 100 rpm.

Unverified (not in the manual): the reply format `<value> <channel>` to IN_ commands (assumed as in the
IKA C-MAG HS 7 package), the empty reply to OUT_/START_/STOP_ commands, and the `Er` reply to an unknown
command. The numeric parser takes the first number of the line, so a reply of `150 4` reads 150 and a
reply of `150` reads the same.
