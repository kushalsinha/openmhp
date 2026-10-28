---
mhp: "2026-09-12"
id: akta-avant-01
class: chromatography_system
make: Cytiva (GE Healthcare)
model: ÄKTA avant 25/150 with UNICORN 6/7
location: ""
tags: [chromatography, fplc, protein-purification, unicorn, opc]
description: Cytiva (formerly GE) ÄKTA avant preparative chromatography system driven through the UNICORN OPC server. Pick it to run a saved, validated UNICORN method (affinity, ion exchange, size exclusion, desalting) with the method variables its author exposed, follow UV, conductivity, pressure and flow live, and pause, hold, continue or end the run. Not for building methods or sending loose manual instructions; methods are written and validated in UNICORN.
driver: driver.py:AktaAvant
sim: sim.py:SimAktaAvant
---

# ÄKTA avant (UNICORN OPC)

The ÄKTA is run by UNICORN on its instrument PC. This package talks to UNICORN's OPC Data
Access server on that PC, so everything UNICORN enforces (pressure alarms, column limits, user
rights, audit trail) still applies. Methods live in UNICORN; an agent picks one and sets only
the variables that method's Start Protocol exposes, within the ranges UNICORN declares.

## Operating procedure

1. Read `connected`, `in_control` and `run_state`. `run_state` must be Ready before a new run
   (a run started while another is running is queued by UNICORN, which this package refuses
   unless `queue: true`).
2. Invoke `list_methods` to see the allowed methods with their variables, units and ranges.
3. Use `mhp_method op='find'` for the compound and project; a saved method here is a UNICORN
   method name plus variable values.
4. Invoke `run_method` with the method, a result name and any variables. The job lasts the whole
   run; `live` is pushed every few seconds (UV, conductivity, pressure, flow, block, run state).
5. To intervene: `pause` (stops the pumps), `hold` (keeps flow, freezes the method clock),
   `continue`, or `end` (ends the run and saves the result). Cancelling the job sends `end`.
6. Read the job result: method, result name, duration, last block, and the final readings. The
   chromatogram and peak table are in UNICORN under that result name.

## What to watch

- `in_control` false means someone holds the system in UNICORN; the agent cannot run anything
  until they release it. Do not ask them to hand over control mid-run.
- `run_state` "Alarms and errors": a person must look at the system and acknowledge in UNICORN.
- A pressure rising toward the column limit during loading usually means a clogged column or
  filter; pause and tell a person.
- Emergency stop pauses the system (pumps stop). Ending the run is a separate, deliberate step.

## Resources

- `references/setup.md`: enabling the UNICORN OPC server, Python on the instrument PC, config.json.
- `references/opc_items.md`: the UNICORN OPC items this driver uses, from Cytiva's OPC manual.
- `config.example.json`: OPC ProgID, method folder, allowed methods, signal item names.
