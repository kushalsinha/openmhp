---
name: openmhp-onboard-device
description: Put one physical device (instrument, robot, PLC-controlled machine) under the Open Model Hardware Protocol by interviewing its owner and writing a device package: DEVICE.md (card + operating instructions), descriptor.yaml (limits, interlocks, approvals) and a driver. Use when a user wants to connect, onboard, expose, or "make agent-controllable" a lab instrument or factory machine, or asks to write an MHP driver, device descriptor, DEVICE.md, safety limits, or interlocks for hardware.
license: Apache-2.0
compatibility: Requires Python 3.10+ and the openmhp package (pip install -e . from the OpenMHP repo). No hardware needed to write and validate the package.
metadata:
  author: openmhp
  version: "0.5"
---

# Onboard a device to OpenMHP

You will produce one **device package**, a folder shaped like a skill:

```
devices/<device-id>/
├── DEVICE.md          Level 1 frontmatter (the card) + Level 2 operating instructions
├── descriptor.yaml    Level 3: signals, settings with limits, actions, safety
├── driver.py          Level 3: Driver subclass, or DEVICE = <adapter>(...)
├── references/        Level 3: SOPs, manual excerpts, calibration tables (optional)
├── scripts/           Level 3: tested mhp_run scripts (optional)
└── methods/           Level 3: saved methods per project, only for instruments whose action is
                       marked `methods: true` (HPLC, GC, MS, PXRD, PCR programs); SPEC.md 4.5
```

Agents see the frontmatter in search results, the DEVICE.md body once they pick the device,
and the rest only when they ask. Write each level for that moment.

## Step 0. Let the server run the interview

The fastest path in any harness: call `mhp_lab op='onboard'`. The server returns the questions
(`ask`) and the answer shape; ask the human one question at a time in plain words, convert the
reply, send it back with `answers={...}`. When every required answer is in, the server writes
DEVICE.md, descriptor.yaml and driver.py, validates the package, and tells you to `op='add'`.
Instruments operated by hand (`kind: manual`) and serial/USB instruments (`kind: serial`) need
no code. If the owner has a manual or SOP, read it first and submit every answer it supports in
one `answers` call, then ask the human only to confirm limits and the procedure. The server
returns a safety card at the end: read it back to the owner before `op='add'`. Check
`mhp_lab op='registry'` first; a community package for the model may already exist. Use the
steps below when you are writing the package yourself, or to check the server's output.

## Two ways to write the package yourself

- **With file access** (a coding harness): write the folder under `~/.openmhp/devices/<id>/` (or the lab's repo) with your file tools.
- **Through MCP only**: use the `mhp_lab` tool. `op='new'` creates the skeleton, `op='write'` writes each file, `op='validate'` checks it, `op='add'` registers it. The rest of this skill applies to both.

Before writing anything, run `mhp_lab op='scan'` (or `mhp lab scan`): if the instrument already speaks MHP on the network, `add` it and stop here.

## Step 1. Decide the driver path

- **Already controlled by SiLA 2, PyLabRobot, MADSci, OPC UA or ROS 2?** Use `openmhp-adapt-fleet`
  for driver.py; still write DEVICE.md and descriptor.yaml here.
- **Vendor API, serial protocol or SDK?** Native Driver from [assets/driver_template.py](assets/driver_template.py).
- **A Python callable or two?** `BoundDriver` bindings (shown at the end).

## Step 2. Interview the owner

Ask in order. Do not invent answers.

1. **Identity and fit.** Make, model, id. Where it sits (bay, bench, room). Three to five tags.
   Then: *"In one or two sentences, what is it and when should an agent pick it over the
   alternatives? What is it not for?"* That answer is `description`.
2. **Procedure.** *"Walk me through a normal run, step by step."* That becomes the DEVICE.md body.
3. **Physics an agent cannot see.** Mass, footprint, payload, reach, power, hot or sharp
   surfaces, fragile parts.
4. **What can be read?** Each measurement, unit, where measured. → `signals`.
5. **What can be set?** Each setpoint, unit, the range you would never leave, and what happens
   at each end. → `settings` with `limits`.
6. **What can it do?** Each operation, how long, its parameters, one or two realistic parameter
   sets. → `actions` with `examples`.
7. **What must be true first?** Lid closed, homed, nobody in the cell. → boolean signals + `interlocks`.
8. **What always needs a human?** → `approval: confirm`; never by an agent → `approval: forbid`.
9. **How does it stop?** The command that cuts motion or energy → `on_estop`. How long may the
   agent go silent → `watchdog_s`.
10. **What documents exist?** SOPs, manual pages, calibration tables → `references/`.
11. **Does it run methods?** If an operation takes a named parameter set that changes per project
    or compound (an HPLC or GC method, a PCR program, a scan recipe), mark that action
    `methods: true`. The device then keeps methods under `methods/<project>/`, validates each one
    when it is saved, and asks the agent which to run. Ask for the standard ones now and save
    them under `_shared`.

## Step 3. Write DEVICE.md

Copy [assets/DEVICE.template.md](assets/DEVICE.template.md). Frontmatter rules: `id` lowercase
hyphenated and unique; `description` ≤ 1,024 characters saying what it is *and* when to pick it;
`location` and `tags` set; `driver: driver.py:ClassName` (omit for a `DEVICE =` adapter file).
Body rules: an "Operating procedure" list in the order the owner gave it; a "What to watch"
list with the signals to read and the failure modes; a "Resources" list naming every file under
`references/` and `scripts/` with one line each. Under 150 lines.

## Step 4. Write descriptor.yaml

Copy [assets/descriptor_template.yaml](assets/descriptor_template.yaml); field rules in
[references/descriptor.md](references/descriptor.md). Identity lives in the frontmatter, not
here. Every numeric setting has `limits`. Every action that moves or heats has `interlocks` or
`approval: confirm`. Actions carry `examples`.

## Step 5. Write driver.py

Vendor code lives only in `setup`, `on_read`, `on_write`, `on_invoke`, `on_estop`. The base class
runs the six safety gates before any hook. In `on_invoke`, validate parameters against the same
physical limits, report `self.progress(job, f)`, check `job.cancel_requested`. For bindings:

```python
from openmhp.adapters import BoundDriver, Signal, Setting, Action
DEVICE = BoundDriver(device={}, signals=[Signal("t", read=read_t, unit="degC")],
                     settings=[Setting("sp", write=set_sp, limits={"min": 4, "max": 105})],
                     actions=[Action("run", run=lambda job, p: do_run(p), duration="long")],
                     estop=stop_all)          # identity is merged in from DEVICE.md
```

## Step 6. Add resources, validate, serve, register

Put SOPs and tables in `references/`, and one tested end-to-end run in `scripts/` written for
`mhp_run` (it sees `lab`). Then:

```bash
python scripts/validate_package.py devices/<id>
mhp serve pkg:devices/<id> --http 18921
mhp http://localhost:18921 describe card                # level 1
mhp http://localhost:18921 describe summary             # level 2: instructions present?
mhp http://localhost:18921 resources                    # level 3 listing
mhp http://localhost:18921 write <setting> <out-of-range>   # must be refused (-32010)
mhp http://localhost:18921 invoke <action> --dry-run
```

Register the folder in the lab's directory manifest or `mhp-mcp` arguments, and hand the owner
DEVICE.md to review. Changing a limit later is a code review, not a runtime action.

## Checklist

- [ ] frontmatter complete; description says what it is and when to pick it
- [ ] DEVICE.md body has procedure, what to watch, resources
- [ ] every numeric setting has limits; every energetic action gated; examples present
- [ ] validator passes; card, summary and resources tiers return; out-of-range write refused
- [ ] `on_estop` does something real, or `safety.estop: false` and the owner agreed
- [ ] owner reviewed DEVICE.md
