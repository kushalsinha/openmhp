---
mhp: "2026-09-12"
id: arbin-battery-cycler-01
class: battery_cycler
make: Arbin Instruments
model: LBT / BT-2000 under MITS Pro (results-folder route)
location: ""
tags: [battery, cycler, energy-storage, formation, file-based, windows, template]
description: Arbin LBT and BT-2000 battery cyclers under MITS Pro on their Windows PC, driven through a request folder and the CSV results export because the MITS Pro console and SDK are under NDA; written as a TEMPLATE whose request-file layout is this package's own. Pick it to queue a typed charge/discharge protocol (steps, cycles) against a named MITS Pro schedule on one channel with a cell barcode, to have a person start it, to wait for the export and get back the cycle count, last discharge capacity and final voltage parsed from the documented MITS Pro columns. Not for stopping a channel, editing schedules or reading live channel data, which stay at the MITS Pro console.
driver: driver.py:Device
sim: sim.py:Sim
---

# Arbin LBT / BT-2000 under MITS Pro (results-folder route, template)

MITS Pro owns the channels, the schedules (.sdu files written in its schedule editor) and the
data (.res Access databases, exported to CSV or Excel). Its console and SDK are under NDA, so this
package never talks to the cycler: it writes a request file naming the channel, a test name that
carries the job token, the schedule to run and the steps that schedule is expected to perform; a
person starts the test in MITS Pro's Start Channel(s) dialog with that schedule and test name, and
exports the results to the results folder when it ends. The driver finds the export by its token and
parses the documented MITS Pro columns.

## Operating procedure

1. Read `connected` and `queue_depth` (0 unless requests wait). Write `channel` to the channel in
   use; `channel_state` reads `queued` while a request for it waits.
2. Find a method for the cell: `methods/find` with the cell type and project (a saved method here is
   the schedule name, the steps and the cycle count), then `actions/invoke {name: start_protocol,
   method: {name, project}, params: {channel, barcode}}`. Each call is confirmed by a person.
3. The job writes `mhp_<job>.json` into the request folder and waits (days, for formation). The
   person at the console starts the test with the named schedule and the test name
   `<barcode>_mhp_<job>`, and when it ends exports the channel's data as CSV named after the test
   into the results folder.
4. The result names the export and carries `cycles_completed`, `last_capacity_ah` (the last cycle's
   discharge capacity), `final_voltage_v` and `test_time_s`.
5. Cancelling withdraws the request if nobody has started it; a running test is stopped at the
   console. The e-stop withdraws every waiting request and nothing else.

## What to watch

- `steps` are informative: the schedule file is what runs. Keep one schedule per method and name
  it in the method so the request and the schedule cannot drift apart.
- Capacities in MITS Pro exports are cumulative within a step; the parser takes the largest
  discharge capacity of the last cycle, which is the last discharge step's capacity.
- A request that waits longer than `result_wait_s` fails the job and leaves the request file in
  place for a person to see.

## Resources

- `references/setup.md`: the MITS Pro PC (Windows), folders, export settings, first hardware test.
- `references/file_formats.md`: the request file this package writes and the MITS Pro CSV columns it
  reads, with what is unverified.
- `methods/`: one example method (`_shared/coin_cell_formation`); `methods/save` adds the lab's.
- `config.example.json`: folders, MITS Pro version, chemistry caps, timeouts.
