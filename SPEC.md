# Open Model Hardware Protocol (MHP)

**Version 2026-09-09 (0.2, draft for early partners)**
An open protocol for AI agents to discover, understand and safely operate physical devices.

---

## 1. Why MHP

Every instrument on a bench or factory floor has its own programming interface. Connecting them to each other is hard; connecting them to an AI agent is harder, because the agent needs three things no vendor API provides: a uniform way to *read and write* the device, a machine-readable account of *what the device is and how to use it safely*, and a way to *hand off long-running work* so the device can run without the agent reasoning at every step.

MHP answers all three with one small protocol. It borrows the shape of the Model Context Protocol (MCP): JSON-RPC 2.0 messages, a short list of primitives, capability negotiation at connect time, and a host/client/server split. Where MCP exposes *tools, resources and prompts*, MHP exposes *signals, settings, actions and a safety envelope*, all described by one **device descriptor** that the driver serves and the agent reads before touching anything.

Design rules, in priority order:

1. **Safety is enforced by the driver, never by the agent.** Limits, interlocks and approval levels live in the descriptor and are checked on the device side of the wire. A wrong value from an agent is refused, not obeyed.
2. **One descriptor is the whole manual.** Everything an agent needs, including the tacit knowledge that used to live in paper manuals and people's heads, is written in natural-language `notes` fields on the descriptor.
3. **Five primitives, no more.** A device that speaks describe / signals / settings / actions / safety can be operated by any MHP host.
4. **Bridge, don't replace.** SiLA 2, PyLabRobot, MADSci, OPC UA and ROS 2 devices become MHP devices through thin adapters; MHP is the layer the agent sees.
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
| **Host** | The agent runtime. Owns the conversation with the model, decides what to do, holds one client per device. Presents human confirmation prompts (elicitation). |
| **Client** | One connection to one server. Sends requests, receives responses and notifications, tracks the lease. |
| **Server (driver)** | Owns exactly one device. Serves the descriptor, enforces the safety envelope, translates primitives into vendor commands, runs jobs. |
| **Device** | The physical thing. May be a single instrument or a coordinated cell exposed as one logical device. |

A server MAY be an **adapter** that wraps another control layer (SiLA 2 feature, PyLabRobot backend, MADSci node) rather than raw hardware. From the host's point of view there is no difference.

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
| `directory/get` | `id` | one card + target, state pinged now |
| `directory/stats` | | counts by class and state |

Ranking is BM25 over id, class, make, model, location, tags, notes and the names of signals, settings and actions, so a query like *"heat a 96-well plate to 95 °C for PCR in bay 12"* finds thermocyclers in bay 12 without the agent knowing any ids. Filters are exact. `state` lets an agent ask for an idle instrument.

A directory is built by asking each device for its card once (`device/describe {detail: "card"}`), or from a manifest file the lab maintains. **State is never served from the index.** The index holds only what is static about a device (identity, location, tags, capability names). At query time the directory pings the top candidates in parallel with a short timeout (the reference uses 500 ms and pings four times `limit` candidates when a `state` filter is given), fills in each card's `state` from the answer, and only then applies the filter. `directory/get` always pings. A device that does not answer is reported as `unreachable` and never matches `state: "idle"`. A client MAY pass `live: false` to skip pinging when it only wants identity, and MUST still treat the device's own `describe` or `ping` as authoritative before acting.

Small labs need no directory: a client with an explicit name-to-target map scans its own devices' cards.

### 3.3 Constant tool surface

An MCP host connected to an MHP lab sees **eight tools regardless of device count**: `mhp_find`, `mhp_describe`, `mhp_read`, `mhp_write`, `mhp_invoke`, `mhp_job`, `mhp_estop`, `mhp_run`. There are never per-device tools. The device descriptor, loaded on demand, is the documentation. Bridges MUST NOT enumerate devices into the tool list or the resource list at startup; resources list only the devices the session has opened.

### 3.4 Programmatic runs

`mhp_run` executes an orchestration script against the lab and returns only what it prints, capped. A script that takes five hundred temperature readings and reports a mean puts one line in the model's context, not five hundred numbers. The script sees the same `Lab` client as §10.3, and every call it makes passes the same safety gates as a direct tool call. Hosts SHOULD sandbox script execution; the reference implementation runs scripts in-process so simulated device state is shared, and says so.

### 3.5 Examples in the descriptor

Actions MAY carry `examples`, an array of realistic parameter objects. Bridges MUST forward them (the reference bridge exposes them through `mhp_describe`, and its own tools ship `input_examples`). A schema says what is valid; an example says what is normal.

### 3.6 Measured

The reference `examples/scale_demo.py` builds 2,000 simulated devices across 8 classes and 40 bays.

| | Tokens in agent context |
|---|---|
| Every descriptor loaded up front | 937,845 |
| `mhp_find` (5 cards) + summary of the chosen device (with its operating instructions) + full spec of the 2 items used | 1,087 |

That is 0.11% of the naive cost, with search taking well under a millisecond. The device is then operated through exactly the same primitives as in a two-device lab.

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
└── scripts/           Level 3: ready-made orchestration scripts for mhp_run
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
mhp: "2026-09-09"
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
    interlocks: [lid_closed]     # signals that must be truthy
    params:
      steps: array of {temp: degC, hold_s: number}
      cycles: integer
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
  watchdog_s: 10                 # driver fails safe if no ping within this window
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
- `type` is one of `number | integer | boolean | string | object | array`. `unit` SHOULD be a UCUM code or a common spelled-out unit (`degC`, `mm`, `percent`, `N`, `rpm`).
- `limits` on a setting: `{min, max}` for numbers, `{enum: [...]}` for strings. The driver MUST refuse writes outside limits with `LimitViolation`.
- `limits` on an action: a map from parameter name to `[min, max]`. Drivers SHOULD enforce these; the reference driver enforces them inside `on_invoke`.
- `approval`: `auto` (agent may act), `confirm` (each call needs `approved: true`, which the host MAY only set after human confirmation), `forbid` (never agent-operable; listed so the agent knows the capability exists and why it is off-limits).
- `interlocks`: names of boolean signals that MUST read truthy at the moment of the write or invoke; otherwise `InterlockOpen`.
- `duration`: `short` actions are expected to finish within seconds and hosts MAY block on them; `long` actions run as jobs and the host SHOULD poll or subscribe.
- `location` and `tags` on `device` are optional but SHOULD be set: they are what a directory filters on. `examples` on an action is an array of parameter objects.
- Unknown top-level keys (for example `locations`) are permitted and MUST be preserved by adapters and bridges. Device classes define their own conventions.

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
| Actions | `actions/list`, `actions/invoke`, `jobs/status`, `jobs/list`, `jobs/cancel` | client → server |
| Safety | `safety/limits`, `safety/estop`, `safety/reset` | client → server |
| Session | `session/acquire`, `session/release` | client → server |
| Notifications | `notifications/signals/update`, `notifications/settings/changed`, `notifications/jobs/{started,progress,finished}`, `notifications/safety/{estop,reset}` | server → client |
| Elicitation | `elicitation/confirm` | server → client (optional; see §7.4) |

### 5.1 `initialize`

```json
→ {"jsonrpc":"2.0","id":1,"method":"initialize",
   "params":{"protocolVersion":"2026-09-09","clientInfo":{"name":"claude-lab","version":"1.0"}}}
← {"jsonrpc":"2.0","id":1,"result":{
     "protocolVersion":"2026-09-09",
     "device":{"id":"thermocycler-01","class":"thermocycler","make":"SimBio","model":"TC-96"},
     "capabilities":{"signals":true,"settings":true,"actions":true,
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

Optional params: `approved: true` (for `confirm` settings), `dryRun: true` (run every gate, touch nothing, return `wouldWrite`).

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

Job states: `queued → running → done | failed | cancelled`. A `failed` job puts the device in `fault` until `safety/reset`. A device that is `busy` refuses a second non-concurrent invoke with `DeviceBusy`.

### 5.6 Safety

- `safety/limits` returns the effective limits, interlocks and approval levels in one call, for hosts that want to show the envelope to a human.
- `safety/estop` MUST stop all motion and energy output as fast as the hardware allows, cancel every running job, and put the device in `estop`. It MUST succeed regardless of lease, approval level or interlock state. It is the one call an agent may always make.
- `safety/reset` returns the device to `idle` after `estop` or `fault`. It MUST fail with `DeviceBusy` while any job is still running.

### 5.7 Session leases

`session/acquire {ttl}` gives the calling client exclusive write/invoke rights until `ttl` seconds elapse or `session/release`. Reads, `ping`, `describe` and `estop` are never blocked by a lease. Leases let an orchestration script own several devices for the duration of a protocol without a second agent interleaving commands.

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
  │── ping (< watchdog_s) ──────────────▶│  keeps the watchdog fed
  │── session/release ──────────────────▶│
```

**Watchdog.** If the descriptor declares `safety.watchdog_s`, the server MUST fail safe (the device-specific equivalent of e-stop, or at minimum refusing further writes) when it has received no request from the lease holder within that window. This is what protects the lab when the agent process dies mid-protocol.

**Versioning.** `protocolVersion` is a date string, as in MCP. A server MUST answer `initialize` with the highest version it supports that is ≤ the client's; a client that receives an older version MUST either speak it or disconnect.

---

## 7. Safety model

The safety model is the reason MHP exists as a separate protocol rather than a set of MCP tools. Every rule below is enforced **in the server**, on the device side of the network, so it holds even when the agent is wrong, compromised or has lost context.

### 7.1 Gate order

On every `settings/write` and `actions/invoke` the server evaluates, in order:

1. **State**: `estop` → `EStopActive`; `fault` → `DeviceFault`.
2. **Approval**: `forbid` → `Forbidden`; `confirm` without `approved:true` → `ApprovalRequired`.
3. **Interlocks**: each named signal is read live; any falsy → `InterlockOpen`.
4. **Limits**: numeric range or enum → `LimitViolation`.
5. **Lease**: another client holds an unexpired lease → `NotLeased`.
6. **Busy**: a non-concurrent job is running → `DeviceBusy`.

Only after all six pass does vendor code run. `dryRun: true` stops after step 6 and reports what would have happened.

### 7.2 Approval levels and elicitation

`confirm` is the bridge between agent autonomy and human oversight. The intended flow:

1. Agent calls `actions/invoke {name:"open_lid"}` → `ApprovalRequired`.
2. Host shows the human a confirmation with the action's `notes` ("Lid may be hot; a human should be present.").
3. Human confirms; host re-sends with `approved: true`.

A host MUST NOT set `approved: true` on the model's say-so alone. Servers that can reach a human directly (a touchscreen on the instrument, a physical key switch) MAY instead implement `elicitation/confirm` as a server-initiated request and wait for the answer in-band.

### 7.3 Fail closed

Any exception inside vendor code during a job moves the device to `fault`. `fault` and `estop` block all writes and invokes until an explicit `safety/reset`. There is no automatic recovery; a human or the agent must decide the device is safe to resume.

### 7.4 Defence in depth

Descriptor limits protect setpoints. Action parameters (a PCR step at 200 °C inside an otherwise valid protocol) are the driver's responsibility; drivers SHOULD validate parameters against the same physical limits and MAY publish them under `actions[].limits`. The reference thermocycler does both.

### 7.5 What MHP does not do

MHP is not a functional-safety system in the IEC 61508 sense. Hard-wired e-stops, light curtains and PLC safety logic remain the primary layer; MHP is the layer that keeps an agent from *asking* for something unsafe, and gives it a standard way to stop everything when it sees something wrong.

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
| `notifications/safety/estop` | `{by, reason}` | e-stop engaged by any client |
| `notifications/safety/reset` | `{by}` | device returned to idle |

---

## 9. Transports and discovery

MHP defines two transports, mirroring MCP:

- **stdio**: newline-delimited JSON-RPC on the driver process's stdin/stdout. For a driver running on the bench PC, launched by the host.
- **HTTP**: `POST /rpc` for requests; `GET /events` as a Server-Sent Events stream of notifications; `GET /mhp.json` returns the descriptor with no handshake, so an agent (or a person with `curl`) can learn what a device is from its URL alone. Clients SHOULD send an `X-MHP-Client` header so leases and audit logs can name them.

**Network discovery.** Servers SHOULD advertise via mDNS/DNS-SD as `_mhp._tcp` with TXT records `id`, `class`, `path=/mhp.json`. Labs MAY additionally run a registry that lists device URLs; the reference `Lab` client accepts a plain name→URL map so no registry is required to start.

**Authentication** is transport-level and out of scope for 0.1: HTTP deployments SHOULD sit behind TLS with bearer tokens or mTLS. The protocol reserves `params.auth` for a future in-band scheme.

---

## 10. Three control surfaces

The same five primitives are reachable three ways. They compose: an agent uses MCP to explore and decide, writes a code file for the parts that must run fast or long, and uses the CLI to check on it.

### 10.1 MCP bridge

A single MCP server exposes a whole lab to Claude or any MCP host through eight generic tools (§3.3), each with `input_examples`. Because the descriptor *is* the documentation, no per-device tool code is written, and the tool list does not grow with the lab.

| MCP tool | MHP call |
|---|---|
| `mhp_find` | `directory/search` (or a scan of cards in a small lab) |
| `mhp_describe` | `device/describe {detail, select}`, default `summary`; with `resource=` it calls `resources/read` |
| `mhp_read` | `signals/read` |
| `mhp_write` | `settings/write` |
| `mhp_invoke` | `actions/invoke` (+ optional wait) |
| `mhp_job` | `jobs/status` / `jobs/cancel` |
| `mhp_estop` | `safety/estop` on one device or every device this session touched |
| `mhp_run` | runs a script against the `Lab` client; returns stdout only (§3.4) |
| resource `mhp://<id>/descriptor`, `mhp://<id>/<path>` | descriptor and package resources of devices this session has opened |

MHP errors surface as MCP tool results with `isError: true` and the structured `mhpError` body, so the model sees *why* a write was refused and can adjust. A refused call inside an `mhp_run` script returns the same body.

```bash
mhp-mcp --directory http://directory:18900               # big lab: nothing loaded until searched
mhp-mcp --directory http://directory:18900 --http 18800  # same, over MCP Streamable HTTP for remote harnesses
mhp-mcp thermo=http://bench:18921 arm=http://arm-pc:18921   # small lab: cards indexed at start
```

The bridge is the lab's MCP server. Any harness that speaks MCP over stdio or HTTP (Claude Code, Claude Desktop, Cursor, Gemini CLI, OpenHands, a custom agent) connects to it and sees the same eight tools.

### 10.2 Command line

```bash
mhp http://bench:18921 describe
mhp http://bench:18921 read block_temperature lid_closed
mhp http://bench:18921 write target_temperature 95
mhp http://bench:18921 invoke run_protocol '{"steps":[...],"cycles":30}' --wait
mhp http://bench:18921 invoke open_lid --approved      # after a human said yes
mhp http://bench:18921 estop "smoke from lid"
```

The CLI is the debugging and shell-scripting surface, and what an agent reaches for inside a Bash tool.

### 10.3 Code files (SDK)

```python
from openmhp.client import Lab

lab = Lab({"arm": "http://arm-pc:18921", "thermo": "http://bench:18921"})
arm, thermo = lab["arm"], lab["thermo"]

with arm, thermo:                                    # leases on both
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
| -32020 | DeviceFault | device in `fault`; reset required |
| -32021 | DeviceBusy | non-concurrent job running, or reset attempted mid-job |
| -32022 | EStopActive | device in `estop`; reset required |
| -32030 | NotLeased | another client holds the lease (`data.holder`) |
| -32040 | UnknownName | no such signal/setting/action |
| -32041 | JobNotFound | no such job id |

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
| **SiLA 2** | `sila_device(host, port, ...)` | property → signal; one-parameter unobservable command → setting; command → action, observable commands stream progress and accept cancel; any stop command → estop. Leases replace LockController. |
| **PyLabRobot** | `plr_device(machine, ...)` | every public coroutine on a `Machine` → action with `params` from its signature; `setup()` on start, `stop()` on estop; coroutines run on a private event loop. |
| **MADSci** | `madsci_node(url, ...)` | self-describing: `/info` actions → actions with params and notes; `/state` keys → signals; `/status` busy → `ping` state; `/action` + polling → jobs; `/admin/safety_stop` → estop. No binding map needed. |
| **OPC UA / Modbus** | `opcua_device(url, ...)` | variable node → signal or setting; method node → action with positional args; abort method → estop. Modbus uses `BoundDriver` with two register callables. |
| **ROS 2** | `ros2_device(node, ...)` | topic subscription → signal; topic publication → setting; action server → action with feedback → progress and cancel; Trigger service → estop. |

Each adapter is a few lines per device; the `openmhp-adapt-fleet` skill (§14.1) walks a harness through a whole fleet. Adapters MUST implement the safety gates in §7 themselves; wrapping a layer that lacks limits does not exempt the MHP server from enforcing them. The reference adapters get this for free from `BoundDriver`.

### 14.1 Agent Skills

MHP ships three [Agent Skills](https://agentskills.io) so that any skills-capable harness can bring hardware under the protocol and operate it without bespoke prompting:

| Skill | When it activates | What it does |
|---|---|---|
| `openmhp-onboard-device` | one instrument to connect | interviews the owner, writes descriptor + driver, validates, serves, registers |
| `openmhp-adapt-fleet` | SiLA 2 / PyLabRobot / MADSci / OPC UA / ROS 2 fleet | one adapter file per device, manifest, directory, `mhp-mcp` config, proof checklist |
| `openmhp-operate` | any task on connected hardware | the find → describe → check → dry-run → act → verify loop; refusal handling; e-stop rules |

Skills follow the progressive-disclosure design of the protocol itself: a harness holds only their names and descriptions until a task matches.

---

## 15. Conformance

| Level | Requirements |
|---|---|
| **MHP Core** | `initialize`, `ping`, `device/describe` (all three tiers and `select`), `resources/*`, `signals/read`, `settings/write` with limit enforcement, error codes in §12. |
| **MHP Actions** | Core + `actions/invoke`, `jobs/*`, `notifications/jobs/*`, interlocks and approval gates. |
| **MHP Safe** | Actions + `safety/estop`, `safety/reset`, watchdog, fail-closed state machine, `session/*` leases. |
| **MHP Directory** (server role) | `initialize` with `role: "directory"`, `directory/search`, `directory/get`, `directory/stats`; indexes cards only. |

Devices that carry stored energy or can move SHOULD NOT be exposed below **MHP Safe**. All device levels MUST support `detail` and `select` on `device/describe` (§3.1).

---

## 16. Not in 0.1

Bulk data transfer (images, spectra) beyond a URI in a job result; in-band authentication; multi-device transactions; descriptor signing; a hosted registry. Each has a natural home in the protocol (a `data/` primitive, `params.auth`, a `transaction/` namespace) and will be specified with partner input.

---

## Appendix: reference implementation

`openmhp` is a Python implementation of everything above (PyYAML is the only dependency, for device packages): the `Driver` base class with all gates and detail tiers, the device package loader, the live-pinging `Directory`, stdio and HTTP+SSE transports, the lazy `Lab` client SDK, the `mhp` CLI (including `serve-directory`), the eight-tool `mhp-mcp` bridge over stdio or HTTP, `BoundDriver` and the five ecosystem adapters, three Agent Skills, two simulated devices, adapter tests that run against injected fakes, and the 2,000-device scale demo. Writing a new driver is a descriptor plus three hooks (`on_read`, `on_write`, `on_invoke`). See `README.md`.
