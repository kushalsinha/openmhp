---
mhp: "2026-09-12"
id: beckman-vicell-blu-01
class: cell_counter
make: Beckman Coulter
model: Vi-CELL BLU
location: ""
tags: [cell-counter, viability, trypan-blue, opc-ua, cell-culture, pharma-biologics]
description: Beckman Coulter Vi-CELL BLU cell viability analyser reached through its OPC UA automation interface. Pick it to count a culture sample (from the automation cup a liquid handler fills, or a carousel slot) with a named cell type and dilution and get viability, viable and total concentration and mean diameter back, to see how many reagent uses remain, and to prime or clean the fluidics. Not for defining cell types or quality controls (done in the instrument software), and not for the 96-well plate workflow.
driver: driver.py:ViCellBlu
sim: sim.py:SimViCellBlu
---

# Vi-CELL BLU (OPC UA automation)

The instrument software owns the cell types, the QC records and the images. This package is an OPC UA
client of its automation interface: it takes the automation lock, starts one sample, waits for
Idle, fetches the result by sample name, and releases the lock, so an operator at the screen is never
locked out for longer than one count.

## Operating procedure

1. Read `connected`, `status` and `reagent_remaining`. `status` must be Idle; below 20 reagent uses,
   tell a person to order a pack.
2. For a liquid handler: wait for `robot_access_ready` true, dispense 200 uL into the automation cup,
   then invoke `count` with `position: "cup"`, the cell type and the dilution. For a carousel, a person
   or robot places the carousel and the position is the slot number as a string.
3. The job lasts about three minutes; cancelling sends Stop. The result carries viability, the
   concentrations (null on interface revisions that report counts only), the mean diameter and the
   image location if requested.
4. `prime` (after a reagent pack change) and `clean` (daily) are confirmed by a person.

## What to watch

- `status` Error or RequiresUserInteraction: a person must clear it at the instrument (waste full,
  reagent pack, stage obstruction).
- Dilution multiplies the reported concentrations; use 1 unless the sample was diluted before the cup.
- A viability below the cell line's norm with a normal diameter usually means the sample sat too long
  in trypan blue, not the culture.

## Resources

- `references/setup.md`: automation option, user and password (keyring), certificates, node ids, first test.
- `references/opcua.md`: the interface's properties, methods and types from Beckman's integration guide,
  and what this package assumes beyond it.
- `config.example.json`: endpoint, user, node id map, allowed cell types.
