---
mhp: "2026-09-12"
id: thermo-heracell-co2-incubator-01
class: incubator
make: Thermo Scientific
model: Heracell VIOS 160i / 250i (also Steri-Cycle i160 / i250)
location: ""
tags: [incubator, co2, cell-culture, biologics, modbus, template]
description: Thermo Scientific Heracell VIOS 160i/250i (and Steri-Cycle i160/i250) CO2 incubator reached over Modbus TCP or RTU through a register map that is a TEMPLATE, not a vendor-documented map. Pick it to read chamber temperature, CO2, O2 and humidity and to change the three setpoints of a cell-culture incubator from an orchestrator; not for decontamination (Steri-run) cycles or gas-cylinder changeover, which stay at the touchscreen. Every register address must be confirmed against the controller's own Modbus document before first use.
driver: driver.py:Device
sim: sim.py:Sim
---

# Thermo Heracell VIOS CO2 incubator (Modbus template)

A 165 L or 255 L CO2 incubator for mammalian cell culture: 37 °C, 5 % CO2, humidified, with an
optional O2 control loop (1–21 % or 5–90 % depending on the sensor fitted). This package
drives it through the declarative Modbus driver. The addresses in `descriptor.yaml` are
**placeholders**: Thermo's user manual (50162755) documents an ASCII request/reply protocol with
CRC8 checksums over USB/RS-232, not a Modbus map, so the map here is a template to be filled in
from the controller's own Modbus document or from a gateway's configuration (see
`references/registers.md`). Until it is confirmed, use the twin only.

## Operating procedure

1. Read `connected`, then `temperature`, `co2` and `humidity` to confirm the link answers and
   the chamber is at its working conditions (37.0 °C, 5.0 % CO2, > 90 % RH after the door has
   been closed for about 30 min).
2. Read `door_closed` and `alarm_active`. An open door suspends gas supply and chamber heating
   on this incubator; wait for `door_closed` before trusting readings.
3. To change conditions write `temperature_setpoint`, `co2_setpoint` or `o2_setpoint`. Writes
   are allowed while a job runs (`during_job`); the incubator's own controller does the ramping.
   Writing `co2_setpoint` 0 switches the CO2 control loop off on this instrument.
4. Read `temperature_setpoint_actual` and the other `*_setpoint_actual` signals to confirm the
   controller accepted the value, then poll the measured signals until they settle.
5. There is nothing to start or stop: the incubator holds its conditions continuously. Leave it
   as you found it (37 °C / 5 % CO2 unless the culture needs otherwise).

## What to watch

- `alarm_active` true means the controller is raising a temperature, gas, humidity or
  door-open alarm; read the error log at the touchscreen. The package cannot clear alarms.
- After a door opening CO2 recovers within minutes, humidity within tens of minutes; do not
  judge the culture conditions from a reading taken right after the door closed.
- `o2` reads a number only when an O2 sensor is fitted; without one the register answers a
  constant and the value means nothing. Set `o2_setpoint` only on O2-equipped units.
- No `robot_access_ready` is declared: the door contact says open or closed, not that an
  automatic door is parked open, so a handling robot must take that from its own door drive.

## Resources

- `references/registers.md`: the placeholder register map, the ASCII protocol Thermo actually
  documents, and what was and was not verified.
- `references/setup.md`: wiring, pymodbus, controller settings, first hardware test, status.
