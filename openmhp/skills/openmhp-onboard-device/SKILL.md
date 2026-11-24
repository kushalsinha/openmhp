---
name: openmhp-onboard-device
description: Put one physical device (instrument, robot, PLC-controlled machine) under the Open Model Hardware Protocol by interviewing its owner and writing a device package: DEVICE.md (card + operating instructions), descriptor.yaml (limits, interlocks, approvals) and a driver. Use when a user wants to connect, onboard, expose, or "make agent-controllable" a lab instrument or factory machine, or asks to write an MHP driver, device descriptor, DEVICE.md, safety limits, or interlocks for hardware.
license: Apache-2.0
compatibility: Requires Python 3.10+ and the openmhp package (npx -y openmhp-cli@latest setup, or pip install -U openmhp). No hardware needed to write and validate the package.
metadata:
  author: openmhp
  version: "0.7"
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
one `answers` call, then ask the human only to confirm limits and the procedure. A `manual`
package keeps every gate but swaps the hands: a setting write records a *request* for the
operator, an action parks in `waiting_operator` until someone runs the device-added
`acknowledge` action, and readings enter only through `record`. Both are `approval: confirm`, so
a person confirms each one (the CLI prints the `--approved` command; the SDK takes an approver) —
the instruction itself arrives as a `notifications/operator/instruction` event, and you relay it
to the person rather than act it. E-stop is a request to the operator, never an automatic stop,
and a manual device claims no watchdog. Protocols still sequence correctly: a protocol's `wait()`
blocks until the person acknowledges, and upgrading to a real driver later is a one-file change.
A `serial` package skips driver code, but the manual is a starting point, never the finished
integration: settings on a real instrument constrain each other, and firmware quietly drops or
ignores commands the manual lists. Probe every command from a Python script against the real
instrument first; keep `serial:` only for surfaces the probe confirmed decoupled, and once
couplings appear move the verified combinations into intent-level actions in a code driver
(`kind: adapter`) instead. The server
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
6.5 **How do you know a write took effect?** Does the instrument raise an error, clamp to the
   nearest valid value, or silently ignore an out-of-range or off-grid one? Is the accepted grid
   uniform (`resolution`) or a 1-2-5 sequence? → `settings` notes; the driver must read back
   after every write and diff the instrument's error queue (see Step 5).
6.6 **Which settings only mean something in a mode, or reshape others?** A trigger level bounded
   by the channel's volts/div; a depth that follows the timebase; a mode that locks or re-arms
   other settings. → `notes`; prefer wrapping such couplings in one intent-level action (see
   Step 5).
6.7 **How do you know a reading is current?** Does the instrument need settling time or a re-read
   before a value reflects the world? → the driver re-reads and compares before trusting a value.
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

**Verify every write.** Real firmware is not always honest: an out-of-range or off-grid value may
  be silently dropped with an empty error queue, or refused with a late `-200` after the write
  seemed to land. So a driver proves every write: read the setting back and compare with the
  intended value (cast both sides the same way — `1` is not `true`), diff the instrument's error
  queue around the write, and snap values to the instrument's grid (a 1-2-5 sequence, for
  example) before sending. Put this in one place every action shares, not in each caller.

**Wrap couplings in intent-level actions.** Many instruments are systems, not independent knobs:
  a trigger level is only valid within the channel's volts/div, an acquisition depth follows the
  timebase, a mode change re-arms or locks other settings. The dividing line: if a value's
  meaning depends on instrument state, do not leave it as a bare setting for callers to sequence.
  Write one action that states the intent (`configure_acquisition(duration_s=7)`), resolves the
  couplings against the live instrument, and returns what it actually allocated (scale, depth,
  sample rate). Keep the raw settings reachable for exploration and tuning; the workflow-facing
  surface is the composed actions.

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
DEVICE.md to review. Changing a limit later is a code review, not a runtime action. The CLI lab
and a running `mhp-mcp` bridge are separate processes, so editing package files is not enough:
with the CLI lab, `mhp lab accept <id>` re-records the manifest after an edit and the bridge
picks it up on reload or restart; without the accept, the bridge refuses the changed package
(`PackageChanged`). In this build (0.12.0+mimi.1) `mhp validate` and `mhp inclusion` choke on the
`pkg:` prefix — pass the bare absolute path instead.

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
- [ ] `class` is a canonical name from SPEC §13 / `openmhp/classes.json` (the published Allotrope, CHMO, OBI or NCIT label in snake_case; `mhp validate` names the nearest and warns on an old alias); `class_ref` for a narrower published term; every parameter is a typed shape with a UCUM `unit`, `limits`, and a `default` or `nullable: true` when optional; `resolution` where the instrument has a settable step
- [ ] every `long` action declares `returns` (the result contract) matching what `on_invoke` returns
- [ ] `state` and `busy` declared with `source: runtime`; `connected` read by the driver or `source: runtime`
- [ ] instrument self-state (SPEC §4.6): `calibration_status`, `qualification_status`, `usage_count` with `source: record` (the base answers from config.json), or `source: instrument` where the device reports them
- [ ] `robot_access_ready` wherever a lid, door, tray, drawer or deck meets a handling system, and `physical.automated_load`
- [ ] `safety.hardware_stop` named where the instrument has a physical stop, with `latch_external_stop` in the driver
- [ ] `mhp rubric <folder>`: every device-level criterion Pass or N/A, and each N/A is true of the instrument
- [ ] `on_estop` does something real, or `safety.estop: false` and `safety.notes` says what stops it
- [ ] a watchdog window, unless the device is operator-run and the notes say so
- [ ] no assignment to `self.descriptor` outside `setup()`, none to `_enforced`/`_index`; no gate
      overridden; any descriptor material an added RPC returns is deep-copied
- [ ] every write is verified: read-back compared with the intended value (same caster
      both sides), error-queue diff around the write, values snapped to the instrument grid
- [ ] state-coupled settings are wrapped in intent-level actions that resolve the
      couplings and report what they allocated, not left as bare settings to sequence
- [ ] `mhp inclusion <folder>` Package tier passes, with every `[-]` skip read and accepted
- [ ] owner reviewed DEVICE.md

To be included in `supported-devices/`, additionally:

- [ ] `sim.py` twin that loads with no vendor library and no `config.json`
- [ ] `references/setup.md` with the vendor library, the host, and a first-hardware-test section
- [ ] `config.example.json` shipped, `config.json` never committed
- [ ] `config.schema.json` beside it: one entry per question `mhp node setup` asks (`ask`, `kind`, `example`, `help`; passwords as `secret` to the keyring), and `discover`/`probe` classmethods on the driver where the instrument can be asked (see `openmhp/node_setup.py`)
- [ ] entry in `openmhp/registry.json`; row in `supported-devices/README.md` with an honest status
- [ ] the twin exercised in `tests/test_adapters.py`
- [ ] `mhp inclusion <folder>` Submission tier passes too

## When the web is out of reach

On many company machines an agent has no web or git access. Everything on openmhp.com ships inside the installed
package, so read it there instead of guessing:

- `mhp guide`: the topics. `mhp guide <topic>` reads one (troubleshooting, quickstart, gateway, lab-nodes,
  experiment-flow, add-a-device, cookbook, adapters, spec, ...). `mhp guide search <words>` finds the lines that
  mention them.
- `mhp --version`: which OpenMHP is installed. `mhp gateway --version`, `mhp node --version` and
  `mhp agent --version` also say what the running gateway, the instrument PC's service, or the joined gateway runs.
- Installed with npx only: the same commands as `npx -y openmhp-cli@latest mhp guide ...`.

When a command is refused or answers oddly, check the versions first, then `mhp guide troubleshooting`.
