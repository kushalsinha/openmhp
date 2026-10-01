# IKA NAMUR commands used by this package

Send each command followed by CR LF at 9600 baud, 8N1. The instrument replies with the value and channel number.

| Command | Meaning |
|---|---|
| `IN_NAME` | device name |
| `IN_PV_1` | plate temperature (actual), degC |
| `IN_SP_1` | temperature setpoint |
| `OUT_SP_1 x` | set temperature setpoint x |
| `START_1` / `STOP_1` | heater on / off |
| `IN_PV_4` | stirring speed (actual), rpm |
| `IN_SP_4` | speed setpoint |
| `OUT_SP_4 x` | set speed setpoint x |
| `START_4` / `STOP_4` | stirrer on / off |
| `RESET` | leave remote mode |

Error codes on the display: Er3 internal temperature too high; Er4 motor blocked; Er5 external probe; Er6 no external probe.
Consult the IKA manual for the full list and safety notes.
