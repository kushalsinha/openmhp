# Setting up

Runs on the PC connected to the STAR by USB: Windows (with the Hamilton USB driver VENUS installs,
or libusb/WinUSB via Zadig for PyLabRobot), Linux or macOS (libusb). PyLabRobot documents the USB
driver step per OS.

1. `pip install openmhp pylabrobot` (PyLabRobot 0.1.x, or 1.0 where the same classes live under
   `pylabrobot.legacy` with deprecation shims on the old paths; both import paths used here work).
2. Close VENUS; only one program may hold the instrument.
3. Build the deck in PyLabRobot once (`STARLetDeck()` or `STARDeck()`, assign carriers, tip racks,
   plates and sites with the names agents will use) and save it: `lh.deck.save("deck.json")`.
4. Copy `config.example.json` to `config.json`, set `deck_file` to that file. `device_address` /
   `serial_number` only when several Hamiltons are attached.
5. Lower the volume limits in `descriptor.yaml` to the channels installed (300 uL channels: 300)
   and ship that as a package edit.

## First hardware test

1. `mhp serve pkg:<this folder> --http <port>`; read `connected` and `cover_open`. Open and close
   the cover and watch `cover_open` follow; `robot_access_ready` must be true only with it open.
2. With water in a source plate: `pick_up_tips ["tips_1000/A1"]`, `aspirate ["src_plate/A1"] [100]`,
   `dispense ["dst_plate/A1"] [100]`, `drop_tips ["trash"]`. Weigh the delivered volume.
3. `move_plate` an empty plate between two free sites with the iSWAP path clear.
4. `safety/estop` during nothing, then `safety/reset` and read `connected` (the twin reconnects on
   its own; the real STAR needs `mhp_lab op='reload'` so setup runs again).
5. Press the instrument's STOP button during a slow move once, to learn what re-initialising takes.

## Status

Written from the PyLabRobot main-branch source (LiquidHandler, STARBackend, STARChatterboxBackend,
star_decks) read on 2026-11-11; `Deck.load_from_json_file` is the one member not confirmed in that
read. Not yet run on hardware: twin tested.
