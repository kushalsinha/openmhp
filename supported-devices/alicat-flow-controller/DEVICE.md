---
mhp: "2026-09-12"
id: alicat-flow-controller-01
class: flow_controller
make: Alicat Scientific
model: MC / MCR mass flow controller (PC / PCD pressure controller compatible)
location: ""
tags: [mass-flow, gas, flow-controller, pressure-controller, serial, rs-485]
description: Alicat Scientific MC/MCR mass flow controller (and the PC/PCD pressure controllers that share the protocol) over RS-232, RS-485 or USB, ASCII polling protocol with a one-letter unit id. Reads the data frame (absolute pressure, temperature, volumetric and mass flow, setpoint, gas) and writes the flow setpoint in the device's own engineering unit. Pick it to meter a gas into a reactor, bubbler or chamber at a set flow and to stop it by zeroing the setpoint; it does not select gases or retune the valve.
driver: driver.py:Device
sim: sim.py:Sim
---

# Alicat mass flow controller

A laminar differential-pressure mass flow controller with a proportional valve. One poll (`A`)
returns everything the device measures in one line; `AS<x>` sets the setpoint and returns the
same line. Setpoint and flow are in whatever engineering unit the device is configured to
(SLPM, SCCM, ...); this package declares L/min, so confirm the device's unit in setup and change
the descriptor's `unit` if yours is SCCM.

## Operating procedure

1. Read `frame` once: the last token is the gas (`Air`, `N2`, ...), and any trailing codes (`MOV`, `HLD`, `OPL`, ...) are status flags. Make sure the gas is the one you are flowing.
2. Read `pressure` (psia upstream) to confirm supply gas is present; a controller cannot flow without inlet pressure.
3. Write `setpoint` in the device unit (0.01 steps). Read `mass_flow` until it settles (a few hundred milliseconds on a healthy valve).
4. To stop, invoke `stop` (setpoint 0, valve closed) or write `setpoint` 0. `hold_closed` forces the valve shut regardless of setpoint until `cancel_hold`.
5. `tare_flow` only with no gas flowing and the outlet open to the same pressure as the inlet; it needs a person's confirmation because a tare under flow makes every later reading wrong.

## What to watch

- `mass_flow` well below `setpoint` with `pressure` low means the supply cannot keep up; the valve is fully open (`frame` shows `MOV` when over range).
- The device replies only to its own unit id. A missing reply means the wrong id (default `A`), the wrong baud (default 19200) or a device left in streaming mode (`@@=A` on a terminal returns it to polling as unit A).
- A pressure controller answers a two-field frame (pressure, setpoint); the field numbers in descriptor.yaml are for a flow controller, see setup.md.

## Resources

- `references/setup.md`: cable, port, unit id, baud, engineering unit, first hardware test.
- `references/protocol.md`: the frame layout and commands this package uses, with the Alicat documents they come from.
