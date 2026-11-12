# PyLabRobot members and the HTTP call this package uses

Sources: github.com/PyLabRobot/pylabrobot main branch (version.txt 1.0.0b1), files
`pylabrobot/legacy/liquid_handling/liquid_handler.py`, `.../backends/opentrons_backend.py`,
`.../backends/chatterbox.py`, `pylabrobot/resources/opentrons/deck.py`,
`pylabrobot/resources/itemized_resource.py`; github.com/Opentrons/opentrons edge branch,
`robot-server/robot_server/robot/control/router.py` and `models.py`. All read 2026-11-11.

| Member | Used for | Verified |
|---|---|---|
| `LiquidHandler(backend, deck)`; `await setup()`, `await stop()`, `setup_finished` | lifecycle; e-stop calls stop() (cancels the HTTP-API run) | yes |
| `pick_up_tips(tip_spots, use_channels=None, offsets=None)` | pick_up_tips | yes |
| `drop_tips(tip_spots, use_channels=None, offsets=None, allow_nonzero_volume=False)` | drop_tips | yes |
| `aspirate(resources, vols: List[float], use_channels=None, flow_rates=None, ...)` / `dispense(...)` | aspirate, dispense | yes |
| `OpentronsOT2Backend(host: str, port: int = 31950)` (older releases: `OpentronsBackend`) | the real backend | yes (old name: the Flex package uses it) |
| `OTDeck()` in `pylabrobot.resources.opentrons` | default deck | yes |
| `LiquidHandlerChatterboxBackend(num_channels=8)` | the twin when pylabrobot is installed | yes |
| `Resource.get_resource(name)`, `ItemizedResource.get_item("A1")` | name resolution | yes |
| `Deck.load_from_json_file(path)` | loading the deck layout file | **unverified** |
| OT-2 door: PyLabRobot exposes none (`opentrons_backend.py` and the `ot_api` package have no door member) | why the driver reads the HTTP API itself | yes |
| `GET http://<host>:31950/robot/door/status` -> `{"data": {"status": "open"|"closed", "doorRequiredClosedForProtocol": bool, "moduleSerial": null}}` | door_open, robot_access_ready | yes (robot-server source) |
| request header `Opentrons-Version: *` | every robot-server request | **unverified** in this read (standard for the Opentrons HTTP API) |

Pipette ranges (docs.opentrons.com, Pipette characteristics): P20 Single/Multi GEN2 1-20 uL, P300
Single/Multi GEN2 20-300 uL, P1000 Single GEN2 100-1000 uL; GEN1 P10 1-10, P300 single 30-300,
P300 multi 20-200, P1000 100-1000.
