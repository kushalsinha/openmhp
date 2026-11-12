# JULABO interface commands used by this package

Primary source: JULABO CORIO CD original operating manual, document 1.950.0800.us.V10 (03/2022),
section 11.1 "Interface commands" and 11.2 "Alarms and Warnings". Secondary source: an open-source
(Apache-2.0) JULABO driver README, which cites the
CORIO CP (1.950.0900.us.V04), MAGIO MS (1.950.1700.us.V05) and DYNEO DD (1.950.1300.us.V03) manuals.

Syntax (manual): an IN command is the command followed by CR; the unit answers the value followed by
CR LF (the manual's example shows `55.5 LF`). An OUT command is the command, a space, the parameter,
CR; OUT commands work only in remote mode. This package ends every command with CR and reads one line.

| Command | Meaning (manual) | Used as |
|---|---|---|
| `in_pv_00` | actual (bath) temperature | signal `bath_temperature` |
| `in_pv_01` | current variable, % (heating/cooling power) | signal `heating_power` |
| `in_pv_02` | external Pt100 temperature | signal `external_temperature` (secondary source; CP/MAGIO/DYNEO only; unverified) |
| `in_pv_03` | temperature of the safety sensor | signal `safety_sensor_temperature` |
| `in_pv_04` | current setting of the high-temperature safety function | signal `protective_temperature_setting` |
| `in_sp_00` | setpoint temperature | signal `temperature_setpoint_actual` |
| `in_mode_05` | 0 = stop, 1 = start | signal `circulating` |
| `out_sp_00 xxx.xx` | set the setpoint temperature | setting `target_temperature` |
| `out_mode_05 0|1` | stop / start tempering (remote mode) | actions `stop_circulation`, `start_circulation`; estop sends 0 |
| `version` | firmware version | signal `firmware_version` |
| `status` | status, error, warning, alarm as text | signal `status_text` |

Status strings (secondary source): `00 MANUAL STOP`, `01 MANUAL START`, `02 REMOTE STOP`; `03 REMOTE
START` is inferred and unverified. Interface errors (secondary source): `-08 INVALID COMMAND`,
`-09 COMMAND NOT ALLOWED IN CURRENT OPERATING MODE`, `-10 VALUE TOO SMALL`, `-11 VALUE TOO LARGE`,
`-13 VALUE EXCEEDS TEMPERATURE LIMITS`.

Alarm codes (manual, CORIO CD): `-01` bath fluid level too low; `-05` working-temperature sensor cable
broken or shorted; `-06` difference between working and protection sensor too large; `-14` protective
temperature exceeded; `-33` protection sensor line shorted or interrupted; `-60`..`-72` internal, CAN and
configuration errors; `-63` watchdog responded; `-83` excessive USB power draw; `-108`/`-116` alarm latch
still active.

Ranges (manual, technical data): working temperature range +20..+150 degC on the CD heating circulators,
-20..+150 on CD-200F, down to -50..+200 on CD-1001F; temperature resolution 0.01 degC. The descriptor's
-20..100 limits are a placeholder; the lab's bath fluid sets the real ones.

Serial (secondary source, unverified here): RS-232 factory default 4800 baud, 7 data bits, even parity,
1 stop bit, RTS/CTS; USB is a virtual COM port (manual: "STMicroelectronics Virtual COM Port"). The manual
gives no minimum delay between commands; the secondary driver waits 0.25 s after a setting (unverified).
Not used here: `out_sp_07`/`out_sp_27` (pump stage), `in_sp_03`/`in_sp_04` (warning limits), `in_hil_*`,
`out_mode_04` (internal/external control) because the CD manual does not list them.
