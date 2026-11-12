---
mhp: "2026-09-12"
id: vapourtec-rseries-01
class: reactor
make: Vapourtec
model: R-Series (R2 pump module, R4 reactor heater) under Flow Commander
location: ""
tags: [flow-chemistry, reactor, pumps, opc-ua, vapourtec, process-chemistry]
description: Vapourtec R-Series continuous-flow system (R2 pumps A and B, R4 four-channel reactor heater/cooler, back-pressure regulator, collection valve) under Flow Commander, reached through Flow Commander's optional OPC UA server. Pick it to run one flow experiment per compound (flow rates, reactor temperatures, residence time, a collection window) and to read pump flows, reactor temperatures, system pressure and the run state. Not for an R-Series without the OPC UA option, and not for connecting reagents or reactors, which a person does.
driver: driver.py:Device
sim: sim.py:Sim
---

# Vapourtec R-Series (Flow Commander, OPC UA)

Flow Commander on the Windows PC owns the pumps, heaters and valves and, with its optional OPC UA server
enabled, serves their values and setpoints to this package. Vapourtec publishes no node list, so each node
this package uses is a `config.json` entry confirmed by browsing the server once (`references/opcua_nodes.md`).
The experiment logic (heat, pump, wait a residence time, collect, flush) runs here against those nodes;
Flow Commander's own reaction tables are not used.

## Operating procedure

1. Read `connected`, `system_state`, `system_pressure`, `pump_a_flow`, `pump_b_flow` and the reactor
   temperatures. Reagent bottles must be on the right inlets and the outlet in waste before anything pumps.
2. Prime each inlet with `prime` (a person confirms; the pump pushes solvent or reagent to waste).
3. Find the compound's method (`methods/find {compound: "..."}`) and invoke `run_experiment` with it, or pass
   `pump_a_ml_min`, `reactors` and `residence_time_min` directly. The job heats the reactors, sets the BPR,
   starts the pumps, waits a residence time plus the lead-in, collects `collect_ml`, flushes and stops.
4. Setpoints may be changed during a job (`pump_a_flow_setpoint`, `reactor_n_setpoint`, `bpr_pressure`).
5. `stop` or `estop` puts pumps to 0, heaters off and the valve to waste.

## What to watch

- `system_pressure` climbing toward `max_pressure_bar` means a blockage or precipitation; the run fails
  and the pumps stop before the pumps' own trip. Lower the flow or raise the temperature.
- A reactor temperature that never settles within `tolerance_k` fails the heating phase after an hour;
  check the channel's node mapping and that the reactor is clamped in the channel.
- `collection_valve` must read `waste` between runs; `collected_ml` is computed from flow and time, so a
  pump that lost prime collects less than reported.

## Resources

- `references/setup.md`: Flow Commander's OPC UA option, browsing nodes, config.json, first test.
- `references/opcua_nodes.md`: the node keys this package uses, what is public, and what is unverified.
- `methods/_shared/amide-coupling.yaml`: an example flow method.
