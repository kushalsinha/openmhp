# Setting up

The package talks OPC UA over Ethernet to the Vi-CELL BLU's own PC, so it can be served from any
Windows, Linux or macOS machine on the network. (Beckman also ships a .NET wrapper DLL with the same
members for Windows clients; this package uses the OPC UA server directly.)

1. The automation option must be licensed and enabled on the instrument (Beckman's "Vi-CELL BLU
   Automation" kit, part C40752 for the offline simulator); set the OPC UA port in the instrument
   software and enable security: a user with automation rights and X.509 certificates.
2. On the serving machine: `pip install openmhp asyncua keyring`. Store the password in the keyring:
   `python -m keyring set ViCellBLU automation`.
3. Trust certificates both ways (UaExpert first, as for any OPC UA server).
4. Node ids: the public integration guide names the properties and methods but not their node ids.
   Browse the server with UaExpert (or read the SDK in `C:\Instrument\Tools\SDK` from the automation
   kit) and copy the ids into `config.json` `nodes`. The shipped ids are placeholders.
5. Copy `config.example.json` to `config.json`: `url`, `user`, `nodes`, optionally
   `allowed_cell_types`.

## First hardware test

1. `mhp serve pkg:<this folder> --http <port>`; read `connected`, `status`, `reagent_remaining`,
   `carousel_present`; compare with the instrument screen.
2. With concentration-control beads or a fresh culture sample in the automation cup: invoke `count`
   with `position: "cup"` and the cell type; compare the result with the instrument's own result record.
3. Run `count` once more with `save_images: true` and check the image location.
4. Start a count and cancel the job; confirm the instrument returns to Idle and the lock is released
   (an operator can use the screen again).
5. With the waste tube emptied: `prime` with a person confirming.

## Status

Written from Beckman Coulter, "Vi-CELL BLU Automation Software Integration Guide for Developer Use",
doc 21.09.2613.PCC Rev A (2021). Node ids, the SampleConfig argument encoding, the carousel position
coding, the prime and clean methods and the concentration result fields are unverified (see
references/opcua.md). Not yet run on hardware: twin tested.
