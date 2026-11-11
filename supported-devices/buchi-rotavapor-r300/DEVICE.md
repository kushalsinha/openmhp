---
mhp: "2026-09-12"
id: buchi-rotavapor-r300-01
class: evaporator
make: Büchi
model: Rotavapor R-300 with Interface I-300 Pro, VacuBox and V-300 pump
location: ""
tags: [evaporator, rotavap, solvent-removal, distillation, rest, buchi]
description: Büchi Rotavapor R-300 rotary evaporator with the Interface I-300 Pro, reached over Ethernet through the BUCHI OpenInterface (HTTPS, JSON, basic auth). Pick it to remove solvent from a flask under vacuum with a set bath temperature, rotation and pressure, either step by step (setpoints, start, stop, vent, lift) or as one timed distillation per solvent (evaporate, a saved method). Not for flask handling, which a person does, and not for an R-300 with the plain I-300 interface, which has no OpenInterface.
driver: driver.py:Device
sim: sim.py:Sim
---

# Büchi Rotavapor R-300 (I-300 Pro)

The I-300 Pro runs the bath, the rotation drive, the V-300 pump through the VacuBox and an optional
recirculating chiller. With "Rotavapor Open Interface" enabled in its settings it serves a small JSON API
on port 443; this package talks to that API with the read/write user and the password shown on the
interface. The flask, the bath liquid and the receiving flask are a person's job.

## Operating procedure

1. Read `connected`, `bath_temperature`, `vacuum_mbar` and `lift_position`. The flask should be clamped,
   the bath filled, and the depth stop set for this flask before anything moves.
2. For one solvent, find its method (`methods/find {compound: "dcm"}`) and invoke `evaporate` with it
   (`actions/invoke {name: evaporate, method: {...}}`), or pass `bath_c`, `vacuum_mbar` and `duration_min`
   directly. The job lowers the flask, pulls vacuum, distils for the time given (or until the vapour probe
   drops, with `stop_when_vapor_below_c`), then vents and lifts the flask out.
3. Step by step instead: write `bath_setpoint`, `rotation_setpoint`, `vacuum_setpoint`; invoke `lift_down`
   (a person confirms: the flask enters the hot bath); invoke `start`; watch `vapor_temperature` and
   `vacuum_mbar`; invoke `stop`, then `vent`, then `lift_up`.
4. Read the job result: time, final pressure and bath temperature, and what ended it.
5. `estop` stops the process, switches heater and rotation off, vents and lifts; the bath stays hot.

## What to watch

- `vapor_temperature` rising to the solvent's boiling point at the set pressure means it is distilling;
  dropping back toward room temperature means it is gone.
- A sudden pressure rise with foam (`process_status.foamActive`) means bumping: raise `vacuum_setpoint`
  or lower `bath_setpoint`.
- `process_status.currentError` non-zero needs a person at the interface; the evaporate job fails on it.
- The bath limit is 95 degC with water. The setpoint limits here are the water-bath placeholder; an oil
  bath lab raises `bath_setpoint` deliberately in descriptor.yaml.

## Resources

- `references/setup.md`: enabling the OpenInterface, the password and keyring, config.json, first test.
- `references/openinterface.md`: the endpoints and JSON fields this package uses, from Büchi's OpenAPI spec.
- `methods/_shared/dcm-strip.yaml`: an example distillation method (dichloromethane).
