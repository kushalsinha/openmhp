---
mhp: "2026-09-12"
id: aja-sputter-system-01
class: deposition_system
class_ref: CHMO:0002122
make: AJA International
model: ATC Orion (Phase II control); Kurt J. Lesker PVD 75 and Moorfield nanoPVD via notes
location: ""
tags: [sputtering, pvd, thin-film, deposition, materials-synthesis, modbus, template]
description: Magnetron sputter deposition tools (AJA ATC Orion under Phase II, Kurt J. Lesker PVD 75, Moorfield nanoPVD) whose control PLC exposes a Modbus TCP register map, written as a TEMPLATE whose register addresses are unverified placeholders. Pick it to watch base and process pressure, power, shutter, substrate temperature and the door and water interlocks, to pump down or vent, and, with a person's confirmation, to run one timed sputter deposition (gas, power, plasma, shutter) that returns a thickness estimate from a calibrated rate; not for recipe editing, target selection or multi-layer stacks, which stay in the vendor software. Every register must be confirmed against the tool's PLC map before first use.
driver: driver.py:Device
sim: sim.py:Sim
---

# AJA Orion / Lesker PVD 75 / Moorfield nanoPVD sputter tool (Modbus template)

A confocal magnetron sputter tool: a vacuum chamber pumped to a base pressure in the 1e-7 mbar
range, argon admitted through a mass-flow controller to a few 1e-3 mbar, a DC or RF supply that
ignites a plasma on one target, a shutter over the target, and a rotating, optionally heated
substrate holder. AJA's own control is the LabVIEW-based Phase II software (the Phase II-J manual,
November 2005, describes layers with power setpoint, shutter delay, coat time, heater setpoint and
soak time, and says the control laptop talks to the PLC over a private network with no further
networking recommended). Neither AJA, Kurt J. Lesker (PVD 75) nor Moorfield (nanoPVD) publish a
Modbus or OPC UA register map; some installations add a Modbus TCP gateway on the PLC or an OPC UA
server in the vendor software. The `modbus:` block here is therefore a **placeholder** map
(`references/registers.md`): confirm every address with the tool's integrator before first use.

## Operating procedure

1. Read `connected`, `base_pressure`, `base_pressure_ok`, `door_closed` and `water_flow_ok`. A
   deposition is refused unless all three interlocks read true.
2. If the chamber is vented, invoke `pump_down` and wait for `base_pressure_ok`: hours on a real
   tool. `vent` (confirmed) brings the chamber to atmosphere for loading; never while `plasma_on`.
3. Write `substrate_temperature_setpoint` and `heater_on` if the film needs a hot substrate; wait
   for `substrate_temperature`. Write `rotation_on` true for uniformity.
4. Invoke `deposit` (confirmed by a person each time) with `gas_flow_ml_min`, `power_w`,
   `presputter_s`, `duration_s` and `rate_nm_per_min` from the lab's calibration for that target
   and power. The job sets the gas flow and power, enables the supply, waits for `plasma_on`, holds
   the shutter closed for the presputter time, opens it for `duration_s`, then closes it and turns
   the supply off. The result carries the thickness estimate (rate times shutter-open time).
5. Cancelling the job closes the shutter and turns the supply off; so does `stop_process` and the
   e-stop. Pressure and gas flow are left where they were; write `gas_flow_setpoint` 0 afterwards.

## What to watch

- `plasma_on` not reading true within the ignition timeout: pressure too low to strike (raise the
  gas flow for ignition, as AJA's manual suggests) or a supply fault. The job fails without opening
  the shutter.
- A process pressure outside the window in `notes` of `process_pressure`: the supply may arc or
  the film's stress and density change; the PLC's own limits apply, this package only reports.
- The `robot_access_ready` signal is a placeholder for tools with a load lock served by a
  transfer robot (Orion load-lock configurations); on a tool loaded by hand it reads from a
  register that may not exist and should then be removed.

## Resources

- `references/registers.md`: the placeholder register map, the Phase II recipe fields it mirrors,
  and what must be confirmed.
- `references/setup.md`: pymodbus, network, PLC settings, first hardware test and status.
- `config.example.json`: host and unit id.
