---
mhp: "2026-09-12"
id: elveflow-ob1-01
class: pump
make: Elveflow
model: OB1 pressure controller
location: ""
tags: [microfluidics, pressure, flow, electrolyte, elveflow]
description: Elveflow OB1 pressure controller (shipped limits are for 0-2 bar regulators), pushing liquid through a microfluidic chip or flow cell by pressurising its reservoir. Pick it to set a reservoir pressure, to hold a flow rate using the MFS flow sensor plugged into it, or to read pressure and flow. Not for switching between liquids (use the MUX distributor) and not for pressures above the descriptor limit.
driver: driver.py:OB1
sim: sim.py:SimOB1
---

# Elveflow OB1 pressure controller

Connects by USB to the bench PC that serves it. It pushes liquid by pressurising the
reservoir; flow is whatever the tubing and cell let through, so the same pressure gives a
different flow after a tubing or cell change. An MFS flow sensor plugged into a channel is read
through this device as `flow_chN`.

## Operating procedure

1. Read `connected`. If false, the SDK or USB link is down; a person must look.
2. Read `pressure_ch1..4` and `flow_ch1..4` to see where things stand. A channel with no
   regulator or no sensor reads null.
3. Either write `pressure_setpoint_chN` (mbar), or invoke `set_flow` with a channel and a target
   flow to let the OB1 hold that flow with its own feedback loop on the MFS reading.
4. Wait for `flow_chN` to settle (typically 10-30 s) before starting the experiment.
5. When done, invoke `vent` so every channel goes to 0 mbar.

## What to watch

- Flow reading zero while pressure is up: empty reservoir, a blocked line, or the MUX is on a
  closed port. Vent and tell a person.
- Flow oscillating under `set_flow`: the feedback gains do not suit this tubing; fall back to a
  fixed pressure.
- Never switch the MUX distributor while this controller is pressurised; vent first.
- Emergency stop vents every channel to 0 mbar.

## Resources

- `references/setup.md`: what must be installed on the bench PC and how to fill in config.json.
- `references/variants.md`: adapting the limits to 200 mbar, 8 bar or vacuum regulators.
- `config.example.json`: the settings the driver needs (device name, regulator and sensor types).
