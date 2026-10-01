---
mhp: "2026-09-12"
id: elveflow-mux-distributor-01
class: valve
make: Elveflow
model: MUX Distributor (rotary selection valve)
location: ""
tags: [microfluidics, valve, selector, electrolyte, elveflow]
description: Elveflow MUX Distributor, a rotary valve that connects one of its numbered ports to the common line. Pick it to choose which liquid (fresh electrolyte, DI water for cleaning, air for drying, waste) feeds the flow cell. It does not move liquid itself (the OB1 pressure controller does) and it cannot mix two ports.
driver: driver.py:MuxDistributor
sim: sim.py:SimMux
---

# MUX Distributor

Sits between the reservoirs and the flow cell, on a serial (COM) port of the bench PC. One port is open at a time. What is plumbed to each port is listed in
`port_map`; trust that over any assumption.

## Operating procedure

1. Read `connected` and `port_map` to learn which port carries which liquid.
2. Vent the OB1 that feeds this valve (its `vent` action) and check its pressure reads near 0.
3. Invoke `select_port` with the port number. The job finishes when the valve reports the new port.
4. Read `valve_position` to confirm, then bring the OB1 pressure or flow back up.

## What to watch

- Switching under pressure wears the rotor seal and sends a pressure spike into the cell. The
  valve cannot see the OB1, so the vent in step 2 is the agent's responsibility.
- A position that does not match the request after `select_port` means the valve is stuck; stop
  and tell a person.
- There is no emergency stop: the valve simply stays where it is. Venting the OB1 is what makes
  the fluidics safe.

## Resources

- `references/setup.md`: installation on the bench PC and how to fill in config.json.
- `config.example.json`: COM port, number of ports and what is plumbed to each.
