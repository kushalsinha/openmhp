---
mhp: "2026-09-12"
id: julabo-corio-circulator-01
class: circulator
make: JULABO
model: CORIO CD / CP, MAGIO, DYNEO
location: ""
tags: [temperature, circulator, bath, chemistry, serial]
description: JULABO CORIO CD/CP, MAGIO or DYNEO heating/refrigerated circulator driven over its USB virtual COM port or RS-232 with the JULABO interface commands (in_pv_00, out_sp_00, out_mode_05). Reads bath and external-probe temperature, sets the working setpoint, starts and stops tempering. Use to hold a reactor jacket, bath or external loop at a temperature between about -20 and 100 degC; the lab sets the real bath-fluid limits.
driver: driver.py:Device
sim: sim.py:Sim
---

# JULABO CORIO / MAGIO / DYNEO circulator

A bath circulator: heater, pump and (on CP, MAGIO, DYNEO refrigerated models) a compressor, holding a
bath fluid at a setpoint and pumping it through an external loop. The interface is the JULABO command
set (`in_...` reads, `out_...` writes, `status`, `version`) on the USB-B port (a virtual COM port) or the
RS-232 socket. Put the port under `port` in `config.json` (see `references/setup.md`). The circulator must
be switched to remote mode at its keypad or menu before `out_` commands are obeyed.

## Operating procedure

1. Read `bath_temperature`, `temperature_setpoint_actual` and `status_text` to confirm the link and that the
   status says REMOTE (`02 REMOTE STOP` when idle).
2. Write `target_temperature` within what the bath fluid can take (water: 5 to 90 degC; the descriptor's
   -20..100 is a placeholder the lab must narrow). The resolution is 0.01 degC.
3. Invoke `start_circulation`. The pump starts and the heater or compressor drives toward the setpoint.
   Expect a few tenths of a degree per second on a small bath, much slower on a large external volume.
4. Follow `bath_temperature`; on units with an external Pt100 (MAGIO, DYNEO) `external_temperature` is the
   probe in the vessel. `heating_power` shows how hard the circulator is working.
5. Change `target_temperature` while running as needed (`during_job: true`). Invoke `stop_circulation` when
   done; `estop` sends `out_mode_05 0` (heater, compressor and pump off).

## What to watch

- A status beginning with `-` is an alarm or warning (for example `-01` low bath-fluid level, `-14` protective
  temperature exceeded); read `status_text` whenever a setpoint is not reached.
- The high-temperature protection (`safety_sensor_temperature`, set on the unit) must sit above every setpoint
  you plan to write; the circulator refuses setpoints above its own limits with `-13`.
- Older JULABO units default to 4800 baud, 7 data bits, even parity on RS-232; see `references/setup.md`.
- Low-temperature setpoints on a refrigerated model are only reachable with a suitable bath fluid; water freezes.

## Resources

- `references/setup.md`: cable, port, remote mode, baud and framing, first hardware test.
- `references/julabo-commands.md`: the interface commands this package uses, from the JULABO CORIO CD manual.
