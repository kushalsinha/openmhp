---
mhp: "2026-09-12"
id: eppendorf-innova-shaker-01
class: shaker
make: Eppendorf (New Brunswick Scientific)
model: Innova 44 / 44R (Innova 40, 42, 43 compatible)
location: ""
tags: [incubator-shaker, shaking, incubation, cell-culture, serial]
description: Eppendorf New Brunswick Innova 44/44R stackable incubator shaker (and the Innova 40/42/43 family, which share the command set) over its RS-232 port in Slave mode, two-letter ASCII commands with echo. Reads platform speed, chamber temperature, humidity where fitted and the setpoints; sets the speed and temperature setpoints and starts or stops stored profiles. Pick it to hold flask cultures at a temperature and shaking speed under agent control; it does not report whether the chamber is open and has no explicit run/stop beyond a speed of zero.
driver: driver.py:Device
sim: sim.py:Sim
---

# Eppendorf Innova 44/44R incubator shaker

A floor-standing or stackable orbital incubator shaker with a 25 mm (or 51 mm) throw platform,
heating (and refrigeration on the R model) and an RS-232 port on the right of the control panel.
In **Slave** mode the shaker takes setpoints from this package; in **Monitor** mode it only answers
reports. Every command is echoed character by character before the reply, which the driver tolerates.

## Operating procedure

1. Read `speed`, `temperature` and `speed_setpoint`, `temperature_setpoint` to confirm the link and the
   state a person left the unit in. Read `firmware` once.
2. Write `target_temperature` (degC, one decimal) and `target_speed` (rpm, whole numbers). The shaker ramps
   the platform over a few seconds and the chamber over tens of minutes.
3. Stop shaking by invoking `stop_shaking` (speed setpoint 0) or writing `target_speed` 0. There is no
   separate motor-on command: a non-zero speed setpoint is "run".
4. Stored profiles (programs 1 to 4, up to 15 steps each, written on the front panel or with `PW`) run with
   `start_profile`; `profile_running` says whether one is active; `stop_profile` ends it.
5. Before anyone opens the chamber, write `target_speed` 0 and wait for `speed` to read 0; the shaker's own
   safety switch also stops the platform when the chamber is opened, but the protocol does not report it.

## What to watch

- `temperature` is the chamber air temperature at the sensor, not the flask contents; cultures lag by 20 to 40 minutes.
- Set commands answer only with the echo, so each write takes the serial timeout (1 s) to return; reads are immediate.
- Clamp platforms rated for 250 rpm will throw flasks above that; the descriptor caps `target_speed` at 400 (the 44's maximum) and the lab lowers it to its platform's rating.
- Humidity reads 0 unless the optional humidity monitor is fitted; CO2 always reads 0 on these models.
- Kuhner ISF1-X / Climo-Shaker and Infors HT Multitron units are not covered: their serial protocols are supplied by the vendor on request, not published.

## Resources

- `references/setup.md`: cable, port, Mode and baud settings on the COMM screen, first hardware test.
- `references/protocol.md`: the remote-programming command set this package uses, from the Innova manuals.
