# Setting up

The OPC UA server runs on the bench PC with iControl, so this package is served from that PC or any
machine that reaches it on the network. The package itself is pure Python and runs on Linux, macOS or
Windows; iControl and its OPC server are Windows.

## What you need

- iControl 6 or 7 with the **OPC option** licensed (Mettler sells OPC connectivity as an option for
  iControl / iC software; ask your Mettler representative for "iControl OPC" or the "iC OPC UA Server"
  and its configuration notes). Without it iControl serves nothing.
- The OPC UA endpoint (address and port) and, if the server is configured with user authentication, a
  user for the agent.
- An OPC UA browser (UaExpert is free) to read the server's address space once.

## Install

1. `pip install openmhp asyncua keyring` (python-opcua also works).
2. Copy `config.example.json` to `config.json` and set `url`. If the server needs a user, set `username`
   and store the password with `python -m keyring set iControlOPC <username>`.
3. Browse the server and fill in `nodes`: the Tr and Tj values and setpoints, the stirrer speed and
   setpoint, and the ramp-rate node are required; the others may stay `null` (the matching signal then
   reads null, and the matching method call is skipped). `references/opcua_nodes.md` says what each key
   is for and which ids are placeholders.
4. On the touchscreen set Tsafe, Tr max/min, Tj max/min and Rsafe for this reaction; the package's
   `tr_setpoint` and `tj_setpoint` limits in descriptor.yaml should sit inside them.
5. `mhp serve pkg:<this folder> --http <port>` and read `connected` and `tr`.

## Limits are the lab's

The shipped -40 to 180 degC and 0 to 1200 rpm are the instrument family's ranges, not a reaction's. Set
them to the solvent, the glassware and the stirrer actually fitted.

## First hardware test

1. Read `tr`, `tj`, `stirrer_rpm`; compare with the touchscreen.
2. Write `stirrer_setpoint` 200 with solvent in the reactor; `stirrer_rpm` should follow and
   `stirrer_running` read true. Write 0.
3. Write `tr_setpoint` 30 and watch `tj` lead and `tr` follow; then write the current room temperature.
4. Invoke `start_experiment` with the example (60 degC for 30 min, then 5 degC for 60 min) on solvent
   only; pause and resume it once; cancel it and confirm the stirrer stops and the thermostat goes idle.
5. If a dosing unit is mapped, invoke `dose` 1 mL at 1 mL/min into the stirred solvent and check
   `dosing_total_ml`. Call `safety/estop` during a second dose and confirm dosing and stirring stop.

## Status

twin tested. The package is written against an OPC UA address space whose node ids are placeholders
(Windows-side iControl, no public node list; see `references/opcua_nodes.md`); not yet run on hardware.
