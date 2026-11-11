---
mhp: "2026-09-12"
id: binder-stability-chamber-01
class: environmental_chamber
make: BINDER
model: KBF / KBF P / KMF (MB2 controller); Memmert ICH / HPP via notes
location: ""
tags: [stability, ich, climate-chamber, humidity, gxp, modbus, template]
description: BINDER KBF, KBF P and KMF ICH stability chambers with the MB2 controller reached over Modbus TCP (BINDER Interface Technical Specifications 7001-0242), written as a TEMPLATE whose register addresses are unverified placeholders. Pick it to watch temperature, humidity, door and alarm state of a running stability study and, with a person's confirmation, to change the temperature or humidity setpoint; not for starting, editing or stopping the controller's programs, and not for Memmert chambers without changing the map. Every address must be confirmed against BINDER's Modbus document before first use.
driver: driver.py:Device
sim: sim.py:Sim
---

# BINDER KBF / KMF stability chamber (Modbus template)

An ICH climate chamber holding a stability study at, typically, 25 °C / 60 % rH, 30 °C / 65 %
rH or 40 °C / 75 % rH for months. The MB2 controller offers Ethernet with a Modbus TCP
interface described in BINDER's *Interface Technical Specifications* (Art. No. 7001-0242, issue
10/2017), where actual values and setpoints are 32-bit floats in holding registers. That
document was not available while this package was written, so the addresses in
`descriptor.yaml` are **placeholders**: confirm each against the BINDER document (see
`references/registers.md`) and rewrite the `modbus:` block before touching a real chamber.
Memmert ICH/HPP chambers also speak Modbus TCP through AtmoCONTROL, with a different map.

## Operating procedure

1. Read `connected`, `temperature`, `humidity`, `door_closed` and `alarm_active`. During a
   study the only job of this package is to watch: log the readings and alert on
   `alarm_active` or on a reading outside the study's tolerance (usually ± 2 °C, ± 5 % rH).
2. Read `temperature_setpoint_actual` and `humidity_setpoint_actual` to confirm the controller
   holds the study conditions. A difference from the protocol is a deviation to report, not to
   fix silently.
3. A setpoint change is a GxP event: both setpoints need `approved: true`, which the host sets
   only after a person confirmed that exact request. Write `temperature_setpoint` and
   `humidity_setpoint` only for a planned condition change, then record it in the study file.
4. Programs (ramps, cycling) are started and stopped at the controller or in APT-COM; this
   package declares no program action because no program-control register was verified.
5. `door_closed` false during a study is itself an excursion: note the time it opened and
   closed; humidity recovers within minutes, temperature faster.

## What to watch

- Condensation: with the door open on a humid setting the water system may fault; wait for
  `alarm_active` to clear before trusting humidity.
- The MB2's own limits: a humidity setpoint outside the climatic diagram for the temperature
  (chapter 17 of the KBF manual) is refused or unattainable by the controller; this package's
  10–80 % band is a placeholder and the lab must set the real one.
- No `robot_access_ready` is declared: stability chambers are loaded by people, and the door
  contact reports only open or closed.

## Resources

- `references/registers.md`: the placeholder register map, what is known of the BINDER
  Modbus specification, and the Memmert note.
- `references/setup.md`: network, pymodbus, controller settings, first hardware test, status.
