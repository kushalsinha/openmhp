# PyLabRobot members this package calls

Source: github.com/PyLabRobot/pylabrobot, main branch (version.txt 1.0.0b1), files
`pylabrobot/legacy/liquid_handling/liquid_handler.py`, `.../backends/hamilton/STAR_backend.py`,
`.../backends/hamilton/STAR_chatterbox.py`, `pylabrobot/resources/hamilton/star_decks.py`,
`pylabrobot/resources/resource.py`, `pylabrobot/resources/itemized_resource.py`, read 2026-11-11.
On released 0.1.x the same classes sit under `pylabrobot.liquid_handling...` (the paths this driver
imports; on 1.0 they are deprecation shims that still resolve).

| Member | Used for | Verified |
|---|---|---|
| `LiquidHandler(backend, deck)`; `await setup()`, `await stop()`, `setup_finished` property | connection lifecycle; e-stop calls stop() | yes |
| `pick_up_tips(tip_spots: List[TipSpot], use_channels=None, offsets=None)` | pick_up_tips | yes |
| `drop_tips(tip_spots: Sequence[TipSpot | Trash], use_channels=None, offsets=None, allow_nonzero_volume=False)` | drop_tips | yes |
| `aspirate(resources: Sequence[Container], vols: List[float], use_channels=None, flow_rates=None, ...)` | aspirate | yes |
| `dispense(...)` same parameters | dispense | yes |
| `move_plate(plate: Plate, to: ResourceStack | ResourceHolder | Resource | Coordinate, ...)` | move_plate with the iSWAP / CO-RE gripper | yes |
| `STAR(device_address=None, serial_number=None, packet_read_timeout=3, read_timeout=30, write_timeout=30)` (alias of `STARBackend`) | the real backend | yes |
| `STARBackend.request_cover_open() -> bool` (firmware `C0 QC`) | cover_open and robot_access_ready | yes |
| `MachineConfiguration.main_front_cover_monitoring_installed` | why cover_open may be null | yes (not called) |
| `STARChatterboxBackend(num_channels=8, ...)` in `backends/hamilton/STAR_chatterbox.py` | the twin when pylabrobot is installed | yes |
| `STARLetDeck()`, `STARDeck()` factory functions returning `HamiltonSTARDeck` | default decks | yes |
| `Resource.get_resource(name) -> Resource` (raises ResourceNotFoundError) | name resolution | yes |
| `ItemizedResource.get_item("A1") -> item` (`plate["A1"]` returns a list) | well and tip-spot resolution | yes |
| `Deck.load_from_json_file(path)` | loading the deck layout file | **unverified** (PyLabRobot documents `lh.deck.save` and `Resource.load_from_json_file`; confirm the exact classmethod on the installed version) |

Volumes: Hamilton 1000 uL CO-RE channels pipette 0.5-1000 uL (PyLabRobot tip definitions:
`hamilton_tip_1000uL` maximal_volume 1250 / filter 1065, `hamilton_tip_300uL` 400 / 360,
`hamilton_tip_50uL` 65 / 60, `hamilton_tip_10uL` 15 / 10). The channel range 0.5-1000 uL is
Hamilton's published figure for the 1000 uL channel and was not read from a document in this pass
(unverified); the lab sets the real limits per installed channel.
