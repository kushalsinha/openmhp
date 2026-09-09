# OPC UA (and PLC/Modbus by analogy) → MHP

`openmhp.adapters.opcua.opcua_device(url, *, device, signals, settings, actions, estop, client=None)`

Requires `pip install asyncua` (or `opcua`). Browse node ids first with UaExpert or:

```python
from asyncua.sync import Client
c = Client("opc.tcp://furnace-plc:4840"); c.connect()
for ch in c.get_objects_node().get_children(): print(ch, ch.read_browse_name())
```

```python
from openmhp.adapters.opcua import opcua_device
DEVICE = opcua_device("opc.tcp://furnace-plc:4840",
    device={"id": "furnace-02", "class": "oven", "location": "line 4", "tags": ["sintering", "heating"],
            "notes": "Sintering furnace. Door interlock is hardwired; MHP mirrors it as door_closed."},
    signals={"zone1_temperature": ("ns=2;s=Furnace.Zone1.PV", "degC"),
             "door_closed": ("ns=2;s=Furnace.DoorClosed", "boolean")},
    settings={"zone1_setpoint": ("ns=2;s=Furnace.Zone1.SP", {"min": 20, "max": 1400}, "degC")},
    actions={"start_program": ("ns=2;s=Furnace", "ns=2;s=Furnace.Start",
                               {"interlocks": ["door_closed"], "approval": "confirm",
                                "params": {"program": "int, recipe number"}})},
    estop=("ns=2;s=Furnace", "ns=2;s=Furnace.Abort"))
```

- Method arguments are passed positionally in the order of `params`; document every one.
- For Modbus, write two callables (`read_register`, `write_register`) and use `BoundDriver`
  directly; the shape is identical.
- PLC safety logic stays primary. MHP limits are the layer that stops an agent from *asking*.
