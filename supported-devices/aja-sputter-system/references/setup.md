# Setting up

The package is pure Python with pymodbus and runs on Linux, macOS or Windows; the simulated twin
needs nothing. **Status: template.** The register map is a placeholder (see `registers.md`); do not
connect a real tool until the `modbus:` block has been rewritten from the integrator's tag list.

1. Ask the tool's integrator (AJA, Kurt J. Lesker or Moorfield service) whether the control PLC can
   be reached over Modbus TCP or OPC UA, and for the tag list. On an AJA Orion the Phase II laptop
   and the PLC share a private network: a gateway or a second port is usually added.
2. Cable the serving machine to that network; note the PLC or gateway address and unit id.
3. `pip install openmhp pymodbus`.
4. Rewrite `modbus:` in `descriptor.yaml` (addresses, kinds, types, scale for Torr versus mbar,
   `sequences`, `estop`) from the tag list, and `sim.py`'s `_Plc` to match.
5. Copy `config.example.json` to `config.json`: `host` and, if not 1, `unit`.
6. Set the limits (`power_setpoint`, `substrate_temperature_setpoint`, `gas_flow_setpoint`, the
   `deposit` parameters) to the lab's supply, target, heater and MFC ratings, and record the
   deposition-rate calibration per target and power that `rate_nm_per_min` will carry.
7. `mhp serve pkg:<this folder> --http <port>` and read `connected`.

## First hardware test

1. With the chamber at base pressure and the door closed: read `base_pressure`,
   `process_pressure`, `door_closed`, `base_pressure_ok`, `water_flow_ok`, `shutter_open`,
   `plasma_on` and compare each with the vendor software's screen. Open the door (with the chamber
   vented) and confirm `door_closed` flips.
2. Write `gas_flow_setpoint` 20 and watch `gas_flow` and `process_pressure` on both screens;
   write it back to 0.
3. Write `rotation_on` true and confirm the holder turns; false again.
4. With a test substrate and a known target: invoke `deposit` with the first example (100 W, 120 s
   presputter, 600 s shutter) and confirm it; watch `plasma_on`, `power` and `shutter_open` follow
   the sequence on the vendor screen; measure the film and record the rate as `rate_nm_per_min`.
5. Start a second deposition and trigger `safety/estop`: the shutter closes, the supply goes off and
   `state` reads `estop`; `safety/reset` only after a person has looked at the tool.

## Status

Template. Written from AJA's Phase II-J manual (November 2005) for the recipe fields and interlocks
and from Kurt J. Lesker PVD 75 datasheets for the tool's automation; no vendor register map was
available, so every address in `descriptor.yaml` is an unverified placeholder. Not run on hardware.
