---
mhp: "2026-09-12"
id: mbraun-glovebox-01
class: glovebox
make: MBRAUN
model: LABstar / UNIlab / LABmaster / MB200 with the PLC Ethernet (Modbus TCP) option
location: ""
tags: [glovebox, inert-atmosphere, argon, nitrogen, antechamber, modbus, template]
description: MBRAUN inert-gas gloveboxes (LABstar, UNIlab, LABmaster, MB200 workstations) whose Siemens-based PLC carries the Ethernet option and answers Modbus TCP, written as a TEMPLATE whose register addresses are unverified placeholders. Reads O2 and H2O in ppm, box and antechamber pressure, blower, purge and regeneration state, antechamber state and both antechamber door interlocks; runs an evacuate/refill antechamber cycle with a typed purge count, releases the inner or outer antechamber door interlocked on the other, and starts purge or regeneration with confirmation. Pick it to watch and sequence an inert box around a robot or a battery line; not for moving the gloves or anything inside, and not without confirming every address against MBRAUN's interface document.
driver: driver.py:Device
sim: sim.py:Sim
---

# MBRAUN glovebox (PLC Modbus TCP template)

An argon or nitrogen box with a gas purifier (copper catalyst and molecular sieve), a circulation
blower, O2 and H2O analyzers, a working-pressure controller and one or two antechambers whose
inner and outer doors are mechanically interlocked against each other. MBRAUN's touch-panel PLC
offers an Ethernet option and MBRAUN service supplies a signal list for it; no public register
map was found while writing this package, so every address in `descriptor.yaml` is a
**placeholder** marked unverified in `references/registers.md`. Obtain MBRAUN's interface document
for your box, rewrite the `modbus:` block, and rehearse with the twin until then.

## Operating procedure

1. Read `connected`, `o2_ppm`, `h2o_ppm`, `box_pressure`, `blower_on` and `purge_state`. A
   working box reads below 1 ppm on both and a pressure near its setpoint; `regenerating` true
   means the purifier is in its ~24 h regeneration and O2 will drift up.
2. To pass material in: with `antechamber_state` idle and both doors closed, invoke
   `antechamber_cycle {purges: 3}` (evacuate to ~1 mbar and refill with box gas, three times,
   about 10 minutes on a large antechamber). The job ends when the cycle is started; poll
   `antechamber_state` until it reads `idle` and `antechamber_pressure` is back at box pressure.
3. Invoke `release_inner_door` to let a person or the in-box robot open the inner door; it
   refuses unless `outer_door_closed` and the antechamber is idle. `robot_access_ready` is true
   while the inner door is open and no cycle runs.
4. Invoke `release_outer_door` only when `inner_door_closed`; the PLC's own mechanical interlock
   is the second line of defence.
5. `start_purge` (confirm) opens the purge valve to flush a contaminated box; `start_regeneration`
   (confirm) runs the purifier regeneration and takes the box off the catalyst for a day.
6. Stop a cycle with `stop_antechamber_cycle`; e-stop aborts the antechamber cycle and closes
   purge and regeneration, and leaves the blower running on purpose.

## What to watch

- O2 and H2O analyzers age and need calibration (zero in the box, span on a reference gas);
  `calibration_status` is the lab's record.
- Pressure: MBRAUN boxes work between about -15 and +15 mbar relative to the room. Foot-pedal
  pressure changes by a person at the box are not visible here except through `box_pressure`.
- The antechamber cycle takes vacuum from the box's pump; do not start regeneration and a
  cycle together.
- Every address is a placeholder; a value that never changes, or a door that reads closed while
  open, means the bit is elsewhere. Remove a signal rather than leave a lie.

## Resources

- `references/registers.md`: the placeholder register map, what is known of the MBRAUN interface, and the mapping of state codes to names.
- `references/setup.md`: network, pymodbus, PLC option, first hardware test, status.
