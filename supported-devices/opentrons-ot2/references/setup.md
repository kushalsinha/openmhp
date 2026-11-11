# Setting up

Runs on any Windows, Linux or macOS machine that reaches the OT-2 on port 31950 (the Opentrons App's
own HTTP API; Wi-Fi or the USB-Ethernet link).

1. `pip install openmhp pylabrobot` (0.1.x, or 1.0 where the OT-2 backend is `OpentronsOT2Backend`
   under `pylabrobot.legacy`; both names are tried).
2. Find the robot's address in the Opentrons App. Check `http://<host>:31950/health` answers.
3. Build the deck in PyLabRobot once (`OTDeck()`, assign tip racks, plates and reservoirs to slots
   with the names agents will use) and save it: `lh.deck.save("deck.json")`.
4. Copy `config.example.json` to `config.json`: `host`, `deck_file`.
5. Set the volume limits in `descriptor.yaml` to the pipettes mounted (P20: max 20; P300: 20-300;
   P1000: 100-1000) and ship that as a package edit.

## First hardware test

1. `mhp serve pkg:<this folder> --http <port>`; read `connected` and `door_open`. Open and close
   the window; `door_open` must follow and `robot_access_ready` be true only with it open.
2. With water in a source plate: `pick_up_tips ["tips_300/A1"]`, `aspirate ["src_plate/A1"] [100]`,
   `dispense ["dst_plate/A1"] [100]`, `drop_tips ["trash"]`. Weigh the delivered volume.
3. Repeat with the 8-channel pipette and a column of eight spots and wells.
4. `safety/estop` during a dispense once (the gantry stops), then `mhp_lab op='reload'` and check
   the robot homes.

## Status

Written from the PyLabRobot main-branch source (LiquidHandler, OpentronsOT2Backend, OTDeck) and the
Opentrons robot-server source for the door endpoint, read 2026-11-11; `Deck.load_from_json_file` and
the `Opentrons-Version` header requirement are not confirmed in that read. Not yet run on hardware:
twin tested.
