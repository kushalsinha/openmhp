---
name: openmhp-adapt-fleet
description: Bring a whole fleet of devices already controlled by SiLA 2, PyLabRobot, MADSci, OPC UA (or Modbus/PLCs), or ROS 2 under the Open Model Hardware Protocol using the openmhp adapters, then publish them through a directory and the mhp-mcp bridge so any agent harness can operate them. Use when a user mentions SiLA, PyLabRobot, MADSci, OPC UA, Modbus, ROS 2, a workcell, a fleet, "connect all our instruments", or wants an MCP server for their lab or factory.
license: Apache-2.0
compatibility: Requires Python 3.10+ and openmhp. Vendor client libraries (sila2, pylabrobot, asyncua or opcua, rclpy) are needed only at run time on the machine that talks to the hardware.
metadata:
  author: openmhp
  version: "0.2"
---

# Bring a fleet under OpenMHP

Goal: every device becomes an MHP server (a few lines each), a directory indexes them, and
one `mhp-mcp` process exposes the lab to agents through eight tools, whatever the fleet size.

## Step 1. Inventory

Get from the user, per control layer: how to reach it (hosts, ports, node names, URLs), and a
list of devices with the four facts a card needs: id, class, location, one-line notes. Read the
matching reference before writing code:

- SiLA 2: [references/sila2.md](references/sila2.md)
- PyLabRobot: [references/pylabrobot.md](references/pylabrobot.md)
- MADSci: [references/madsci.md](references/madsci.md)
- OPC UA / PLCs: [references/opcua.md](references/opcua.md)
- ROS 2: [references/ros2.md](references/ros2.md)

MADSci nodes describe themselves; the other four need a short binding map per device. Ask
the owner the safety questions from the `openmhp-onboard-device` skill (limits, interlocks,
what needs a human, how it stops) for every device that moves or heats. Adapters do not
exempt a device from the gates: a layer without limits still gets limits in MHP.

## Step 2. One device package per device

Create `devices/<device-id>/` with a `DEVICE.md` (frontmatter card + operating instructions,
template in the `openmhp-onboard-device` skill) and a `driver.py` that builds the driver with
the ecosystem's adapter and exposes it as `DEVICE`. Identity from the frontmatter is merged in,
so the adapter call carries only the bindings. Example (SiLA 2):

```python
# devices/arm-01/driver.py
from openmhp.adapters.sila2 import sila_device
DEVICE = sila_device("10.0.0.12", 50052, device={},
    signals={"position": "RobotController.Position",
             "safe_zone_clear": ("SafetyController.SafeZoneClear", "boolean")},
    settings={"speed": ("RobotController.SetSpeed.Speed", {"min": 1, "max": 100})},
    actions={"move_to": ("RobotController.MoveTo", {"observable": True, "interlocks": ["safe_zone_clear"]})},
    estop="RobotController.EmergencyStop")
```

Put the owner's SOP under `references/` and one tested run under `scripts/`. Serve the package
on the machine that can reach the hardware:

```bash
mhp serve pkg:devices/arm-01 --http 18921
```

For many devices on one host, [scripts/serve_fleet.py](scripts/serve_fleet.py) serves every
package folder you list, one port each.

## Step 3. Directory

Build the manifest once from the running servers, then serve it:

```bash
python scripts/build_manifest.py fleet.json arm-01=http://bay3-pc:18921 star-01=http://bay1-pc:18921 ...
mhp serve-directory fleet.json --http 18900
mhp http://localhost:18900 find plates bay 3          # ranked cards, live state
```

The directory pings candidates at query time, so `state` filters are truthful even if the
manifest is a week old. Re-run `build_manifest.py` when devices are added or renamed.

## Step 4. Expose to agents

One bridge, eight tools, any harness:

```bash
mhp-mcp --directory http://localhost:18900                # stdio (Claude Code, Claude Desktop, Cursor...)
mhp-mcp --directory http://localhost:18900 --http 18800   # Streamable HTTP for remote harnesses
```

```json
{"mcpServers": {"lab": {"command": "mhp-mcp", "args": ["--directory", "http://localhost:18900"]}}}
```

## Step 5. Prove it

For each device class, run through the bridge or CLI: `describe card`, an in-range write, an
out-of-range write (must be refused, code -32010), an action with `--dry-run`, and `estop`
followed by `reset`. Record the results next to the manifest.

## Checklist

- [ ] every device is a package: frontmatter complete, DEVICE.md procedure written, numeric settings have limits
- [ ] energetic actions have interlocks or `approval: confirm`; estop wired or explicitly declined
- [ ] directory finds each device by a plain-language query; live state reflects a busy device
- [ ] `mhp-mcp` shows exactly eight tools; `mhp_find` then `mhp_describe` reach every device
