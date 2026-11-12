---
mhp: "2026-09-12"
id: neware-battery-cycler-01
class: battery_cycler
make: Neware
model: CT-4008 / BTS 8.0 (BTS server TCP interface)
location: ""
tags: [battery, cycler, energy-storage, coin-cell, formation, tcp]
description: Template for Neware CT-4008 and other BTS 8.0 battery cyclers reached through the BTS server's XML-over-TCP interface on the Windows PC that runs the BTS client. Pick it to start a typed charge/discharge protocol (CC charge, CV charge, CC discharge, rest with voltage, time and capacity limits, repeated for N cycles) on one channel with a cell barcode, to follow it to completion and get back the cycle count and last capacity, to read any channel's state, voltage, current and capacity, and to stop a channel or every channel. Not for editing BTS step files, downloading full data records (use BTSDA or the backup folder) or temperature chambers; the step-file layout this package writes is unverified until compared with one the BTS client exports.
driver: driver.py:Device
sim: sim.py:Sim
---

# Neware CT-4008 / BTS 8.0 battery cycler (BTS server interface)

The BTS server owns the channels, the step files and the data. Its TCP interface (port 502 by
default, XML requests ending in `#` on a line) answers `getdevinfo` with the channel list,
`inquire` with each channel's work status, voltage, current, capacity, step and cycle, `start`
with a step file and a barcode, and `stop`. This package writes the step file for a typed
protocol, starts the channel, follows it until the status leaves `working`, and reports the
cycle count and the last capacity. Channels are pipeline ids `devid-subdevid-chlid` (`1-1-3`).

## Operating procedure

1. Read `connected` and `channels`; write `channel` to the pipeline you will use and read
   `channel_state` (it must be `finish`, `stop` or `protect` before a start), `voltage`.
2. Connect the cell to that channel by hand and note its barcode.
3. Find a method for the cell: `methods/find` with the cell type and project (a saved method here
   is the step list and cycle count), then `actions/invoke {name: start_protocol, method: {name,
   project}, params: {channel, barcode}}`; or give `steps` and `cycles` explicitly. Each call is
   confirmed by a person: the voltage limits in the steps are what keeps the cell safe.
4. The job lasts the protocol (hours to days); `progress` follows the cycle counter and the job
   `phase` carries the work status. Cancelling sends `stop`. The result names the step file and
   carries `cycles_completed`, `last_capacity_ah`, `final_voltage_v` and `final_state`.
5. `stop_channel` opens one channel at any time; the e-stop opens every channel.

## What to watch

- `channel_state` reading `protect`: the channel tripped its own protection (voltage, current or
  temperature); the job fails with the partial result and a person resets it in the BTS client.
- `voltage_max_v`, `voltage_min_v` and `current_max_a` in `config.json` must match the chemistry on
  the bench; the package refuses steps outside them before anything is sent.
- The step-file layout is this package's own (`references/bts_api.md`): the first hardware test
  compares it with a file exported by the BTS client and adjusts `render_step_file`.

## Resources

- `references/setup.md`: enabling the BTS API, the PC, folders, config.json, first hardware test.
- `references/bts_api.md`: the TCP protocol as used here, the reply fields and what is unverified.
- `methods/`: one example method (`_shared/coin_cell_formation`); `methods/save` adds the lab's.
- `config.example.json`: host, port, user, password, step folder and the chemistry caps.
