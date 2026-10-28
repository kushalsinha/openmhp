---
name: openmhp-onboard-device
description: Put one physical device (instrument, robot, PLC-controlled machine) under the Open Model Hardware Protocol by interviewing its owner and writing a device package: DEVICE.md (card + operating instructions), descriptor.yaml (limits, interlocks, approvals) and a driver. Use when a user wants to connect, onboard, expose, or "make agent-controllable" a lab instrument or factory machine, or asks to write an MHP driver, device descriptor, DEVICE.md, safety limits, or interlocks for hardware.
license: Apache-2.0
compatibility: Requires Python 3.10+ and the openmhp package (pip install -e . from the OpenMHP repo). No hardware needed to write and validate the package.
metadata:
  author: openmhp
  version: "0.6"
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

- **Already controlled by OPC UA, ROS 2, SiLA 2, MADSci or PyLabRobot?** Use `openmhp-adapt-fleet`
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
   agent go silent → `watchdog_s`, and what should happen then → `watchdog_action`: `estop` for an
   instrument that is only safe while something is minding it, `release` for one whose work must
   not be interrupted (it hands the instrument over and keeps running). Declaring a window is also
   what makes a lease mandatory, so do not switch it off to avoid an unwanted stop.
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
physical limits, report `self.progress(job, f)`, check `job.cancel_requested`.

**Four rules about safety values.** A device keeps two copies of its configuration: `descriptor`,
which it reports, and a sealed copy the gates actually read. They are separate because they used
to be the same, and a caller handed a bound could raise it by assigning to the answer it was
given — `dev.limits()["settings"]["x"]["max"] = 900`, and 900 was enforced. A run script is handed
that API on purpose and an agent writes run scripts, so the base `Driver` keeps the two apart. A
driver reopens the hole like this:

- **Never assign to `self.descriptor` outside `setup()`**, and never to `_enforced`, `_index` or
  `_seal_digest` at all. `setup()` is allowed because it runs inside the load path and the driver
  re-seals after it, which is how a driver that discovers its own channels declares them. An edit
  anywhere else lands after the seal and now stops the device (`-32013`) rather than being obeyed.
- **Never override `_gate`, `_verify_seal`, `_reindex` or a `_check_*` method.** Those are the
  gates, not extension points.
- **If you add or override an RPC that returns descriptor material, return `copy.deepcopy(...)`.**
  A reported bound is a copy, not a handle on the bound being enforced.
- **Answer writes through the gates, not instead of them.** `on_write` runs after the gates; it is
  not the place to decide whether a value is allowed.

Changing a safety value is a person editing the package and the lab accepting it
(`mhp_lab op='reload'`), never a runtime call — there is no API for it, and the package's
fingerprint covers file contents, so an edited package is not enforced until someone accepts the
diff. Scripts you ship in `scripts/` run in the run sandbox: they get `lab`, and importing
`openmhp` or `gc`, or writing a package folder or the host's home, is refused and logged.

For bindings:

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

## Step 7. Check it the way the repository checks it

```bash
mhp inclusion devices/<id>            # or python scripts/check_inclusion.py devices/<id>
```

This runs the package's twin and reports two tiers. **Package** is the bar for any package,
including one that never leaves the lab: the validator, the four driver rules from step 5 checked
in the source, and behavioural proof that the gates refuse what they declare and that no answer
the device gives is a handle on what it enforces. **Submission** is what this repository
additionally needs to ship the package. `[-]` in the report means skipped because it does not
apply here, with the reason — a skip is not a pass. Field-by-field meanings and how to fix each
failure: [references/inclusion.md](references/inclusion.md).

Run `mhp conformance pkg:devices/<id>` as well. It scores the device against the SPEC 15 levels
and is safe against hardware; the level a package claims is what its status line rests on.

## Checklist

Authoring, for any device:

- [ ] frontmatter complete; description says what it is and when to pick it
- [ ] DEVICE.md body has procedure, what to watch, resources
- [ ] every numeric setting has limits; every energetic action gated; examples present
- [ ] `on_estop` does something real, or `safety.estop: false` and `safety.notes` says what stops it
- [ ] a watchdog window, unless the device is operator-run and the notes say so
- [ ] no assignment to `self.descriptor` outside `setup()`, none to `_enforced`/`_index`; no gate
      overridden; any descriptor material an added RPC returns is deep-copied
- [ ] `mhp inclusion <folder>` Package tier passes, with every `[-]` skip read and accepted
- [ ] owner reviewed DEVICE.md

To be included in `supported-devices/`, additionally:

- [ ] `sim.py` twin that loads with no vendor library and no `config.json`
- [ ] `references/setup.md` with the vendor library, the host, and a first-hardware-test section
- [ ] `config.example.json` shipped, `config.json` never committed
- [ ] entry in `openmhp/registry.json`; row in `supported-devices/README.md` with an honest status
- [ ] the twin exercised in `tests/test_adapters.py`
- [ ] `mhp inclusion <folder>` Submission tier passes too
