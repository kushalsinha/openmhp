# Setting up

Flow Commander and its OPC UA server run on the Windows PC attached to the R-Series; this package is
served from that PC or from any machine that reaches the server. The package is pure Python (Linux,
macOS or Windows); the vendor side is Windows-only.

## What you need

- Flow Commander 2.x with the **OPC UA server option** enabled (the R-Series brochure: "The R-Series
  software includes an optional OPC UA server ... Python script examples are included"). Ask Vapourtec
  for the option, its endpoint and port, and the node reference that ships with the examples.
- An OPC UA browser (UaExpert) to read the address space once.
- Alternatively Vapourtec's `FCRemote.dll` / `FCRemoteCSV.dll` .NET interface (used by the open-source
  TheWorldAvatar VapourtecAgent through pythonnet) exists; this package does not use it. See
  `references/opcua_nodes.md`.

## Install

1. `pip install openmhp asyncua keyring` (python-opcua also works).
2. Copy `config.example.json` to `config.json`: set `url`, `max_pressure_bar` (below the weakest part of
   the flow path), and, after browsing, the `nodes`. Pump flows, setpoints, pressure and state are
   required; reactor channels without a reactor and the method nodes may stay `null`.
3. If the server needs a user: set `username` and `python -m keyring set FlowCommanderOPC <username>`.
4. `mhp serve pkg:<this folder> --http <port>` and read `connected`, `system_state`, `system_pressure`.

## Limits are the lab's

The shipped ranges are the brochure's for the whole family (0 to 10 mL/min, -70 to 250 degC, 0 to 20 bar
BPR). Set each pump's and channel's limits to the pump head, reactor coil and BPR actually fitted.

## First hardware test

1. With solvent on both inlets and the outlet in waste: read the pump flows, pressure and reactor
   temperatures; compare with Flow Commander's display.
2. Invoke `prime` on pump A (5 mL at 2 mL/min, `approved: true`); watch `pump_a_flow` and the waste line.
3. Write `reactor_2_setpoint` 40 and watch `reactor_2_temperature` follow; write the room temperature.
4. Invoke `run_experiment` with the example (0.5 + 0.5 mL/min, channel 2 at 120 degC, 10 min residence,
   collect 15 mL) on solvent; confirm `collection_valve` switches to `collect` and back to `waste`.
5. Start a second run and call `safety/estop`: both pumps must read 0, the channel disable, and the valve
   read `waste`.

## Status

twin tested. Written against an OPC UA address space whose node ids are placeholders (no public node
list); not yet run on hardware.
