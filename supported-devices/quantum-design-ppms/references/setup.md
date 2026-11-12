# Setting up

MultiVu runs on the instrument's Windows PC. MultiPyVu (Quantum Design, MIT, on PyPI) adds a socket
server beside it and a client that can run on Windows, macOS or Linux anywhere on the network, so
this package is served either from the MultiVu PC or from any other machine that can reach it.

1. On the MultiVu PC: `pip install --upgrade MultiPyVu` (needs pywin32 >= 300 there), start MultiVu
   with the cryostat connected, then start the server: `python -m MultiPyVu` (or a two-line script
   with `mpv.Server()`). It listens on port 27183 by default; pass another port to both ends if that
   one is taken. The server hosts one client at a time. `python -m MultiPyVu -get_ip` prints the
   address to put in `config.json`.
2. Where this package runs: `pip install openmhp MultiPyVu` (the client needs no pywin32).
3. Copy `config.example.json` to `config.json`: `host`, `port`, and `platform` (ppms, dynacool,
   mpms3, versalab, opticool), which decides whether the PPMS-only persistent/driven magnet mode
   is offered and whether the chamber commands exist (not on an OptiCool).
4. Set the limits in `descriptor.yaml` to your instrument before the first ramp: `field_setpoint`
   and `set_field_and_wait.field` to the magnet (7 T = 70000 Oe, 9 T = 90000, 14 T = 140000),
   `temperature_setpoint` to the thermometry range installed (base 1.8-400 K; He3, dilution and
   oven options differ; VersaLab 50-400 K). Ship those edits as a package change.
5. Without the instrument, MultiPyVu's scaffolding (`python -m MultiPyVu -s dynacool`, or
   `mpv.Server(flags=['-s', 'DYNACOOL'])`) answers the same client calls on any machine, which is a
   second way to rehearse besides this package's twin.

## First hardware test

1. `mhp serve pkg:<this folder> --http <port>`; read `connected`, `temperature`, `temperature_status`,
   `field`, `field_status`, `chamber_state`. Compare each with MultiVu's own display.
2. Write `temperature_rate` 2 and `temperature_setpoint` 2 K above the current temperature; watch
   `temperature_status` go Tracking, Near, Stable and `temperature` follow.
3. `set_temperature_and_wait` back to the starting temperature with `settle_s` 60; the job should
   finish within the ramp time plus a minute, `reached` true.
4. With a person at the instrument and the magnet's limits set: `set_field_and_wait` to 1000 Oe at
   50 Oe/s (confirm it); check `field_status` goes Charging then Stable; `discharge_magnet`.
5. `set_chamber purge_seal` (confirm); confirm `chamber_state` returns to Purged and Sealed.

## Status

Written from Quantum Design's MultiPyVu project description on PyPI (version 3.8.1) and application
note 1070-220 Rev. A1; the status words that this package reports are passed through from MultiVu and
the exact spellings are unverified (see references/multipyvu.md). MultiPyVu documents no abort, so
`estop` is false and a person stops a ramp in MultiVu. Not yet run on hardware: twin tested.
