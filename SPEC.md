# Open Model Hardware Protocol (MHP)

**Version 2026-09-12 (0.9, draft for early partners)** · rendered at [openmhp.com/spec](https://openmhp.com/spec)
An open protocol for AI agents to discover, understand and safely operate physical devices.

---

## 1. Why MHP

Every instrument on a bench or factory floor has its own programming interface. Connecting them to each other is hard; connecting them to an AI agent is harder, because the agent needs three things no vendor API provides: a uniform way to *read and write* the device, a machine-readable account of *what the device is and how to use it safely*, and a way to *hand off long-running work* so the device can run without the agent reasoning at every step.

MHP answers all three with one small protocol. It borrows the shape of the Model Context Protocol (MCP): JSON-RPC 2.0 messages, a short list of primitives, capability negotiation at connect time, and a host/client/server split. Where MCP exposes *tools, resources and prompts*, MHP exposes *signals, settings, actions and a safety envelope*, all described by one **device descriptor** that the driver serves and the agent reads before touching anything.

Design rules, in priority order:

1. **Safety is enforced by the driver, never by the agent.** Limits, interlocks and approval levels live in the descriptor and are checked on the device side of the wire. A wrong value from an agent is refused, not obeyed.
2. **One descriptor is the whole manual.** Everything an agent needs, including the tacit knowledge that used to live in paper manuals and people's heads, is written in natural-language `notes` fields on the descriptor.
3. **Six primitives, no more.** A device that speaks describe / signals / settings / actions / safety / methods can be operated by any MHP host.
4. **Bridge, don't replace.** OPC UA, ROS 2, SiLA 2, MADSci and PyLabRobot devices become MHP devices through thin adapters; MHP is the layer the agent sees.
5. **The agent's context is a resource the protocol protects.** A lab with two thousand devices costs the agent the same handful of tokens as a lab with two. Nothing is loaded that was not asked for (§3).

---

## 2. Architecture

```
┌──────────────────────────────────┐
│  Host  (agent runtime)           │
│   Claude / lab orchestrator /    │
│   scheduler / notebook           │
│  ┌──────────┐  ┌──────────┐      │        one server per device
│  │MHP client│  │MHP client│ ...  │
└──┴────┬─────┴──┴────┬─────┴──────┘
        │ JSON-RPC     │ JSON-RPC
   stdio / HTTP   stdio / HTTP
        │             │
┌───────▼──────┐ ┌────▼─────────┐
│ MHP server   │ │ MHP server   │
│ (driver)     │ │ (adapter)    │
│ thermocycler │ │ SiLA 2 arm   │
└───────┬──────┘ └────┬─────────┘
   serial/USB      SiLA gRPC
        │             │
   [instrument]   [instrument]
```

| Role | Responsibility |
|---|---|
| **Host** | The agent runtime around the model. Holds one client per device, presents confirmation prompts to people, and is trusted; the model it hosts is not (§7.2). |
| **Client** | One connection to one server. Sends requests, receives responses and notifications, tracks the lease. |
| **Server (driver)** | Owns exactly one device. Serves the descriptor, enforces the safety envelope, translates primitives into vendor commands, runs jobs. |
| **Device** | The physical thing. May be a single instrument or a coordinated cell exposed as one logical device. |

A server MAY be an **adapter** that wraps another control layer (an OPC UA server, a SiLA 2 feature, a MADSci node) rather than raw hardware. From the host's point of view there is no difference.

---

## 3. Scale: one device among thousands

MCP's first year taught a specific lesson. Loading every tool definition up front cost about 55,000 tokens for five ordinary servers, and selection accuracy *fell* as the list grew. Anthropic's fixes, described in "Advanced tool use", were three: a **tool search tool** with deferred loading (85% fewer tokens, accuracy up from 49% to 74% on Opus 4), **programmatic tool calling** so intermediate results never enter the model's context (37% fewer tokens on research tasks), and **usage examples** inside tool definitions (72% to 90% on complex parameters). MHP builds all three in from the start, because a lab has more devices than a workspace has tools, and every device descriptor is longer than a tool schema.

### 3.1 Descriptor detail tiers

`device/describe` takes a `detail` parameter. A host never has to load the whole descriptor to decide whether it wants the device.

| Tier | Cost | Contents |
|---|---|---|
| `card` | ~40 tokens | Level 1: the DEVICE.md frontmatter (id, class, make, model, location, tags, description), live state, and the *names* of every signal, setting and action |
| `summary` | under 1k tokens | Level 2: card + the DEVICE.md operating instructions + every signal/setting/action with type, unit, limits, approval level and interlocks + the list of bundled resources |
| `full` | unbounded | Level 3: the whole descriptor, including notes, params and examples |

`select` fetches full specs for named items only: `{"select": {"actions": ["run_protocol"], "settings": ["target_temperature"]}}`. The normal path is *card → summary → select the two things you will use*. A host SHOULD default to `summary`; `full` is for authoring and debugging.

### 3.2 The directory

A **directory** is an MHP server whose role is finding devices rather than being one. It indexes cards, not descriptors, and keeps no open connection to the devices it lists.

| Method | Params | Returns |
|---|---|---|
| `directory/search` | `query` (free text), `class`, `tags`, `location`, `state`, `limit`, `live` (default true) | ranked cards with live `state`, each with a `target` the client can connect to |
| `directory/get` | `id` | one card + target, with live state (a ping, or a cached answer younger than 2 s) |
| `directory/stats` | | counts by class and state |

Ranking is BM25 over id, class, make, model, location, tags, notes and the names of signals, settings and actions, so a query like *"heat a 96-well plate to 95 °C for PCR in bay 12"* finds thermocyclers in bay 12 without the agent knowing any ids. Filters are exact. `state` lets an agent ask for an idle instrument.

A directory is built by asking each device for its card once (`device/describe {detail: "card"}`), or from a manifest file the lab maintains. **State is never served from the index.** The index holds only what is static about a device (identity, location, tags, capability names). At query time the directory pings the top candidates in parallel with a short timeout (the reference uses 500 ms and pings four times `limit` candidates when a `state` filter is given), fills in each card's `state` from the answer, and only then applies the filter. `directory/get` uses the same live state, reusing an answer younger than the cache window (2 s in the reference). A device that does not answer is reported as `unreachable` and never matches `state: "idle"`. A client MAY pass `live: false` to skip pinging when it only wants identity, and MUST still treat the device's own `describe` or `ping` as authoritative before acting.

Small labs need no directory: a client with an explicit name-to-target map scans its own devices' cards.

### 3.3 Constant tool surface

An MCP host connected to an MHP lab sees **eight operating tools regardless of device count**: `mhp_find`, `mhp_describe`, `mhp_read`, `mhp_write`, `mhp_invoke`, `mhp_job`, `mhp_estop`, `mhp_run`, plus three for the lab itself: `mhp_lab` (§9.1), `mhp_data` (§3.5) and `mhp_method` (§5.8) — eleven in total. There are never per-device tools. The device descriptor, loaded on demand, is the documentation. Bridges MUST NOT enumerate devices into the tool list or the resource list at startup; resources list only the devices the session has opened.

### 3.4 Programmatic runs

`mhp_run` executes an orchestration script against the lab and returns only what it prints, capped. A script that takes five hundred temperature readings and reports a mean puts one line in the model's context, not five hundred numbers. The script sees the same `Lab` client as §10.3, a `run_dir` folder to save files into, and every call it makes passes the same safety gates as a direct tool call. Hosts SHOULD sandbox script execution; the reference implementation runs scripts in-process so simulated device state is shared, and says so.

Three modes matter for real work:

- **Recipes.** `mhp_lab op="recipes"` searches tested cross-instrument procedures (bundled ones such as `pcr-with-plate-transfer`, `timed-hold`, `setpoint-sweep`, `periodic-readings`, plus any in `~/.openmhp/recipes/`). Each is an ordinary script with a header (`# recipe`, `# needs`, `# asks`, `# summary`) and a `PARAMS` dict; `mhp_run recipe=<name> params={...}` merges the caller's overrides into `PARAMS` as data, never as generated code, before the body runs. An agent adapts a recipe rather than composing a protocol from scratch.
- **Plan mode.** `mhp_run plan=true` rehearses a script against a *plan lab*: reads are real, every write and invoke is a dry run through the gates (including the driver's whole-request parameter check), any other mutating request is recorded but not executed, jobs complete instantly, `time` is virtual, and a plan stops after 300 steps. The result is the ordered list of steps, the ones a person must confirm, the long-running ones, the first step the driver would refuse, and the steps whose interlocks are open right now. A plan follows one path using current readings: a loop that waits on a live reading is recorded as one `wait_until` step or truncates the plan, and the verdict says which. Hosts SHOULD show the plan to the person before running anything that heats or moves.
- **Background runs.** `mhp_run background=true` starts the script and returns a run id; the script continues after the tool call, for hours if needed. `mhp_data` (§3.5) reads its output and files later.

### 3.5 Runs, data and the run log

Every `mhp_run` is a **run** with a folder under `~/.openmhp/runs/<id>/` holding `script.py`, `stdout.txt`, `meta.json` and whatever the script saved to `run_dir` (readings as CSV, images, logs). `mhp_data` lists runs, lists a run's files, and reads a text file from one, capped; binary files are reported by size and path. This is the protocol's answer to bulk data in this draft: results live in files next to the run that produced them, and an agent pulls in only the file it needs.

A run's `meta.json` is written when it starts, and a run whose process ended before it finished is reported as `interrupted`. Script output goes only to the run's own file; nothing redirects the process's standard output, which the MCP transport owns.

The **run log** is append-only JSONL, one file per day under `~/.openmhp/log/`. The bridge records every call made through its clients, from direct tools and from run scripts (tagged with the run id): reads, writes, invokes, refusals, confirmations, e-stops and leases, plus scans, adds, plans, run boundaries and events from in-process devices. Sequence numbers continue across restarts; a cursor older than memory is served from disk, and the answer says `complete: false` when history is missing. Events from devices served over HTTP are not yet consumed (§16). `mhp_lab op="events" since=<seq>` returns what happened after a point, so a returning agent can catch up; the same events are pushed to the harness as MCP logging messages when it declared the capability. A run is reproducible from its script and the log, and a lab-notebook entry can be generated from them.

### 3.6 Examples in the descriptor

Actions MAY carry `examples`, an array of realistic parameter objects. Bridges MUST forward them (the reference bridge exposes them through `mhp_describe`, and its own tools ship `input_examples`). A schema says what is valid; an example says what is normal.

### 3.7 Measured

The reference `examples/scale_demo.py` builds 2,000 simulated devices across 8 classes and 40 bays.

| | Tokens in agent context |
|---|---|
| Every descriptor loaded up front | 1,224,382 |
| `mhp_find` (5 cards) + summary of the chosen device (with its operating instructions) + full spec of the 2 items used | 1,270 |

That is 0.10% of the naive cost, with search taking well under a millisecond. The device is then operated through exactly the same primitives as in a two-device lab.

---

## 4. The device package

A device is described the way an Agent Skill is: a folder whose contents load in three levels, each only when the agent needs it. This is the same progressive disclosure that lets a harness hold hundreds of skills at ~100 tokens each, applied to hardware.

```
thermocycler-01/
├── DEVICE.md          Level 1: YAML frontmatter, the card        (~100 tokens, always cheap)
│                      Level 2: Markdown body, operating instructions (loaded when the device is chosen)
├── descriptor.yaml    Level 3: full machine-readable spec: limits, params, examples
├── driver.py          Level 3: code, a Driver subclass or an adapter's DEVICE object
├── references/        Level 3: manual excerpts, SOPs, calibration tables
├── scripts/           Level 3: ready-made orchestration scripts for mhp_run
└── methods/           Level 3, optional: the parameter sets this instrument runs, per project (§4.5)
```

| Level | Content | Served by | Loaded when |
|---|---|---|---|
| 1 | frontmatter: `id`, `class`, `make`, `model`, `location`, `tags`, `description` | `device/describe {detail: "card"}`, `directory/search` | search results; ~40 tokens per device |
| 2 | DEVICE.md body: how to operate it, what to check, what never to do | `device/describe {detail: "summary"}` (with a slim capability table) | the agent picks this device; under 1k tokens |
| 3 | descriptor.yaml items, references, scripts, driver | `device/describe {select}`, `resources/list`, `resources/read {path}` | the agent needs that item; none until asked |

### 4.1 DEVICE.md

The frontmatter is the card. `description` is what a directory ranks and what an agent matches its task against, so it must say both what the device is and when to pick it, in under 1,024 characters. The body is written for the agent that has just chosen the device: an operating procedure, what to watch, and pointers to the resources it may need.

```markdown
---
mhp: "2026-09-12"
id: thermocycler-01
class: thermocycler
make: SimBio
model: TC-96
location: bay 3, bench 3
tags: [pcr, heating, 96-well]
description: 96-well PCR thermocycler with heated lid, 4 to 105 degC block. Use for PCR,
  denaturation, ligation holds and any timed temperature program on a 96-well SBS plate.
  Not for tubes, not for cooling below 4 degC.
driver: driver.py:SimThermocycler
---

# Thermocycler-01

Sits on bench 3 in bay 3, left of the liquid handler; the plate arm reaches it at `thermocycler`.
The block ramps about 4 °C/s. Turn `lid_heater` on ~40 s before loading to avoid condensation.

## Operating procedure
1. Confirm `lid_closed` is true; `run_protocol` refuses otherwise.
2. Set `lid_heater` true; wait for `lid_temperature` above 100 °C.
3. Invoke `run_protocol`; poll the job. 30 cycles of three steps take ~75 minutes.
4. Write `target_temperature` 4 to hold. Open the lid only below 60 °C (needs a human).

## Resources
- `references/protocols.md`: standard programs per polymerase.
- `scripts/pcr.py`: complete run through `mhp_run`, including the 4 °C hold.
```

### 4.2 descriptor.yaml

The machine-readable part. Identity fields live in the frontmatter and are merged in; everything below is enforced or served by the driver.

```yaml
device:
  notes: >
    96-well block on bench 3, left of the liquid handler. Lid must be closed
    before any run. Block ramps ~4 °C/s; lid heater takes ~40 s to reach 105 °C.

physical:                        # anything the agent cannot infer from code
  mass_kg: 12.5
  footprint_mm: [330, 460, 250]
  power_w: 850
  notes: Bench-mounted, do not relocate while running. Hot lid surface up to 110 °C.

signals:                         # READ
  - name: block_temperature
    type: number
    unit: degC
    notes: Measured at block centre; edge wells lag by ~0.5 °C.
  - name: lid_closed
    type: boolean
    notes: True when the lid latch is engaged.

settings:                        # WRITE
  - name: target_temperature
    type: number
    unit: degC
    limits: {min: 4, max: 105}   # enforced by the driver
    approval: auto               # auto | confirm | forbid
    notes: Below 4 °C condensation forms; above 105 °C the seal fails.

actions:                         # INVOKE -> job
  - name: run_protocol
    duration: long               # short | long
    approval: auto
    interlocks: [lid_closed]     # boolean signals that must read exactly true
    params:                      # undeclared parameters are refused
      steps: array of {temp: degC, hold_s: number}
      cycles: integer
    required: [steps, cycles]
    limits: {cycles: [1, 100]}   # enforced by the driver, element-wise for lists
    pausable: true               # the driver checkpoints between steps
    notes: Runs a cycling program; steps are repeated `cycles` times.
    examples:                    # what normal usage looks like (§3.5)
      - {steps: [{temp: 95, hold_s: 30}, {temp: 58, hold_s: 30}, {temp: 72, hold_s: 45}], cycles: 30}
  - name: open_lid
    duration: short
    approval: confirm            # a human must confirm each invocation
    notes: Lid may be hot; a human should be present.

safety:
  estop: true                    # driver implements safety/estop
  interlocks: [lid_closed]
  watchdog_s: 10                 # while a session holds the lease: fail safe if it goes silent this long (§6)
  notes: E-stop cuts block and lid heaters; the block cools passively.

locations:                       # optional, device-class specific extensions
  thermocycler: [-410, 90, 120]
```

### 4.3 Resources

`resources/list` returns the relative paths of every file in the package except DEVICE.md. `resources/read {path}` returns a text file's contents (capped; binary files return size only) and MUST refuse paths outside the package. Scripts under `scripts/` are written for `mhp_run` and see `lab`; an agent reads one, adapts the constants, and runs it, so the device owner's tested procedure is what executes.

### 4.4 Field rules

- `device.id` MUST be unique within a host's set of devices. `class` is an open string; §13 lists the initial vocabulary.
- `device.description` (frontmatter) SHOULD state what the device is and when to pick it, ≤ 1,024 characters. It is the ranking text for directories and the card text for agents.
- Every object (device, physical, signal, setting, action, safety) MAY carry a `notes` string. Notes are **natural language for the agent**. They are the mechanism by which tacit knowledge enters the protocol; drivers MUST pass them through unchanged.
- `type` is one of `number | integer | boolean | string | object | array`. `unit` SHOULD be a UCUM code or a common spelled-out unit (`degC`, `mm`, `percent`, `N`, `rpm`). Values are checked against the declared type before any limit or vendor code runs: numbers must be finite, integers and booleans are not interchangeable, `null` is refused, and strings may not contain control characters.
- `limits` on a setting: `{min, max}` for numbers, `{enum: [...]}` for strings. The driver MUST refuse writes outside limits with `LimitViolation`.
- `limits` on an action: a map from parameter name to `[min, max]`, `{min, max}` or `{enum: [...]}`, applied element-wise to lists. The driver MUST enforce them, for dry runs and real runs alike, together with `required` and, when `params` is declared, the rule that undeclared parameters are refused. Checks that span a whole request (every step of a program) belong in the driver's side-effect-free `validate_params` hook, which also runs for dry runs, so no step starts before the whole request is known to be valid.
- `approval`: `auto` (agent may act), `confirm` (each call needs `approved: true`, which only the host may set, and only after a person confirmed that exact request; §7.2), `forbid` (never agent-operable; listed so the agent knows the capability exists and why it is off-limits).
- `interlocks`: names of boolean signals that MUST read exactly `true` at the moment of the write or invoke; false, unreadable or stale values count as open (`InterlockOpen`).
- `during_job` on a setting (default false) says it may change while a job runs; otherwise the write is refused as busy. `concurrent`, `pausable` and `cancellable` on an action declare what the driver can actually do; pause and cancel requests for actions that do not support them are refused with `NotSupported`.
- A factory-built driver (adapter) generates its capabilities from bindings; descriptor.yaml then refines named items and MUST NOT name a capability the driver has no binding for.
- `duration`: `short` actions are expected to finish within seconds and hosts MAY block on them; `long` actions run as jobs and the host SHOULD poll or subscribe.
- `tags` on `device` SHOULD be set: they are what a directory filters on, along with `location`. A package meant to be shared cannot know where the instrument will stand, so `location` is recorded by the lab that installs it (`mhp_lab op='location'`, `mhp lab location <id> "bay 3"`) and the fleet record is the authority; the frontmatter value is a default for a device installed in one place only. `examples` on an action is an array of parameter objects.
- Unknown top-level keys (for example `locations`) are permitted and MUST be preserved by adapters and bridges. Device classes define their own conventions.

### 4.5 Methods: the `methods/` folder

Some instruments do not run *actions* so much as *methods*: an HPLC, GC, MS or PXRD runs one named
parameter set per injection or scan, and that set changes from project to project and compound to
compound. A balance or a laser probe has no such thing. MHP treats methods as a primitive that every
device answers (§5.8), and as Level 3 content of the package for the devices that have them. The rules
below are the whole game; the reference implementation enforces each one.

**M1. Declaring.** An action that runs methods carries `methods: true` in descriptor.yaml. A device with at
least one such action is *method-capable* and reports `capabilities.methods: true` in `initialize`. A device
with none reports `false`: its `methods/list` and `methods/find` answer empty, and `methods/save` is refused
with `NotSupported`. No device may be method-capable without declaring the action, and no method may
target an action that is not declared method-driven.

**M2. Where they live.** Methods are files in the package, under `methods/`, one folder per project:

```
methods/
├── README.md                       optional: what a method means on this instrument
├── _shared/                        methods owned by no project: vendor defaults, system suitability
│   └── <method>.yaml
└── <project>/                      one folder per project that has run on this instrument
    ├── <method>.yaml               the current version
    ├── <method>.history.jsonl      every earlier version, append-only, never rewritten
    └── <method>.runs.jsonl         every run of it on this instrument, append-only
```

Project ids and method ids match `^[a-z0-9][a-z0-9._-]{0,63}$`. `_shared` is the one reserved project id.
A method's full id is `<project>/<method>`; wherever a request names a method, `name` MAY be the full id, or
a bare method id together with `project` (default `_shared`). Nothing else in the package may be named
`methods`. A package without method-driven actions MUST NOT have a `methods/` folder; the validator refuses
either inconsistency. The folder is written by the device itself, so it is not part of the package's enforced
configuration: a host that fingerprints a package to detect tampering (§9.1, `reload`) MUST leave `methods/`
out of the fingerprint, and a method file is never code.

**M3. The record.** A method file is YAML with exactly these top-level keys:

| Key | Required | Meaning |
|---|---|---|
| `name`, `project` | yes | must equal the file name and folder name |
| `action` | yes | the method-driven action that receives `params` |
| `params` | yes | an object: exactly what `actions/invoke` sends; nothing else is interpreted |
| `compounds` | yes | one or more lowercase names; what the method is for; `methods/find` matches on them |
| `version` | yes | integer ≥ 1, assigned by the device, never chosen by the caller |
| `hash` | yes | first 12 hex of sha256 over canonical JSON `{action, params}`; assigned by the device |
| `created`, `updated` | yes | Unix seconds, assigned by the device |
| `validated` | yes | `{at, hash}` when the device's own parameter gate passed for this version; `null` if the file was authored by hand and never checked |
| `status` | yes | `active` or `retired`; retired methods are kept, listed only on request, never found by `methods/find` |
| `author`, `notes` | no | free text: who and why |
| `source` | no | `{kind: vendor_file \| manual \| person \| agent \| derived, ref}`: where the parameters came from |
| `derived_from` | no | `{project, name, version}`: the method this one was copied or tuned from |

A file with any other key, a missing required key, or a `name`/`project` that disagrees with its path is
invalid and the device MUST NOT serve it. History entries repeat the record as it was; run entries are
`{ts, job, session, state, overrides, project, result_digest}`.

**M4. Versions.** `methods/save` on a name that exists compares `hash` and `action`. Unchanged: the record's
metadata is updated and `version` stays. Changed: the previous record is appended to the history file and
`version` increments. Versions are never renumbered or removed. `methods/delete` sets `status: retired`; it
does not remove the file. A retired method can be saved again, which reactivates it as a new version.

**M5. Validation on save.** Before writing, the device runs the target action's parameter gate on `params`:
types, required parameters, undeclared parameters, `limits`, and the whole-request `validate_params` hook.
State, interlocks, leases and busy are run-time conditions and are not checked. A refusal is returned
unchanged and nothing is written. The stored `validated.hash` MUST equal the record's `hash`.

**M6. Running one.** `actions/invoke` accepts `method: {name, project?, version?, overrides?}` in place of, or
in addition to, `params`. The parameters sent to the action are the method's, then `overrides`, then explicit
`params`, later keys winning. The job carries `method: {project, name, version, hash, overrides?}` and
`project`, in every status answer and every job notification, so a result is traceable to the exact
parameters that produced it. On completion the device appends the run to the method's runs file. Overrides
are for adapting between runs; they are never saved implicitly.

**M7. Asking.** A method-driven action invoked with neither `method` nor `params` is refused with
`MethodRequired` (-32015). `data` carries the answer of `methods/find` for the request's `compound` and
`project` (`choice`, `method` or `candidates`, `ask`), so the caller knows exactly what to ask a person. A
method-driven action invoked with explicit `params` under a `project` that has no method for the given
`compound` is accepted, and the response carries `methodHint`, telling the caller to save the parameters
under that project if they worked. This is how a new project's methods come to exist on an instrument.

**M8. Finding.** `methods/find {compound, project?, action?}` answers with `choice`:

| `choice` | When | The caller's duty |
|---|---|---|
| `one` | exactly one active method for the compound in the project; or none in the project and exactly one anywhere (then `newProject` names the project) | use it |
| `several` | more than one candidate at the level that matched | ask the person which one; an autonomous loop with a declared project takes the project's own, never one from another project |
| `none` | no active method for the compound | ask the person for the parameters, run once with explicit params, save them under the project |

Project methods take precedence over `_shared`; `_shared` over other projects' methods. `ask` is a sentence
the caller can put to a person as is.

**M9. Provenance.** The host's run log records `method` and `project` with every invoke; the device's runs
file is the instrument-side record; the history file is the parameter-side record. Together they answer,
for any result, which parameters produced it, on which instrument, in which project, and what they were
derived from.

**M10. Plans.** In plan mode `methods/list`, `get`, `find` and `diff` are real; `save` and `delete` are
recorded, not executed; a `run` of a method is a dry-run invoke with the resolved parameters, so the plan
shows the method's name and version next to the step.

---

## 5. Primitives

All requests are JSON-RPC 2.0. Method names are namespaced with `/`, as in MCP.

| Primitive | Methods | Direction |
|---|---|---|
| Lifecycle | `initialize`, `ping` | client → server |
| Describe | `device/describe {detail, select}` | client → server |
| Resources | `resources/list`, `resources/read {path}` | client → server |
| Directory | `directory/search`, `directory/get`, `directory/stats` | client → directory server |
| Signals | `signals/list`, `signals/read`, `signals/subscribe` | client → server |
| Settings | `settings/list`, `settings/write` | client → server |
| Actions | `actions/list`, `actions/invoke`, `jobs/status`, `jobs/list`, `jobs/pause`, `jobs/resume`, `jobs/cancel` | client → server |
| Methods | `methods/list`, `methods/find`, `methods/get`, `methods/save`, `methods/diff`, `methods/delete` | client → server |
| Safety | `safety/limits`, `safety/estop`, `safety/reset` | client → server |
| Session | `session/acquire`, `session/renew`, `session/release` | client → server |
| Notifications | `notifications/signals/update`, `notifications/settings/changed`, `notifications/jobs/{started,progress,paused,resumed,cancelling,finished}`, `notifications/safety/{estop,fault,reset}`, `notifications/methods/{saved,retired}` | server → client |
| Elicitation | `elicitation/confirm` | server → client (optional; see §7.2) |

### 5.1 `initialize`

```json
→ {"jsonrpc":"2.0","id":1,"method":"initialize",
   "params":{"protocolVersion":"2026-09-12","clientInfo":{"name":"claude-lab","version":"1.0"}}}
← {"jsonrpc":"2.0","id":1,"result":{
     "protocolVersion":"2026-09-12",
     "device":{"id":"thermocycler-01","class":"thermocycler","make":"SimBio","model":"TC-96"},
     "capabilities":{"signals":true,"settings":true,"actions":true,"methods":false,
                     "subscribe":true,"lease":true,"estop":true}}}
```

Servers MUST respond to `initialize` before any other method. Capabilities are booleans; a client MUST NOT call a method whose capability is false.

### 5.2 `device/describe`

Returns the descriptor (§4) at the requested `detail` tier (`card | summary | full`, §3.1) or the named items in `select`, plus `"state": "idle" | "busy" | "fault" | "estop"`. Hosts SHOULD call this with `summary` before operating a device, then `select` the items they will use.

### 5.3 Signals (read)

```json
→ {"method":"signals/read","params":{"names":["block_temperature","lid_closed"]}}
← {"result":{"values":{"block_temperature":22.0,"lid_closed":true},"ts":1788991266.5}}
```

`names` omitted means all signals. `signals/subscribe` asks the server to push `notifications/signals/update` for the named signals; over HTTP these arrive on the `/events` SSE stream, over stdio as interleaved notification lines.

### 5.4 Settings (write)

```json
→ {"method":"settings/write","params":{"name":"target_temperature","value":95}}
← {"result":{"ok":true,"name":"target_temperature","value":95}}

→ {"method":"settings/write","params":{"name":"target_temperature","value":200}}
← {"error":{"code":-32010,"message":"target_temperature=200 above max 105","data":{"min":4,"max":105}}}
```

Optional params: `approved: true` (for `confirm` settings; set by the host only, after a person confirmed, §7.2), `dryRun: true` (run every check, touch nothing, return `wouldWrite`).

A write whose outcome is unknown (the command may have reached the device but the reply failed) latches the device in `fault` with `data.outcome: "unknown"`. Errors raised before anything was sent (`InvalidValue`, `LimitViolation`, ...) do not change the device state.

### 5.5 Actions and jobs

`actions/invoke` returns immediately with a **job**. The device does the work; the agent polls or subscribes.

```json
→ {"method":"actions/invoke","params":{"name":"run_protocol",
     "params":{"steps":[{"temp":95,"hold_s":30},{"temp":58,"hold_s":30},{"temp":72,"hold_s":45}],"cycles":30}}}
← {"result":{"job":{"id":"job_04324008","action":"run_protocol","state":"queued","progress":0.0}}}

→ {"method":"jobs/status","params":{"id":"job_04324008"}}
← {"result":{"job":{"id":"job_04324008","state":"running","progress":0.43}}}

   ... later ...
← {"method":"notifications/jobs/finished","params":{"job":{"id":"job_04324008","state":"done",
     "progress":1.0,"result":{"cycles_completed":30,"final_block_temperature":72}}}}
```

Job states: `queued → running → done | failed | cancelled`, plus `waiting_operator` for operator-run instruments (§9.1). A `failed` job carries `outcome: "unknown"` and puts the device in `fault` until a verified `safety/reset`. Busy is derived from all active jobs: a non-concurrent action is refused while any job runs, and a `concurrent` one may run alongside. A job's completion and the device state are published together. Adapters MUST report the backend's terminal outcome (a cancelled or aborted backend job is not `done`) and MUST NOT report a cancel the backend has not honoured.

### 5.6 Safety

- `safety/limits` returns the effective limits, interlocks and approval levels in one call, for hosts that want to show the envelope to a human.
- `safety/estop` MUST stop all motion and energy output as fast as the hardware allows, cancel every running job, and put the device in `estop`. It MUST succeed regardless of lease, approval level or interlock state, and MUST NOT wait behind ordinary requests: the reference driver runs it outside the request lock, and the serial driver interrupts in-flight I/O before sending its stop commands. If the stop hook fails, the device stays in `estop` and the response says `stopped: false`. It is the one call an agent may always make.
- `safety/reset` returns the device to `idle` after `estop` or `fault`. It MUST fail with `DeviceBusy` while any job is still active, and MUST verify recovery first (the reference reads every signal). Only the lease holder, or anyone when the device is unleased, may reset.

### 5.7 Session leases

`session/acquire {ttl}` gives the calling session exclusive write and invoke rights until `ttl` seconds pass without `session/renew`, or until `session/release`. Every client has its own session id, so independent clients never share a lease. The reference client renews automatically with a heartbeat while it holds a lease, and each run gets its own session whose leases end with the run. If a lease is lost, the next actuating call fails with `NotLeased`, and the client must not assume it still has control. Reads, `ping`, `describe`, `jobs/status`, `jobs/pause`, `jobs/cancel` and `safety/estop` are never blocked by a lease; `jobs/resume` and `safety/reset` are. On a device that declares `watchdog_s`, operating it requires holding the lease (`NotLeased` with `data.reason: "lease_required"`); the reference client acquires it on first use.

### 5.8 Methods

The rules are in §4.5; this is the wire surface. Every device answers all six; a device that is not
method-capable answers `list` and `find` with nothing and refuses `save` with `NotSupported`.

| Method | Params | Result |
|---|---|---|
| `methods/list` | `compound?`, `project?`, `action?`, `query?`, `retired?` (default false) | `{methods: [card...], count, compounds, projects, actions, method_driven}`; a card is the record without `params` |
| `methods/find` | `compound` (required), `project?`, `action?` | `{choice: one\|several\|none, method? \| candidates, ask?, why?, newProject?}` (§4.5 M8) |
| `methods/get` | `name` (full id or bare), `project?`, `version?` | the full record; an earlier version is reconstructed from history |
| `methods/save` | `method: {name, project?, action, params, compounds, author?, notes?, source?, derived_from?}`, `note?` | `{saved: card, validated: true}`; the device assigns version, hash, timestamps and `validated` |
| `methods/diff` | `a`, `b?` (full ids or bare with `project`), `aVersion?`, `bVersion?` | `{a, b, action?, params: {key: {from, to}}, same}` |
| `methods/delete` | `name`, `project?` | `{retired: true}`; the file stays (§4.5 M4) |

`actions/invoke` gains `method`, `project` and `compound` (§4.5 M6, M7). `methods/list`, `find`, `get` and
`diff` are never blocked by a lease or by a running job; `save` and `delete` wait for the request lock like
any write and require no lease, since they touch files, not hardware.

---

## 6. Lifecycle

```
client                                server
  │── initialize ───────────────────────▶│  version + capabilities
  │── device/describe ──────────────────▶│  descriptor into agent context
  │── session/acquire {ttl:600} ────────▶│  optional exclusive control
  │── signals/subscribe ────────────────▶│  optional streaming
  │── settings/write / actions/invoke ──▶│  operate (gated by §7)
  │◀─ notifications/... ─────────────────│
  │── session/renew (< watchdog_s) ─────▶│  keeps the lease and the watchdog fed
  │── session/release ──────────────────▶│
```

**Watchdog.** If the descriptor declares `safety.watchdog_s`, the watchdog is armed whenever a session holds the lease. Any request from the holder renews it; the reference client sends `session/renew` at a third of the window. If the holder is silent for longer than the window, or its lease expires without release, the server MUST fail safe: enter `estop`, cancel active jobs, run the stop hook, and drop the lease. Recovery needs a verified `safety/reset`. The watchdog protects against the controlling process dying or losing its connection; it does not notice a model that is alive but idle. A driver running inside the host process dies with the host, so host power loss is covered only by a device-side or hardware watchdog, which the descriptor should describe in `safety.notes`.

**Versioning.** `protocolVersion` is a date string, as in MCP. A server MUST answer `initialize` with the highest version it supports that is ≤ the client's; a client that receives an older version MUST either speak it or disconnect. The MCP bridge negotiates MCP versions separately: it answers with the client's version when it supports it, and otherwise with its newest supported version.

---

## 7. Safety model

The safety model is the reason MHP exists as a separate protocol rather than a set of MCP tools. Every rule below is enforced **in the server**, on the device side of the network, so it holds even when the agent is wrong, compromised or has lost context.

### 7.1 Gate order

On every `settings/write` and `actions/invoke` the server evaluates, in order:

1. **State**: `estop` → `EStopActive`; `fault` → `DeviceFault`.
2. **Approval**: `forbid` → `Forbidden`; `confirm` without `approved:true` → `ApprovalRequired`.
3. **Interlocks**: each named signal is read live and must be exactly `true`; false, unreadable or stale → `InterlockOpen`.
4. **Values**: type (`InvalidValue`), then limits (`LimitViolation`); for actions also declared, required and bounded parameters, then the driver's whole-request `validate_params`.
5. **Lease**: another session holds an unexpired lease → `NotLeased`; a watchdog device operated without the lease → `NotLeased` (`lease_required`).
6. **Busy**: an action while a non-concurrent job runs, or a setting not marked `during_job` while any job runs → `DeviceBusy`.

Only after all six pass does vendor code run. `dryRun: true` evaluates the same checks without touching the device; approval, lease and busy conditions come back as notes (`needsApproval`, `needsLease`, `leaseHeldBy`, `busyNow`) so a plan can show them.

### 7.2 Approval levels, elicitation and the trust boundary

`confirm` is the bridge between agent autonomy and human oversight, and it depends on one rule: **the host is trusted, the model is not.** `approved: true` is the host's statement that a person confirmed *this exact request*. A model asserting it is not approval.

1. The model asks for `open_lid`. The host sends the request without approval and gets `ApprovalRequired`.
2. The host asks a person, showing the device, the action, its exact parameters and the descriptor's `notes`.
3. Only on an explicit yes does the host send the same request again with `approved: true`. The answer is logged.

The reference bridge does this through MCP elicitation, for direct tool calls and for every call a run script makes, and it ignores any `approved` value the model supplies. If the harness has no elicitation, the bridge has no trusted way to reach a person, so confirm-gated operations are unavailable and the refusal says so. The SDK and the CLI are host tooling: code or a person using them directly is the trusted party, and `--approved` is that person's own statement. Servers that can reach a person directly (a touchscreen on the instrument, a key switch) MAY implement `elicitation/confirm` as a server-initiated request.

Jobs can be **paused** (`jobs/pause`, `jobs/resume`) when the action declares `pausable: true`: the driver calls `checkpoint()` between steps, which blocks while paused and raises on cancel, so a person can step in without an emergency stop.

### 7.3 Fail closed

Any exception inside vendor code during a job, and any failure of a write after the command may have been sent, moves the device to `fault` with an unknown outcome and runs the driver's safe-state hook (by default the e-stop behaviour). `fault` and `estop` block all writes and invokes until `safety/reset`, which verifies recovery first. There is no automatic recovery. A request rejected before anything was sent does not change the device state.

### 7.4 Defence in depth

Descriptor limits protect setpoints and parameters. A value hidden inside a structured parameter (a 200 °C step inside an otherwise valid protocol) is caught by the driver's `validate_params`, which MUST run for dry runs as well as real runs, so no step executes before the whole program is known to be valid. The reference thermocycler validates every step this way.

### 7.5 What MHP does not do

MHP is not a functional-safety system in the IEC 61508 sense. Hard-wired e-stops, light curtains and PLC safety logic remain the primary layer; MHP is the layer that keeps an agent from *asking* for something unsafe, and gives it a standard way to stop everything when it sees something wrong.

### 7.6 Trust boundary and retries

Package code (`driver.py`, `sim.py`), recipes and `mhp_run` scripts are code the host executes. The runtime can refuse malformed or out-of-limit requests only while the driver and its descriptor are outside the model's authority: a model that can edit a package, or run arbitrary scripts in an unsandboxed host, can change what is enforced. Deployments SHOULD separate package authoring (a code review) from operation, and SHOULD sandbox scripts.

MHP operations are not idempotent. A request can reach a device even when its response is lost, and servers do not deduplicate requests. Clients MUST NOT retry writes or invokes automatically; after a lost response they SHOULD read state or list jobs to reconcile.

---

## 8. Notifications

Servers push notifications (JSON-RPC requests without `id`) for anything a supervising agent needs to react to:

| Method | Params | When |
|---|---|---|
| `notifications/signals/update` | `{name, value, ts}` | a subscribed or driver-chosen signal changes |
| `notifications/settings/changed` | `{name, value, by}` | any client writes a setting |
| `notifications/jobs/started` | `{job}` | job leaves the queue |
| `notifications/jobs/progress` | `{job, ...extra}` | driver reports progress (extra keys are device-specific) |
| `notifications/jobs/finished` | `{job}` | job reaches done / failed / cancelled |
| `notifications/jobs/paused`, `jobs/resumed`, `jobs/cancelling` | `{job, by}` | pause, resume or cancel requested |
| `notifications/safety/estop` | `{by, reason, stopped, stop_error}` | e-stop engaged by a client or the watchdog |
| `notifications/safety/fault` | `{reason}` | the device latched a fault with an unknown outcome |
| `notifications/operator/instruction` | `{text, job?}` | an operator-run instrument asks a person to act |
| `notifications/safety/reset` | `{by}` | device returned to idle |
| `notifications/methods/saved`, `methods/retired` | `{method: card, by}` | a method was saved (new version or new method) or retired |

A supervising host consumes these without asking: the reference bridge subscribes to every device it opens
(in-process, over the HTTP `/events` stream, or over stdio), keeps the recent ones per device for
`mhp_data op='updates'`, appends them to the `events.jsonl` of any run that has used the device, and writes
the notable ones (job finished with its result, safety, operator, methods) to the lab's run log. An agent
reads what came in and decides the next run; nothing in this path polls the instrument.

---

## 9. Transports and discovery

MHP defines two transports, mirroring MCP:

- **stdio**: newline-delimited JSON-RPC on the driver process's stdin/stdout. For a driver running on the bench PC, launched by the host.
- **HTTP**: `POST /rpc` for requests; `GET /events` as a Server-Sent Events stream of notifications; `GET /mhp.json` returns the descriptor with no handshake, so an agent (or a person with `curl`) can learn what a device is from its URL alone. Clients MUST send a unique session id in `X-MHP-Client`; leases are per session. The device HTTP transport has no authentication in this draft and belongs on a trusted network (§16).

**Network discovery.** Servers SHOULD advertise via mDNS/DNS-SD as `_mhp._tcp` with TXT records `id`, `class`, `path=/mhp.json`; the reference HTTP transport does so when the optional `zeroconf` package is installed. Clients discover devices two ways, and SHOULD use both: browse `_mhp._tcp`, and probe `GET /mhp.json` on candidate hosts across the conventional port range (18900 to 18939), which works on networks that block multicast. Labs MAY additionally run a directory (§3.2).

### 9.1 The fleet and `mhp_lab`

A host keeps a **fleet**: the list of devices it knows, persisted as `~/.openmhp/fleet.json`, each entry an id, a target and the device's card. Device packages the host owns are hosted in-process from `~/.openmhp/devices/<id>/`, so a scientist's laptop needs no separate device servers for them. The bridge exposes the fleet through one tool, `mhp_lab`, with these operations:

| op | Effect |
|---|---|
| `status` | how many devices the lab has and what to do next; the agent's starting point |
| `scan` | mDNS browse plus HTTP probe of localhost and any `hosts` given; returns devices not yet in the fleet |
| `add` | register a target (`http://host:port`, a package folder, or a package id under `~/.openmhp/devices`); fetches the card; the device is immediately searchable; an id already in the lab at a different target is refused |
| `onboard` | a guided interview run by the server: returns the next questions (`ask`, in plain words for the human) and the `shape` of the answer; on completion the server writes DEVICE.md, descriptor.yaml and driver.py, validates, and asks the agent to `add` |
| `new` | create a package skeleton for an instrument that does not speak MHP yet (for agents that prefer to write files themselves) |
| `write` | write files (DEVICE.md, descriptor.yaml, driver.py, references, scripts) into that package; paths may not escape it |
| `validate` | run the package validator |
| `recipes` | search tested procedures (§3.4) |
| `registry` | search known community packages; add one with `add target="github:owner/repo/path"` |
| `safety_card` | a readable review of a device before first use: enforced limits, gated actions, e-stop, watchdog, validator findings, and live probes (every action dry-run, an out-of-range write on every bounded setting) |
| `events` | what happened since a sequence number (§3.5) |
| `remove`, `reload` | `remove` refuses a device with active jobs unless `force`; both drop the device's connection, directory entry and in-process driver. `reload` loads a package again after its files changed; a changed package is never silently reused |
| `location` | record where an installed instrument stands; the lab's fleet record, not the package, is the authority |
| `release` | hand the bridge session's leases back |
| `list`, `home` | membership and paths |

`add` accepts `sim=true` to register a package's **simulated twin** (`sim.py`, declared as `sim:` in the frontmatter) under `<id>-sim`, so protocols can be rehearsed with nothing plugged in. The bundled devices and the community packages all ship one. Onboarding (`onboard`) ends with a safety card the agent reads back to the owner; an agent that has the instrument's manual SHOULD submit everything the manual states in one `answers` call and ask the human only to confirm the limits.

The bridge also declares MCP `instructions` on `initialize`, so a harness with no skills support still receives the operating loop and the setup path, and three MCP prompts (`setup-my-lab`, `add-instrument`, `run-experiment`) that harnesses surface as slash commands.

**No-code drivers.** The interview asks how the instrument is controlled today and picks a driver kind. `manual` wraps an instrument a person operates: a setting write is a request the operator carries out, reads return only what a person reported, each action waits in `waiting_operator` until a person acknowledges it, and both `acknowledge` and `record` need a person's confirmation. A manual device never claims an automatic e-stop or a watchdog. It can take part in protocols now and swap in a real driver later by changing one file. `serial` is a declarative driver for instruments with text commands over a serial or USB port: the owner pastes the commands from the manual into `descriptor.yaml` under `serial:` (`read`, `write`, `actions`, `estop`), and `openmhp.drivers.serial_ascii` does the rest; boolean replies must match known tokens exactly, and anything else counts as unreadable. `mhp` means the instrument already has an address and is simply added. `adapter` collects the interview and leaves `driver.py` for the fleet skill. In all kinds the descriptor, gates and levels are the same.

This is how a scientist adds an instrument without leaving the conversation: *"find the instruments on my network"* → `scan` → *"add the thermocycler"* → `add`. For an instrument that has no MHP server, the `openmhp-onboard-device` skill interviews the owner, and the agent writes the package with `new`, `write` and `validate`, then `add`s it. The `npx openmhp-cli` launcher installs the runtime, the skills and the harness registration in one command.

**Authentication.** The device HTTP transport has none in this draft: run it on a trusted network, or behind TLS with authentication. The MCP bridge's HTTP endpoint (`mhp-mcp --http`) exposes script execution and hardware control, so it requires a bearer token (`OPENMHP_HTTP_TOKEN`, or a generated `~/.openmhp/http_token`), refuses requests whose `Origin` is not explicitly allowed (`--allow-origin`), and on a loopback bind refuses `Host` headers other than localhost. It has no server-initiated requests, so confirm-gated operations are unavailable over it. The protocol reserves `params.auth` for a future in-band scheme.

---

## 10. Three control surfaces

The same six primitives are reachable three ways. They compose: an agent uses MCP to explore and decide, writes a code file for the parts that must run fast or long, and uses the CLI to check on it.

### 10.1 MCP bridge

A single MCP server exposes a whole lab to any MCP host through ten generic tools (§3.3), each with `input_examples`. Because the descriptor *is* the documentation, no per-device tool code is written, and the tool list does not grow with the lab.

| MCP tool | MHP call |
|---|---|
| `mhp_find` | `directory/search` (or a scan of cards in a small lab) |
| `mhp_describe` | `device/describe {detail, select}`, default `summary`; with `resource=` it calls `resources/read` |
| `mhp_read` | `signals/read` |
| `mhp_write` | `settings/write` |
| `mhp_invoke` | `actions/invoke` (+ optional wait) |
| `mhp_job` | `jobs/status`, `jobs/pause`, `jobs/resume`, `jobs/cancel` |
| `mhp_estop` | `safety/estop` on one device or every device this session touched |
| `mhp_run` | runs a script against the `Lab` client; returns stdout only (§3.4) |
| `mhp_lab` | fleet management: status, scan, add, onboard, recipes, registry, safety card, events, remove, reload, release (§9.1) |
| `mhp_data` | runs, their files, the run log, and what devices pushed (`op='updates'`, §8) |
| `mhp_method` | the device's methods: find, list, get, save, run, diff, retire (§4.5, §5.8) |
| resource `mhp://<id>/descriptor`, `mhp://<id>/<path>` | descriptor and package resources of devices this session has opened |

MHP errors surface as MCP tool results with `isError: true` and the structured `mhpError` body, so the model sees *why* a write was refused and can adjust. A refused call inside an `mhp_run` script returns the same body.

```bash
npx openmhp-cli setup                                        # scientist's laptop: runtime, skills, harness registration
mhp-mcp                                                  # the lab in ~/.openmhp/fleet.json; mhp_lab fills it
mhp-mcp --directory http://directory:18900               # big lab: nothing loaded until searched
mhp-mcp --directory http://directory:18900 --http 18800  # over HTTP for remote harnesses: bearer token required
mhp-mcp thermo=http://bench:18921 arm=http://arm-pc:18921   # small lab: cards indexed at start
```

The bridge is the lab's MCP server. Any harness that speaks MCP over stdio or HTTP (Claude Code, Codex, OpenClaw, Hermes, Claude Science, Open Science, or a custom agent) connects to it and sees the same eleven tools.

### 10.2 Command line

```bash
mhp http://bench:18921 describe
mhp http://bench:18921 read block_temperature lid_closed
mhp http://bench:18921 write target_temperature 95
mhp http://bench:18921 invoke run_protocol '{"steps":[...],"cycles":30}' --wait
mhp http://bench:18921 invoke open_lid --approved      # the person at this terminal confirms
mhp http://bench:18921 estop "smoke from lid"
```

The CLI is the debugging and shell-scripting surface, and what an agent reaches for inside a Bash tool.

### 10.3 Code files (SDK)

```python
from openmhp.client import Lab

lab = Lab({"arm": "http://arm-pc:18921", "thermo": "http://bench:18921"})
arm, thermo = lab["arm"], lab["thermo"]

with arm, thermo:                                    # leases on both, renewed by a heartbeat
    arm.write("speed", 30)
    arm.wait(arm.invoke("pick_plate", location="deck_A1"))
    arm.wait(arm.invoke("place_plate", location="thermocycler"))
    result = thermo.wait(thermo.invoke("run_protocol", steps=PCR, cycles=30))
    arm.wait(arm.invoke("pick_plate", location="thermocycler"))
```

An agent writes a file like this when a protocol must run for hours or step faster than its own reasoning loop. The devices then execute it without the model in the loop; the model reads the result, or gets a notification when something trips.

---

## 11. Authoring descriptors

Two paths, same output, a device package (§4):

1. **By hand.** Copy the package template, fill in the frontmatter and limits, write the operating procedure in DEVICE.md.
2. **By interview.** The agent asks the owner a short set of questions and writes the package: *What is it and when should an agent pick it? Where does it sit? What is heavy, hot, sharp or fragile about it? How do you run it, step by step? What must be true before it runs? What values would you never set? What should always need a human?* The first answer becomes `description`, the procedure becomes the DEVICE.md body, and the rest become `notes`, `interlocks`, `limits` and `approval` levels in descriptor.yaml. Existing SOPs and manual excerpts go under `references/`. The owner reviews the package before it is served.

Packages are versioned folders checked into the lab's repository. Changing a limit is a code review, not a runtime action.

---

## 12. Error codes

| Code | Name | Meaning |
|---|---|---|
| -32601 | MethodNotFound | unknown method |
| -32602 | InvalidParams | missing/invalid params |
| -32010 | LimitViolation | value outside descriptor limits (`data` carries the limits) |
| -32011 | InterlockOpen | a required interlock signal is falsy (`data.interlock`) |
| -32012 | ApprovalRequired | `confirm` item called without `approved:true` |
| -32013 | Forbidden | `forbid` item |
| -32014 | InvalidValue | wrong type, non-finite number, `null`, control characters, undeclared or missing parameter; a malformed method record |
| -32015 | MethodRequired | a method-driven action was invoked with neither `method` nor `params`; `data` carries `choice`, `candidates` and `ask` (§4.5 M7) |
| -32020 | DeviceFault | device in `fault` (or a write's outcome is unknown, `data.outcome`); verified reset required |
| -32021 | DeviceBusy | non-concurrent job running, or reset attempted mid-job |
| -32022 | EStopActive | device in `estop`; reset required |
| -32030 | NotLeased | another session holds the lease (`data.holder`), the lease was lost, or a watchdog device needs one (`data.reason: "lease_required"`) |
| -32040 | UnknownName | no such signal/setting/action |
| -32041 | JobNotFound | no such job id |
| -32050 | NotSupported | the action does not support pause or cancel; use `safety/estop` |

---

## 13. Device classes (initial vocabulary)

`thermocycler`, `liquid_handler`, `robot_arm`, `microscope`, `plate_reader`, `centrifuge`, `incubator`, `hotplate`, `balance`, `pump`, `valve`, `spectrometer`, `laser`, `stage`, `cnc`, `3d_printer`, `oven`, `power_supply`, `camera`, `generic`.

A class is a hint for the agent and a namespace for conventions (a `robot_arm` SHOULD have a `locations` map; a `microscope` SHOULD expose an `acquire` action returning an image URI). Classes are not enforced by the protocol.

---

## 14. Bridging existing ecosystems

MHP is deliberately thin enough to sit on top of the control layers labs already run. The reference implementation ships an adapter for each, built on one mechanism: **bindings**. A binding pairs an MHP name with a callable into the foreign layer, and `BoundDriver` turns three lists of bindings into a complete MHP driver with every gate, tier, job and notification inherited.

```python
from openmhp.adapters import BoundDriver, Signal, Setting, Action
dev = BoundDriver(device={"id": "hotplate-01", "class": "hotplate", "notes": "Fume hood 2."},
                  signals=[Signal("plate_temperature", read=lambda: plc.read(0x10), unit="degC")],
                  settings=[Setting("target_temperature", write=lambda v: plc.write(0x20, v),
                                    limits={"min": 20, "max": 300})],
                  actions=[Action("shutdown", run=lambda job, p: plc.write(0x21, 0), approval="confirm")],
                  estop=lambda: plc.write(0x21, 0))
```

| Layer | Adapter | Mapping |
|---|---|---|
| **OPC UA / Modbus** | `opcua_device(url, ...)` | variable node → signal or setting; method node → action with positional args; abort method → estop. Modbus uses `BoundDriver` with two register callables. |
| **ROS 2** | `ros2_device(node, ...)` | topic subscription → signal; topic publication → setting; action server → action with feedback → progress and cancel, reporting the goal's terminal status (aborted is a failure); signals older than `max_age_s` read as no value; Trigger service → estop, with its result checked. |
| **SiLA 2** | `sila_device(host, port, ...)` | property → signal; one-parameter unobservable command → setting; command → action, observable commands stream progress and accept cancel; any stop command → estop. Leases replace LockController. |
| **MADSci** | `madsci_node(url, ...)` | self-describing: `/info` actions → actions with params and notes; `/state` keys → signals; `/status` busy → `ping` state; `/action` + polling → jobs; cancel is sent to the node and the job ends only on a terminal status, and a node that keeps running after a cancel faults the device; `/admin/safety_stop` → estop. No binding map needed. |
| **PyLabRobot** | `plr_device(machine, ...)` | every public coroutine on a `Machine` → action with `params` from its signature and enforced `limits`; `setup()` on start, `stop()` on estop; coroutines run on a private event loop. Actions cannot be cancelled mid-move (use e-stop); an operation that times out is cancelled and faults the device. |
| **MQTT** | `mqtt_device(url, ...)` | subscribed topic → signal (last message cached with its arrival time; stale after `max_age_s`, default 5 s); published topic → setting; a command topic paired with a reply topic → action, correlated by a `job` field in both payloads; without a reply topic an action is fire-and-forget and returns once the broker has acknowledged the publish, which is not the same as the device having acted. Estop publishes at QoS 2; like the action case, that confirms the broker received it, not that the device stopped — pair it with a signal on a state topic to verify. |

Each adapter is a few lines per device; the `openmhp-adapt-fleet` skill (§14.1) walks a harness through a whole fleet. Adapters MUST implement the safety gates in §7 themselves; wrapping a layer that lacks limits does not exempt the MHP server from enforcing them. The reference adapters get this for free from `BoundDriver`. They are tested against fakes of each client library; no vendor system has been exercised yet.

### 14.1 Agent Skills

MHP ships three [Agent Skills](https://agentskills.io) so that any skills-capable harness can bring hardware under the protocol and operate it without bespoke prompting:

| Skill | When it activates | What it does |
|---|---|---|
| `openmhp-onboard-device` | one instrument to connect | interviews the owner, writes descriptor + driver, validates, serves, registers |
| `openmhp-adapt-fleet` | OPC UA / ROS 2 / SiLA 2 / MADSci / PyLabRobot fleet | one adapter file per device, manifest, directory, `mhp-mcp` config, proof checklist |
| `openmhp-operate` | any task on connected hardware | the find → describe → check → dry-run → act → verify loop; refusal handling; e-stop rules |

Skills follow the progressive-disclosure design of the protocol itself: a harness holds only their names and descriptions until a task matches.

---

## 15. Conformance

| Level | Requirements |
|---|---|
| **MHP Core** | `initialize`, `ping`, `device/describe` (all three tiers and `select`), `resources/*`, `signals/read`, `settings/write` with limit enforcement, error codes in §12. |
| **MHP Actions** | Core + `actions/invoke`, `jobs/*`, `notifications/jobs/*`, interlocks and approval gates, and `methods/*` as specified in §4.5 (answering empty and refusing `save` when no action is method-driven). |
| **MHP Safe** | Actions + `safety/estop` that never waits behind ordinary requests, verified `safety/reset`, watchdog, fail-closed state machine with unknown-outcome faults, per-session `session/*` leases with renewal. |
| **MHP Directory** (server role) | `initialize` with `role: "directory"`, `directory/search`, `directory/get`, `directory/stats`; indexes cards only. |

Devices that carry stored energy or can move SHOULD NOT be exposed below **MHP Safe**. All device levels MUST support `detail` and `select` on `device/describe` (§3.1).

Conformance is behavioural. The reference suite `tests/test_safety_gates.py` exercises typed limits, ownership, watchdog silence, rejected approvals, blocked I/O, backend aborts and plan-mode isolation; a conformant implementation should pass equivalent tests.

---

## 16. Not yet specified

In-band authentication, and authentication for the device HTTP transport; request idempotency tokens; multi-device transactions; descriptor signing; a hosted registry beyond the bundled index; sandboxed script execution; streaming bulk data (results are stored as files next to the run, §3.5); a machine-readable description of hardware watchdogs and device-side safe states. Each has a natural home in the protocol (a `data/` primitive, `params.auth`, a `transaction/` namespace) and will be specified with partner input.

---

## Appendix: reference implementation

`openmhp` is a Python implementation of everything above (PyYAML is the only dependency, for device packages): the `Driver` base class with all gates and detail tiers, the device package loader, the live-pinging `Directory`, stdio and HTTP+SSE transports, the lazy `Lab` client SDK, the `mhp` CLI (including `serve-directory`), the eight-tool `mhp-mcp` bridge over stdio or HTTP, `BoundDriver` and the five ecosystem adapters, three Agent Skills (bundled in the package, `mhp skills install`), the fleet and `mhp_lab`, network discovery, the `npx openmhp-cli` launcher, two simulated devices, adapter tests that run against injected fakes, and the 2,000-device scale demo. Writing a new driver is a descriptor plus three hooks (`on_read`, `on_write`, `on_invoke`), with optional `validate_params` and `on_fault`. See `README.md`.

**Status: experimental.** Everything is tested against simulators and fakes; no physical instrument or vendor system has been exercised. §16 lists what is not yet specified.
