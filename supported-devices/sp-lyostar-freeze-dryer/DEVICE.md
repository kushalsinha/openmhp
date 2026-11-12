---
mhp: "2026-09-12"
id: sp-lyostar-freeze-dryer-01
class: freeze_dryer
make: SP Scientific
model: LyoStar 3 / LyoStar 4 (Martin Christ Epsilon 2-4 LSCplus via notes)
location: ""
tags: [lyophilisation, freeze-drying, formulation, small-molecule, modbus, template]
description: SP Scientific LyoStar 3/4 laboratory freeze dryer (shelf -70 to 60 degC, condenser to -85 degC, capacitance manometer and Pirani) reached over a Modbus map that is a TEMPLATE with unverified placeholder addresses; the controller's real map (LyoS / SCADA OPC or Modbus) is not public. Pick it to run a loaded lyophilisation recipe by number, hold or stop it, watch shelf, condenser and product temperatures, chamber pressure and the drying phase, and defrost the condenser between runs; not for writing recipes, which stay in the controller software. Confirm every address against the controller's document before first use.
driver: driver.py:Device
sim: sim.py:Sim
---

# SP LyoStar freeze dryer (Modbus template)

A development-scale shelf freeze dryer: three or more temperature-controlled shelves in a
chamber, an external ice condenser, a vacuum pump, a capacitance manometer (gas-independent)
and a Pirani gauge (reads high while water vapour is present, which is how the end of primary
drying is seen). A lyophilisation cycle is a recipe held in the controller: freezing, optional
annealing, primary drying under vacuum at a shelf temperature below the product's collapse
temperature, then secondary drying. This package drives the controller through the
declarative Modbus driver with **placeholder addresses**: SP's LyoS / Telstar SCADA and Martin
Christ's LPCplus expose their tags through OPC or Modbus with maps that are not public. Fill the
`modbus:` block from your controller's document (see `references/registers.md`) before use.

## Operating procedure

1. Read `connected`, `door_closed`, `idle`, `vacuum_ok` and `condenser_temperature`. A run
   starts only with the door closed and the controller idle; the condenser should be below
   -40 °C before primary drying, which the recipe itself waits for.
2. Find the recipe for the product: `mhp_method op='find'` with the compound. A method here is
   the recipe number loaded in the controller plus the product it is validated for; the
   recipe's steps live in the controller software, not in this package.
3. Invoke `start_recipe` with the method (or `recipe` number). The job writes the recipe
   number and sets the run coil; the controller then runs the cycle, typically 24–72 h.
4. Poll `phase_code`, `shelf_temperature`, `product_temperature_1..3`, `chamber_pressure`
   and `pirani_pressure`. Primary drying ends when Pirani and capacitance manometer converge
   and product probes rise to the shelf temperature.
5. `hold` freezes the recipe at its current step (short; the controller holds conditions);
   invoke `start_recipe` again only if your controller resumes on the run coil, otherwise
   resume at the controller. `stop_recipe` ends the cycle (confirm: it aborts the batch).
6. After the run the controller vents and the person unloads; then, with the door closed and
   the controller idle, `defrost_condenser` (confirm) melts the ice before the next batch.

## What to watch

- `shelf_setpoint` can be changed during a run, but a shelf ramp during primary drying can
  take the product above its collapse temperature and ruin the cake: it needs a person's
  confirmation every time.
- `vacuum_ok` false during drying means a leak, a pump fault or the condenser overloaded;
  the controller alarms and may hold. Read `phase_code` to see whether it moved to a hold.
- Product probes read only where probes are placed; a probe not in a vial reads the shelf.
- No `robot_access_ready`: the door contact reports closed or open only, and this bench
  freeze dryer is loaded by hand (automatic loading systems are production equipment).

## Resources

- `references/registers.md`: placeholder register map, phase codes, what is and is not verified.
- `references/setup.md`: network, pymodbus, controller settings, first hardware test, status.
- `methods/README.md`: what a method means on this instrument, and the example record.
