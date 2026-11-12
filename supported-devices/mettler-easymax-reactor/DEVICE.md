---
mhp: "2026-09-12"
id: mettler-easymax-reactor-01
class: reactor
make: Mettler Toledo
model: EasyMax 102/402 or OptiMax 1001 under iControl
location: ""
tags: [reactor, synthesis, process-chemistry, opc-ua, icontrol, dosing]
description: Mettler Toledo EasyMax 102/402 (or OptiMax 1001) automated synthesis reactor under iControl, reached through iControl's OPC UA server from the bench PC. Pick it to run a temperature recipe on a stirred, thermostated reactor (ramps, holds, dosing from the dosing unit, pH logging) with the reactor and jacket temperatures, stirrer speed and dosing volume as live signals. Not for loading vessels, which a person does, and not for an EasyMax with no OPC option in its iControl licence.
driver: driver.py:Device
sim: sim.py:Sim
---

# Mettler Toledo EasyMax (iControl, OPC UA)

The EasyMax is a thermostat block with one or two glass reactors, an overhead stirrer and a touchscreen;
iControl on the bench PC records the experiment and, with the OPC option, serves the live values and
setpoints over OPC UA. Mettler publishes no node list, so every node this package touches is a
`config.json` entry confirmed by browsing the server once (see `references/opcua_nodes.md`). The thermostat's
own safety limits (Tsafe, Tr and Tj max and min, Rsafe) stay set on the touchscreen.

## Operating procedure

1. Read `connected`, `tr`, `tj`, `stirrer_rpm`, `phase`. The reactor must be charged and covered, the Tr
   probe in the liquid, before any temperature is set.
2. Find the recipe for the compound: `methods/find {compound: "..."}`; invoke `start_experiment` with it
   (`actions/invoke {name: start_experiment, method: {...}}`), or pass `steps` directly. The job starts an
   iControl experiment, then for each step sets stirrer and ramp rate, writes the Tr setpoint, waits for Tr
   to settle within `tolerance_k`, and holds; finally brings the reactor to `end_tr_c`.
3. To add a reagent, invoke `dose` with volume and rate; it is refused unless `stirrer_running` is true.
4. Setpoints may be changed during a job (`tr_setpoint`, `stirrer_setpoint`, `ramp_rate`); the running step
   will still wait for its own target.
5. When done, invoke `end_experiment` (or set `end_experiment: true` in the recipe): the stirrer stops and
   the thermostat goes idle. `estop` does the same immediately and stops any dosing.

## What to watch

- `tj` far from `tr` for a long time means poor heat transfer: low stirrer speed, a small charge, or the
  probe out of the liquid. The package faults a step whose Tr never settles.
- Exotherms show as `tr` above its setpoint with `tj` dropping below it; the thermostat compensates up
  to its Tj limits, beyond which iControl runs its emergency program and this package sees only a Tr
  that will not settle.
- `dosing_total_ml` and `ph` read null until their nodes are mapped; the dose action still works through
  the dose method node and counts volume here.

## Resources

- `references/setup.md`: iControl with the OPC option, the OPC UA server, browsing the nodes, config.json, first test.
- `references/opcua_nodes.md`: the node keys this package uses, what is known publicly, and what is unverified.
- `methods/_shared/crystallisation-cool.yaml`: an example recipe (a cooling crystallisation).
