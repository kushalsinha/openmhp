# SiLA 2 → MHP

`openmhp.adapters.sila2.sila_device(host, port, *, device, signals, settings, actions, estop, insecure=True, client=None)`

Requires `pip install sila2` at run time. Discover features first:

```python
from sila2.client import SilaClient
c = SilaClient("10.0.0.12", 50052, insecure=True)
print(c.SiLAService.ImplementedFeatures.get())      # fully qualified feature identifiers
```

| MHP | Binding value | SiLA element |
|---|---|---|
| signal | `"Feature.Property"` or `("Feature.Property", "boolean")` | property, observable or not (`.get()`) |
| setting | `"Feature.Command.Parameter"` or `(path, {min,max})` | unobservable command with one parameter |
| action | `"Feature.Command"` or `(path, {"observable": True, "interlocks": [...], "approval": ...})` | command; observable ones stream progress and accept cancel |
| estop | `"Feature.Command"` | any command that stops the device |

Notes
- MHP leases replace SiLA LockController; do not also lock from another client.
- SiLA metadata (auth tokens) is not passed in 0.2; inject a pre-configured `client=` if the server needs it.
- Feature descriptions are good `notes`; paste the ones the owner agrees with.
