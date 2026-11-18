<!-- generated from https://openmhp.com/adapters by scripts/build_guide.py; edit the website, not this file -->

# Adapters

If your instruments already answer to OPC UA, ROS 2, SiLA 2, MADSci, PyLabRobot, Modbus or MQTT, you do not write a driver. You write a few lines of bindings, and the adapter builds an MHP driver with every safety gate, describe level, job and e-stop included.

All six adapters rest on one mechanism. A **binding** pairs an MHP name with a callable into the foreign layer, and `BoundDriver` turns three lists of bindings into a complete driver. The ecosystem adapters just build those lists by introspecting their layer. Each adapter's mapping logic is tested against injected fakes; the exact client-library calls should be confirmed against a live system in your lab, and the paths are configurable for that reason.

| Layer | Function | What becomes what |
|---|---|---|
| **OPC UA** | `opcua_device` | variable node → signal or setting; method node → action; abort method → e-stop. Modbus uses `BoundDriver` with two register callables |
| **ROS 2** | `ros2_device` | topic subscription → signal; topic publication → setting; action server → action with feedback progress; Trigger service → e-stop |
| **SiLA 2** | `sila_device` | property → signal; one-parameter command → setting; command → action, observable commands stream progress and accept cancel |
| **MADSci** | `madsci_node` | self-describing: node info → actions with params and notes; state → signals; status → ping; no binding map needed |
| **PyLabRobot** | `plr_device` | every public coroutine on a Machine → action, params from its signature; `setup()` on start, `stop()` on e-stop |
| **MQTT** | `mqtt_device` | subscribed topic → signal, cached with its arrival time; published topic → setting; command topic + reply topic, correlated by a `job` field → action; without a reply topic an action is fire-and-forget |

Each device still gets a [device package](https://openmhp.com/add-a-device): the DEVICE.md frontmatter and instructions are what agents read, and the adapter call lives in `driver.py` as a module-level `DEVICE`. Identity from the frontmatter is merged in, so the adapter call carries only bindings.

## OPC UA and Modbus

```
from openmhp.adapters.opcua import opcua_device
DEVICE = opcua_device("opc.tcp://furnace-plc:4840", device={},
    signals={"zone1_temperature": ("ns=2;s=Furnace.Zone1.PV", "degC"),
             "door_closed": ("ns=2;s=Furnace.DoorClosed", "boolean")},
    settings={"zone1_setpoint": ("ns=2;s=Furnace.Zone1.SP", {"min": 20, "max": 1400}, "degC")},
    actions={"start_program": ("ns=2;s=Furnace", "ns=2;s=Furnace.Start",
                               {"interlocks": ["door_closed"], "approval": "confirm", "params": {"program": "int"}})},
    estop=("ns=2;s=Furnace", "ns=2;s=Furnace.Abort"))
```

Method arguments are passed positionally in the order of `params`. For Modbus, write two callables (read register, write register) and use `BoundDriver` directly. PLC safety logic stays primary; MHP limits are the layer that stops an agent from asking.

## ROS 2

```
from openmhp.adapters.ros2 import ros2_device
DEVICE = ros2_device("mhp_ur5e", device={},
    signals={"joint_positions": ("/joint_states", "sensor_msgs/msg/JointState", "position"),
             "estop_clear": ("/safety/estop_clear", "std_msgs/msg/Bool", "data")},
    settings={"speed_scale": ("/speed_scaling", "std_msgs/msg/Float64", "data", {"min": 0.05, "max": 1.0})},
    actions={"move_to_joints": ("/follow_joint_trajectory", "control_msgs/action/FollowJointTrajectory",
                                {"interlocks": ["estop_clear"], "duration": "long"})},
    estop=("/ur_hardware_interface/dashboard/stop", "std_srvs/srv/Trigger"))
```

Source your ROS 2 workspace first so `rclpy` and message packages import. Goal messages are built from `params`, so nested dicts must match the message layout; put an example in the action's `examples`.

## SiLA 2

```
# devices/arm-01/driver.py
from openmhp.adapters.sila2 import sila_device
DEVICE = sila_device("10.0.0.12", 50052, device={},
    signals={"position": "RobotController.Position",
             "safe_zone_clear": ("SafetyController.SafeZoneClear", "boolean")},
    settings={"speed": ("RobotController.SetSpeed.Speed", {"min": 1, "max": 100})},
    actions={"move_to": ("RobotController.MoveTo", {"observable": True, "interlocks": ["safe_zone_clear"]})},
    estop="RobotController.EmergencyStop")
```

Discover feature identifiers with `client.SiLAService.ImplementedFeatures.get()`. MHP leases replace SiLA's LockController; do not also lock from another client.

## MADSci

```
from openmhp.adapters.madsci import madsci_node
DEVICE = madsci_node("http://192.168.1.40:2000", device={},
                     approval={"transfer": "auto", "free_drive": "forbid"})
```

Nodes describe themselves through `/info`, `/state` and `/status`; the adapter needs no binding map. A MADSci workcell manager can also act as a host and point at the MHP directory instead of per-node REST.

## PyLabRobot

```
from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STAR
from pylabrobot.resources import STARLetDeck
from openmhp.adapters.pylabrobot import plr_device

lh = LiquidHandler(backend=STAR(), deck=STARLetDeck())
DEVICE = plr_device(lh, device={},
    actions=["pick_up_tips", "drop_tips", "aspirate", "dispense", "move_plate"],
    limits={"aspirate": {"vols": [0, 1000]}, "dispense": {"vols": [0, 1000]}})
```

Omit `actions` to expose every public coroutine. Resources are passed by name; wrap the machine in a thin class that looks names up on the deck if agents should not need PyLabRobot object graphs.

## MQTT

Many labs already stream what varies with time over MQTT: temperatures, pressures, door contacts, CO₂, flow, anything a sensor reports on a topic. The adapter leaves that broker and those topics as they are and lets an agent read the stream as signals, with the same limits, interlocks and e-stop rules as any other device.

```
from openmhp.adapters.mqtt import mqtt_device
DEVICE = mqtt_device("mqtt://broker.lab.local:1883", device={},
    signals={"temperature": ("lab/incubator-07/temperature", "degC"),
             "door_closed": ("lab/incubator-07/door", "boolean")},
    settings={"setpoint": ("lab/incubator-07/cmd/setpoint", {"min": 4, "max": 55}, "degC")},
    actions={"purge_co2": ("lab/incubator-07/cmd/purge", "lab/incubator-07/evt/purge",
                                {"approval": "confirm"})},
    estop=("lab/incubator-07/cmd/stop", None))
```

A subscribed topic becomes a signal, its last message cached with the time it arrived; older than the staleness window (5 s by default, set per signal) it reads as `None` rather than a guess, the same rule the ROS 2 adapter uses. A published topic becomes a setting; MQTT has no read-back for a plain publish, so pair a setting with a signal on the device's own state topic if it has one. An action publishes to a command topic with a `job` field for correlation; given a reply topic, it waits for a matching reply and returns its payload (a `status` of `failed` or `cancelled` raises accordingly); without one, it is fire-and-forget and returns once the broker has acknowledged the publish, which confirms delivery to the broker, not that the device acted. E-stop is the same trade-off, published at QoS 2 — pair it with a signal the device publishes back so a person or the agent can confirm from a live reading, the way the rest of MHP treats safety: a claim is evidence only once something read from the device shows it.

Needs `paho-mqtt` (`pip install -U "openmhp[mqtt]"`). Works with any broker your lab already runs; pass `client=` a pre-configured `paho.mqtt.client.Client` for auth, TLS, or a connection shared with other subscribers.

## Anything else: bindings

```
from openmhp.adapters import BoundDriver, Signal, Setting, Action
DEVICE = BoundDriver(device={},
    signals=[Signal("plate_temperature", read=lambda: plc.read(0x10), unit="degC")],
    settings=[Setting("target_temperature", write=lambda v: plc.write(0x20, v), limits={"min": 20, "max": 300})],
    actions=[Action("shutdown", run=lambda job, p: plc.write(0x21, 0), approval="confirm")],
    estop=lambda: plc.write(0x21, 0))
```

## A whole fleet

The `openmhp-adapt-fleet` skill walks a harness through an inventory, one package per device, a directory manifest and the bridge config, with a proof checklist at the end. By hand, the steps are: one folder per device as above, `mhp node <packages-dir> --http 18900` to serve every package under one directory from a single process (one port each, each auto-advertised on the LAN), `build_manifest.py` to index them, `mhp serve-directory`, then `mhp-mcp --directory`. A bench PC with several instruments needs exactly one running process this way, not one per device. Adapters do not exempt a device from the safety gates: a layer without limits still gets limits in MHP.

On the bench PC itself, the friendliest form of that is `mhp node add <package>` (or `npx -y openmhp-cli@latest node add <package>` with Node): it fetches the package, asks its questions, then installs `mhp node` as a background service (systemd on Linux, a LaunchAgent on macOS, your Startup folder on Windows) so the machine keeps serving whatever it is wired to across reboots, with no terminal left open and no agent running on that computer at all. `mhp node --service-status` and `mhp node --uninstall-service` manage it from there.
