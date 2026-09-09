# MADSci → MHP

`openmhp.adapters.madsci.madsci_node(url, *, device, approval=None, http=None, paths=MadsciPaths)`

MADSci nodes are self-describing, so no binding map is needed:

```python
from openmhp.adapters.madsci import madsci_node
DEVICE = madsci_node("http://192.168.1.40:2000",
    device={"id": "pf400-01", "class": "robot_arm", "location": "bay 2", "tags": ["plates", "motion"],
            "notes": "MADSci-managed PF400. Only SBS plates."},
    approval={"transfer": "auto", "free_drive": "forbid"})
```

| MADSci | MHP |
|---|---|
| `GET /info` actions + args | actions with `params`, descriptions as `notes` |
| `GET /state` keys | signals |
| `GET /status` busy/errored | folded into `ping` state |
| `POST /action`, `GET /action/{id}` | `actions/invoke` → job polling |
| `POST /admin/safety_stop` | `safety/estop` |

If your MADSci version uses different paths, subclass `MadsciPaths` and pass `paths=`.
MADSci workcell managers can also be *hosts*: point them at the MHP directory instead of
per-node REST and they gain the same gates and cards.
