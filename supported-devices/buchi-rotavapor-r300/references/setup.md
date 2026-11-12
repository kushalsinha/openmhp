# Setting up

Runs from any Linux, macOS or Windows machine on the same network as the Interface I-300 Pro. No vendor
library: the package uses Python's standard library for HTTPS and JSON, plus `keyring` for the password.

## What you need

- An R-300 with the **Interface I-300 Pro** (the plain I-300 has no OpenInterface) and a VacuBox; a V-300
  pump and, optionally, a recirculating chiller, all connected to the interface.
- On the interface: Settings > **Rotavapor Open Interface** > enable. The interface shows two users, `ro`
  (read only) and `rw` (read/write), each with a generated password. Note the `rw` password. Restart the
  interface after enabling.
- A fixed IP address or DHCP reservation for the interface (Settings > Network).

## Install

1. `pip install openmhp keyring`
2. Store the `rw` password in the OS keyring, never in a file:
   `python -m keyring set BuchiRotavapor <host>` (the host exactly as you put it in config.json).
3. Copy `config.example.json` to `config.json` and set `host`. The interface uses a self-signed
   certificate; leave `verify_tls` false, or set it true with `ca_cert` pointing at `root_cert.crt`
   from Büchi's `openinterface_rotavapor` repository.
4. `mhp serve pkg:<this folder> --http <port>` and read `connected`.

## Limits are the lab's

`bath_setpoint` ships with the water-bath placeholder 20 to 95 degC. The interface itself accepts up to
220 degC and the bath's own ceiling (`settings.heating.maxTemperature`: 95, 180 or 220) is what protects
it. With an oil bath, raise the max in descriptor.yaml deliberately. `vacuum_setpoint` stops at 1013 mbar.

## First hardware test

1. Read `connected`, `bath_temperature`, `vacuum_mbar`, `rotation_rpm`, `lift_position`; compare with the
   interface display.
2. With an empty flask clamped: write `rotation_setpoint` 60 and invoke `start`; `rotation_rpm` should
   climb to 60 and `running` read true. Invoke `stop`.
3. Invoke `vent` and watch `vacuum_mbar` return to atmospheric; invoke `lift_up` and `lift_down` (the
   latter needs `approved: true`) and watch `lift_position`.
4. Invoke `evaporate` with the example (40 degC, 450 mbar, 20 min) on a flask of water; cancel it after
   two minutes and confirm the system vents and lifts.
5. Call `safety/estop` while rotating and confirm rotation and heating stop, the system vents and the
   lift rises.

## Status

twin tested. Written from Büchi's published OpenAPI specification and Python examples (see
`references/openinterface.md`); not yet run against an I-300 Pro.
