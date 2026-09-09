# OpenMHP

Reference implementation of the **Open Model Hardware Protocol (MHP)**: an
open protocol through which an AI agent finds a physical device among
thousands, learns how to operate it safely, reads from it, writes to it, and
runs long actions on it.

MHP is to instruments and machines what MCP is to software tools, with two
lessons from MCP's first year built in from the start: the agent's context
stays flat as the lab grows, and safety is enforced on the device side of the
wire.

| Primitive | Verb | Example |
|---|---|---|
| **Directory** | `directory/search` | "something idle that can heat a 96-well plate to 95 °C in bay 12" → 5 cards |
| **Describe** | `device/describe {detail, select}` | card (~40 tokens) → summary (~200) → full spec of the two items you'll use |
| **Signals** | `signals/read`, `signals/subscribe` | block temperature, arm position, lid state |
| **Settings** | `settings/write` | target temperature = 95 °C, refused above 105 |
| **Actions** | `actions/invoke` → job | run PCR protocol, pick plate; device does the work |
| **Safety** | `safety/limits`, `safety/estop`, `safety/reset` | limits, interlocks, approval levels, e-stop, watchdog |

Python ≥ 3.10; PyYAML is the only dependency.

## Try it in 60 seconds

```bash
pip install -e .

# 1. code file: orchestrate a robot arm and a thermocycler
python examples/pcr_run.py

# 2. scale: 2,000 devices, find the right one for 1,087 tokens instead of 937,845
python examples/scale_demo.py

# 3. CLI: run devices and a directory over HTTP
mhp serve local:openmhp.devices.sim_thermocycler:SimThermocycler --http 18921 &
mhp serve local:openmhp.devices.sim_arm:SimArm --http 18922 &
mhp serve-directory thermo=http://localhost:18921 arm=http://localhost:18922 --http 18900 &
mhp http://localhost:18900 find pick plates                 # directory search
curl localhost:18921/mhp.json                               # discovery document
mhp http://localhost:18921 describe card                    # card | summary | full
mhp http://localhost:18921 write target_temperature 200     # refused: LimitViolation
mhp http://localhost:18921 invoke run_protocol '{"steps":[{"temp":95,"hold_s":5}],"cycles":3}' --wait
mhp http://localhost:18921 estop

# 4. MCP: expose the whole lab to any agent harness through eight tools, whatever its size
mhp-mcp --directory http://localhost:18900                # stdio
mhp-mcp --directory http://localhost:18900 --http 18800   # MCP Streamable HTTP at /mcp

# 5. adapters + live directory, verified against fakes (no hardware)
python tests/test_adapters.py
```

## Already running SiLA 2, PyLabRobot, MADSci, OPC UA or ROS 2?

Each device is a few lines with the matching adapter; every gate, tier and job comes for free:

```python
from openmhp.adapters.sila2 import sila_device            # also: pylabrobot.plr_device,
DEVICE = sila_device("10.0.0.12", 50052,                  # madsci.madsci_node, opcua.opcua_device,
    device={"id": "arm-01", "class": "robot_arm", "location": "bay 3", "tags": ["plates"],   # ros2.ros2_device
            "notes": "PF400 plate mover. Light curtain trips safe_zone_clear."},
    signals={"position": "RobotController.Position", "safe_zone_clear": ("SafetyController.SafeZoneClear", "boolean")},
    settings={"speed": ("RobotController.SetSpeed.Speed", {"min": 1, "max": 100})},
    actions={"move_to": ("RobotController.MoveTo", {"observable": True, "interlocks": ["safe_zone_clear"]})},
    estop="RobotController.EmergencyStop")
```

Anything else with a Python callable goes through `BoundDriver(Signal, Setting, Action)` directly.

## Agent Skills

`skills/` holds three [Agent Skills](https://agentskills.io) any skills-capable harness can load:

| Skill | Use it to |
|---|---|
| `openmhp-onboard-device` | interview a device owner and write a validated descriptor + driver |
| `openmhp-adapt-fleet` | bring a SiLA 2 / PyLabRobot / MADSci / OPC UA / ROS 2 fleet under MHP, build the directory, publish `mhp-mcp` |
| `openmhp-operate` | run experiments safely through the eight tools: find → describe → check → dry-run → act → verify |

Point your harness's skills directory at `skills/` (for Claude Code: copy or symlink into `.claude/skills/`).

Claude Desktop / Claude Code config for the bridge:

```json
{"mcpServers": {"lab": {"command": "mhp-mcp", "args": ["--directory", "http://directory:18900"]}}}
```

The bridge exposes `mhp_find`, `mhp_describe`, `mhp_read`, `mhp_write`,
`mhp_invoke`, `mhp_job`, `mhp_estop` and `mhp_run` (run a script against the
lab, get back only what it prints). Every tool carries `input_examples`. There
are never per-device tools.

## A device is a package, like a skill

```
devices/thermocycler-01/
├── DEVICE.md          Level 1: YAML frontmatter = the card (~40 tokens in search results)
│                      Level 2: Markdown body = operating instructions (loaded when chosen)
├── descriptor.yaml    Level 3: limits, interlocks, params, examples (loaded per item)
├── driver.py          Level 3: code
├── references/        Level 3: SOPs, manual excerpts
└── scripts/           Level 3: tested mhp_run scripts
```

```bash
mhp serve pkg:openmhp/devices/thermocycler-01 --http 18921
mhp http://localhost:18921 describe card        # level 1
mhp http://localhost:18921 describe summary     # level 2, with instructions
mhp http://localhost:18921 resources scripts/pcr.py   # level 3
```

## Writing a driver

A driver is a package plus three hooks. Everything else (limit checks,
interlocks, approval gating, leases, jobs, e-stop, notifications, detail
tiers) is inherited.

```python
from openmhp.driver import Driver

class MyHotplate(Driver):
    descriptor = {
        "device":   {"id": "hotplate-01", "class": "hotplate", "make": "IKA", "model": "C-MAG",
                     "location": "fume hood 2", "tags": ["heating", "stirring"],
                     "notes": "Fume hood 2. Stir bar rattles above 800 rpm with 50 mL flasks."},
        "physical": {"mass_kg": 3.2, "notes": "Plate surface reaches 500 °C; keep solvents capped."},
        "signals":  [{"name": "plate_temperature", "type": "number", "unit": "degC"}],
        "settings": [{"name": "target_temperature", "type": "number", "unit": "degC",
                      "limits": {"min": 20, "max": 300}, "approval": "auto"},
                     {"name": "stir_rpm", "type": "number", "limits": {"min": 0, "max": 1500}}],
        "actions":  [{"name": "shutdown", "duration": "short", "approval": "confirm"}],
        "safety":   {"estop": True, "watchdog_s": 5},
    }
    def setup(self):                    self.dev = serial.Serial("/dev/ttyUSB0")
    def on_read(self, name):            return float(self.dev.query("IN_PV_1"))
    def on_write(self, name, value):    self.dev.write(f"OUT_SP_1 {value}")
    def on_invoke(self, job):           self.dev.write("STOP")
    def on_estop(self):                 self.dev.write("STOP")
```

```bash
mhp serve mypkg.hotplate:MyHotplate --http 18921
```

## Layout

```
openmhp/driver.py        Driver base class: primitives, safety gates, jobs, leases, detail tiers, resources
openmhp/package.py       device packages: DEVICE.md frontmatter + body, descriptor.yaml, resources
openmhp/directory.py     Directory: card index + BM25 search + live state pings; serves directory/*
openmhp/adapters/        BoundDriver bindings; sila2, pylabrobot, madsci, opcua, ros2 adapters
skills/                  Agent Skills: onboard-device, adapt-fleet, operate
tests/test_adapters.py   adapters and live directory against injected fakes
openmhp/transport.py     stdio and HTTP(+SSE) transports; /mhp.json discovery
openmhp/client.py        Device / Lab client SDK (local, stdio, http); Lab is lazy and directory-aware
openmhp/cli.py           `mhp` command, incl. serve and serve-directory
openmhp/mcp_bridge.py    `mhp-mcp`: eight tools, constant in device count; mhp_run
openmhp/devices/         simulated thermocycler and robot arm, each as a device package
examples/pcr_run.py      cross-device orchestration script
examples/scale_demo.py   2,000 devices; context cost old way vs MHP way
docs/spec.html           the specification, rendered
SPEC.md                  the specification, Markdown
```
