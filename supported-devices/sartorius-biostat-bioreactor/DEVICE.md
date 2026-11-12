---
mhp: "2026-09-12"
id: sartorius-biostat-bioreactor-01
class: bioreactor
make: Sartorius
model: Biostat B / Biostat STR (DCU 4, Biobrain)
location: ""
tags: [bioreactor, cell-culture, upstream, opc-ua, biobrain, fed-batch]
description: Sartorius Biostat B or Biostat STR stirred-tank bioreactor under its DCU 4 / Biobrain controller, reached through the Biobrain OPC UA server. Pick it to start and follow a Biobrain recipe for a cell line (fed-batch, perfusion phases), read temperature, pH, DO, agitation, gas flow and weight, move setpoints mid-batch, deliver a timed feed, and stop a batch. Not for writing recipes or calibrating probes (done in Biobrain), and not for an Eppendorf BioFlo 320 without its own OPC server (see the setup note).
driver: driver.py:Device
sim: sim.py:Sim
---

# Sartorius Biostat bioreactor (Biobrain OPC UA)

The DCU 4 / Biobrain controller owns the loops, the alarms, the recipes and the batch record. This
package is one more OPC UA client of it, with a user that has the Remote operation permission: it
starts a recipe, reads the process values, writes setpoints into loops it then puts in Auto, feeds
through the substrate pump, and stops. Node ids differ per site and come from the OPC UA interface
report Sartorius supplies; config.json holds them.

## Operating procedure

1. Read `connected` and `phase`. A recipe may only start when no phase is running (`Complete`,
   `Stopped` or empty).
2. Find the recipe for the cell line: `methods/find` with the compound (cell line or product) and
   project; a saved method here is the Biobrain recipe name plus an optional duration. Then
   `actions/invoke {name: start_batch, method: {name, project}}`.
3. The job lasts the whole batch; `phase` is pushed as it changes. Read `temperature`, `ph`, `do`,
   `agitation_rpm`, `gas_flow`, `weight_kg` and `foam_alarm` at any time.
4. Setpoints (`temperature_setpoint`, `ph_setpoint`, `do_setpoint`, `gas_flow_setpoint`) may be
   written during the batch; `agitation_setpoint` needs a person's confirmation.
5. `add_feed` with a volume and rate runs the feed pump for volume/rate; it refuses while the
   stirrer is off.
6. `stop_batch` (confirmed by a person) ends the recipe; cancelling the start_batch job does the same.

## What to watch

- `foam_alarm` true: the DCU doses antifoam itself; if it stays on, a person checks the level and
  the exhaust filter.
- `do` falling below the setpoint with agitation and gas at their ceilings means the culture
  outgrows the oxygen supply; tell a person before the DCU cascade saturates.
- `ph` drifting with the base pump running continuously usually means the probe, not the culture.
- E-stop switches the stirrer, gas, feed, acid, base and temperature loops off; the DCU alarms still
  stand. After a reset, a person puts the loops back in Auto at the panel or by writing the setpoints.

## Resources

- `references/setup.md`: Biobrain user, certificates, config.json, Eppendorf BioFlo 320 note, first test.
- `references/opcua.md`: the node roles this package uses, with every id marked unverified.
- `methods/`: one example recipe method (`_shared/cho_fedbatch_14d`); `methods/save` adds the lab's.
- `config.example.json`: endpoint, user, unit and the node id map.
