<!-- generated from https://openmhp.com/add-a-device by scripts/build_guide.py; edit the website, not this file -->

# Add an instrument

How to put a new instrument or machine under OpenMHP so that any AI agent harness can find it, understand it, and operate it within the limits you set. One folder, a few files, no changes to the agent.

An MHP device is a **device package**: a folder shaped like an Agent Skill. What you write loads into the agent in three levels, each only when needed.

```
devices/hotplate-01/
├── DEVICE.md          Level 1: YAML frontmatter, the card     (what agents see in search results)
│                      Level 2: Markdown body, operating instructions (loaded when an agent picks it)
├── descriptor.yaml    Level 3: signals, settings with limits, actions, interlocks, safety
├── driver.py          Level 3: the code that talks to the hardware
├── references/        Level 3: SOPs, manual excerpts, calibration tables (optional)
└── scripts/           Level 3: tested end-to-end runs for mhp_run (optional)
```

## The easy way: let your agent do it

After `npx -y openmhp-cli@latest setup`, three sentences cover most instruments:

1. **"Find the instruments on my network."** The agent runs `mhp_lab scan`. Anything already serving MHP (a bench PC running `mhp serve`, a vendor device with MHP built in, a SiLA 2 or OPC UA adapter) shows up with its card.

2. **"Add the thermocycler."** `mhp_lab add`. It is in your lab and searchable from now on.

3. **"Onboard my hotplate."** For an instrument with no MHP address yet, the OpenMHP server runs a short interview through your agent: about ten questions, in plain words, one at a time. What is it? How is it controlled today? What is it for and not for? Where is it? What can be read, what can be set and within what range, what can it do, what must be true first, how do you run it, how do you stop it? You answer as you would to a new colleague; the agent turns your words into structure. Then the server writes DEVICE.md, descriptor.yaml and driver.py itself, validates them, and the agent adds the instrument and reads the operating procedure back to you for review. The package lives in `~/.openmhp/devices/` and is hosted by the server, so nothing else needs to run.

Two shortcuts before any interview. **"Is there a package for the IKA C-MAG?"** searches the community registry; if one exists, `add` pulls it from GitHub and you only set its location and port. **"Add its simulated twin"** registers the package's `sim.py` so you can rehearse a protocol with nothing plugged in. A shared package cannot know where your instrument stands, so the agent asks and records that with the device, which is what location searches use afterwards. And after any onboarding the agent reads you a **safety card**: the limits the driver will enforce, which actions need a person, whether an emergency stop exists, and the result of probing the device with an out-of-range request.

### No code needed for most bench instruments

The interview asks how the instrument is controlled today and picks a driver for you.

| If the instrument is… | You get |
|---|---|
| operated by hand at the bench | a **manual** driver. The agent tells the operator what to set or start, and records what they read off the display. The instrument takes part in protocols today, with every safety limit enforced; a real driver can replace one file later. |
| connected by a serial or USB cable with text commands | a **serial** driver. You paste the read, write and action commands from the manual (or let the agent find them); the driver sends them and parses the replies. No programming. |
| already at an OpenMHP address on the network | added directly, no package to write. |
| driven by OPC UA, ROS 2, SiLA 2, MADSci or PyLabRobot | the interview still produces the card and instructions; a technician finishes `driver.py` with an [adapter](https://openmhp.com/adapters) in a few lines. |

This works in any harness that speaks MCP, with or without Agent Skills: the server tells the agent how to run the interview, and ships `setup-my-lab`, `add-instrument` and `run-experiment` as MCP prompts that most harnesses show as slash commands.

The rest of this page is what the server writes, so you can do it by hand, check its work, or serve the result from a bench PC for the whole lab.

## By hand

### Gather what only the owner knows

Before writing anything, answer these. They become the package.

   - What is it, and when should an agent pick it over the alternatives? What is it *not* for?

   - Where does it sit? Which tags would someone search for?

   - How do you run it, step by step? What do you check first, what do you watch, how do you leave it safe?

   - What can be read (each value with its unit)? What can be set, and the range you would never leave?

   - What must be true before it runs: lid closed, door closed, homed, nobody in the cell?

   - What should always need a human? What should an agent never do?

   - How does it stop in an emergency? How long may an agent go silent before it should fail safe?

### Write DEVICE.md

The frontmatter is the card. `description` must say both what the device is and when to pick it, in under 1,024 characters; it is the text a directory ranks against the agent's request. The body is for the agent that has just chosen the device.

```
---
mhp: "2026-09-12"
id: hotplate-01
class: hotplate
make: IKA
model: C-MAG HS 7
location: fume hood 2
tags: [heating, stirring, chemistry]
description: Magnetic stirrer hotplate, 20 to 300 degC plate, 0 to 1500 rpm. Use for heating and
  stirring capped flasks up to 500 mL in fume hood 2. Not for open solvents above 60 degC and
  not for anything needing temperature feedback inside the vessel.
driver: driver.py:Hotplate
---

# Hotplate-01

Sits in fume hood 2 on the left. The plate surface reaches 500 °C even when the setpoint is
300 °C, because the setpoint is the plate probe, not the surface. Keep solvents capped.

## Operating procedure
1. Read `sash_closed`; heating refuses while the sash is up.
2. Write `stir_rpm` before `target_temperature` so the bar is moving as heat arrives.
3. Write `target_temperature`. Ramp is about 2 °C/s; read `plate_temperature` to confirm.
4. When done, write `target_temperature` 20 and `stir_rpm` 0, then invoke `shutdown`.

## What to watch
- The stir bar rattles above 800 rpm with 50 mL flasks; lower the speed if `stir_rpm` reads unstable.
- `shutdown` cuts the heater relay; it needs a human to confirm because the plate stays hot.

## Resources
- `references/sop.md`: the lab's SOP for reflux setups.
- `scripts/reflux.py`: heat to setpoint, hold, cool, shut down.
```

### Write descriptor.yaml

The machine-readable half. Identity comes from the frontmatter, so this file holds only what the driver enforces or serves. Every numeric setting needs `limits`. Every action that heats or moves needs `interlocks` or `approval: confirm`.

```
physical:
  mass_kg: 3.2
  notes: Plate surface up to 500 degC. Keep solvents capped.

signals:
  - name: plate_temperature
    type: number
    unit: degC
  - name: sash_closed
    type: boolean
    notes: Fume hood sash interlock.

settings:
  - name: target_temperature
    type: number
    unit: degC
    limits: {min: 20, max: 300}      # the driver refuses anything outside
    interlocks: [sash_closed]
    approval: auto
  - name: stir_rpm
    type: number
    unit: rpm
    limits: {min: 0, max: 1500}

actions:
  - name: shutdown
    duration: short
    approval: confirm                 # a human must say yes to each call
    notes: Cuts the heater relay. Plate stays hot for minutes.

safety:
  estop: true
  interlocks: [sash_closed]
  watchdog_s: 10
  notes: E-stop opens the heater relay and stops the stirrer.
```

Approval levels: `auto` (the agent may act), `confirm` (each call needs a human's yes, passed back as `approved: true`), `forbid` (listed so the agent knows it exists, never agent-operable). Full field rules are in the [specification](https://openmhp.com/spec#descriptor).

### Write driver.py

Pick the route that matches your hardware. All three give you every safety gate, the three describe levels, jobs, notifications and e-stop from the base class. You never re-implement limit checks.

#### Route A: native driver (vendor API, serial, SDK)

```
from openmhp.driver import Driver, Job
import serial

class Hotplate(Driver):
    def setup(self):
        self.dev = serial.Serial("/dev/ttyUSB0", 9600, timeout=1)

    def on_read(self, name):
        cmd = {"plate_temperature": "IN_PV_1", "sash_closed": "IN_SASH"}[name]
        return float(self._query(cmd))

    def on_write(self, name, value):           # limits already checked by the base class
        cmd = {"target_temperature": "OUT_SP_1", "stir_rpm": "OUT_SP_4"}[name]
        self._query(f"{cmd} {value}")

    def on_invoke(self, job: Job):             # runs in a worker thread; report progress, honour cancel
        if job.action == "shutdown":
            self._query("STOP_1"); self._query("STOP_4")
            return {"heater": "off"}

    def on_estop(self):
        self._query("STOP_1"); self._query("STOP_4")

    def _query(self, cmd):
        self.dev.write((cmd + "\\r\\n").encode()); return self.dev.readline().decode().strip()
```

#### Route B: bindings (you already have Python callables)

```
from openmhp.adapters import BoundDriver, Signal, Setting, Action
DEVICE = BoundDriver(device={},                       # identity is merged in from DEVICE.md
    signals=[Signal("plate_temperature", read=plc.read_pv, unit="degC"),
             Signal("sash_closed", read=plc.sash, type="boolean")],
    settings=[Setting("target_temperature", write=plc.set_sp, limits={"min": 20, "max": 300}, interlocks=["sash_closed"])],
    actions=[Action("shutdown", run=lambda job, p: plc.off(), approval="confirm")],
    estop=plc.off)
```

#### Route C: an adapter (OPC UA, ROS 2, SiLA 2, MADSci, PyLabRobot)

```
from openmhp.adapters.opcua import opcua_device
DEVICE = opcua_device("opc.tcp://hood2-plc:4840", device={},
    signals={"plate_temperature": ("ns=2;s=HP.PV", "degC"), "sash_closed": ("ns=2;s=Hood.Sash", "boolean")},
    settings={"target_temperature": ("ns=2;s=HP.SP", {"min": 20, "max": 300}, "degC")},
    actions={"shutdown": ("ns=2;s=HP", "ns=2;s=HP.Off", {"approval": "confirm"})},
    estop=("ns=2;s=HP", "ns=2;s=HP.Off"))
```

For routes B and C, omit the `driver:` line in the frontmatter; the loader finds `DEVICE`. See [Adapters](https://openmhp.com/adapters) for each ecosystem's binding shape.

### Add references and a tested script

Drop the SOP or manual pages into `references/` as Markdown or text. Put one end-to-end run you have actually tested into `scripts/`, written for `mhp_run`: it sees `lab` and should print one summary line. Mention both in the DEVICE.md "Resources" list. Agents read these only when they need them, so there is no cost to including a lot.

```
# scripts/reflux.py
hp = lab["hotplate-01"]
with hp:
    hp.write("stir_rpm", 400)
    hp.write("target_temperature", 80)
    while hp.read("plate_temperature") < 78: time.sleep(5)
    time.sleep(3600)
    hp.write("target_temperature", 20); hp.write("stir_rpm", 0)
print("reflux done; plate at", hp.read("plate_temperature"), "degC")
```

### Validate and serve

```
mhp validate devices/hotplate-01
mhp serve pkg:devices/hotplate-01 --http 18923
```

Then prove the gates from another terminal:

```
mhp http://localhost:18923 describe card                      # level 1 looks right?
mhp http://localhost:18923 describe summary                   # instructions present?
mhp http://localhost:18923 write target_temperature 350       # must be refused, code -32010
mhp http://localhost:18923 invoke shutdown --dry-run          # must say ApprovalRequired
mhp http://localhost:18923 estop && mhp http://localhost:18923 reset
```

### Register it in the directory

Add the new server to the manifest and restart the directory. From then on any agent can find it by describing what it needs.

```
python openmhp/skills/openmhp-adapt-fleet/scripts/build_manifest.py fleet.json \
    hotplate-01=http://hood2-pc:18923 thermocycler-01=http://bench3:18921 arm-01=http://bench3:18922
mhp serve-directory fleet.json --http 18900
mhp http://localhost:18900 find heat and stir a flask in the fume hood
```

Nothing changes on the harness side. The bridge still exposes the same eleven tools; the new instrument simply appears in `mhp_find` results.

To serve this package from the computer it is wired to, so it stays up without a terminal open, see [lab nodes](https://openmhp.com/lab-nodes).

### Verify from the agent

In your harness, ask for something the instrument does and something it must refuse. Confirm that the agent read the operating procedure (it should mention the sash), that the out-of-range request came back to you, and that the `confirm` action asked for your yes. Then hand DEVICE.md to the instrument owner for review, and commit the folder: changing a limit is a code review, not a runtime action.

## Checklist

- frontmatter complete; description says what it is and when to pick it

- DEVICE.md has an operating procedure, what to watch, and a resources list

- every numeric setting has limits; every energetic action has interlocks or needs confirmation

- validator passes; out-of-range write refused; e-stop wired

- every parameter is a typed shape with a UCUM unit, limits, and a default or `nullable` when optional; every long action declares `returns`

- `class` is a name from the [published vocabulary](https://openmhp.com/spec/classes): the snake_case label of an Allotrope, CHMO, OBI or NCIT term where one exists (`lyophilizer`, not `freeze_dryer`; `thermal_cycler`, not `thermocycler`), with `class_ref` for a narrower term such as a scanning electron microscope under `electron_microscope`; older names still load with a warning

- `state` and `busy` declared with `source: runtime`; the instrument self-state signals `calibration_status`, `qualification_status` and `usage_count` with `source: record` (the base answers them from `config.json`) or `source: instrument` where the device reports them ([spec §4.6](https://openmhp.com/spec/descriptor))

- `robot_access_ready` wherever a lid, door, tray or deck meets a handling robot; `physical.automated_load` said either way

- `mhp rubric <folder>`: every device-level procurement criterion Pass or honestly N/A (see [instruments supported](https://openmhp.com/instruments) for what the score means)

- directory finds it from a plain-language query; the owner has reviewed DEVICE.md
