# PyLabRobot → MHP

`openmhp.adapters.pylabrobot.plr_device(machine, *, device, actions=None, signals=None, limits=None, approval=None, setup=True)`

Works with any `Machine`: `LiquidHandler`, `PlateReader`, `Centrifuge`, `Incubator`, `HeaterShaker`, `Tilter`.

```python
from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STAR
from pylabrobot.resources import STARLetDeck
from openmhp.adapters.pylabrobot import plr_device

lh = LiquidHandler(backend=STAR(), deck=STARLetDeck())
DEVICE = plr_device(lh,
    device={"id": "star-01", "class": "liquid_handler", "location": "bay 1", "tags": ["pipetting", "plates"],
            "notes": "Hamilton STARlet. Keep the deck clear of loose tips; 8-channel head only."},
    actions=["pick_up_tips", "drop_tips", "aspirate", "dispense", "move_plate", "move_lid"],
    limits={"aspirate": {"vols": [0, 1000]}, "dispense": {"vols": [0, 1000]}},
    approval={"move_plate": "auto"})
```

- Omit `actions` to expose every public coroutine on the machine; name them to expose fewer.
- `params` are documented from the Python signature; add `notes` by editing the descriptor after
  construction if the docstring is thin: `DEVICE.descriptor["actions"][0]["notes"] = "..."`.
- Resources (plates, tips) are passed by name in `params`; the adapter does not resolve deck
  objects. Wrap `machine` in a thin class whose coroutines take names and look up resources on
  the deck when the agent should not need PyLabRobot object graphs.
- `setup()` runs when the driver starts; `stop()` is the e-stop.
