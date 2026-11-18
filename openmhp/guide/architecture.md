<!-- generated from https://openmhp.com/architecture by scripts/build_guide.py; edit the website, not this file -->

# Architecture

How OpenMHP is actually put together: who talks to whom, what the two protocol layers do, and a full worked example on the wire. This is the accessible walkthrough; [the specification](https://openmhp.com/spec) is the normative contract.

This page covers OpenMHP's [scope], its [core concepts] — participants and layers — and a [step-by-step example] showing each one on the wire. If you already know how the Model Context Protocol is put together, most of this will feel familiar: OpenMHP reuses MCP's shape on purpose. The parts that don't map onto MCP at all are the point of this page, because they are the parts a physical instrument needs that a software tool never did.

## Scope

OpenMHP is more than the wire format. The project includes:

- [**The specification**](https://openmhp.com/spec), which sets out what a client and a server MUST, SHOULD and MAY do.

- **A reference implementation** in Python (`openmhp`): the driver base class, the client SDK, the MCP bridge, the CLI, and a package validator.

- **Reference device packages** — a simulated thermocycler, plate arm and gas chromatograph — that exercise the whole protocol with nothing plugged in.

- **A behavioral conformance suite** (`tests/test_safety_gates.py` and friends) that stands in for a formal test harness: passing an equivalent suite is what "conformant" means.

> OpenMHP is scoped to **operating a physical device safely** — describing it, reading and writing it, running long jobs on it, and stopping it. It does not dictate how an agent decides what to run, or which model powers it.

## Concepts

### Participants

OpenMHP follows the same client-server shape MCP does, with one addition MCP has no need for: the device itself.

- **Host** — the agent runtime around the model. It holds one client per device, is the one thing on the network trusted to set `approved: true`, and is where a person's confirmation actually lands.

- **Client** — one connection to one server. Sends requests, receives responses and pushed notifications, and tracks that connection's lease.

- **Server** — usually called a **driver**. Owns exactly one device: serves its descriptor, enforces every safety gate, and translates OpenMHP calls into whatever the vendor actually speaks. A server that wraps an existing control layer instead of raw hardware — an OPC UA server, a SiLA 2 feature, a MADSci node — is an **adapter**, and from the host's side of the wire there is no difference.

- **Device** — the physical thing. Usually one instrument; sometimes a coordinated cell (an arm and a thermocycler that hand a plate back and forth) exposed as one logical device.

- **Directory** — an optional server whose role is finding devices rather than being one. It indexes cards, not descriptors, keeps no open connection to what it lists, and answers `directory/search` instead of the device primitives.

- **Gateway** — optional, for labs whose network nothing outside may enter. Bench PCs connect *out* to it and register their devices; it serves each one to hosts at an ordinary HTTP address, plus a directory of all of them. A host cannot tell a relayed device from a local one. The gateway authenticates hosts, so it is where `approved: true` is trusted from, and it hands each request to the bench PC once or not at all.

**For example:** a scientist's agent harness — Claude Code, say — is the host for its connection to a lab's MCP bridge; that connection is one MCP client, and the bridge is the MCP server on the other end of it. Inside the bridge, a second, independent client-server relationship starts: the bridge is now an *OpenMHP host*, and it opens one OpenMHP client for every device the conversation touches — a serial connection to a real thermocycler, a SiLA 2 adapter talking gRPC to a liquid handler. The agent never sees this second layer; it only sees the eleven MCP tools the bridge exposes. This nesting is deliberate: **MCP is how a model reaches the bridge; OpenMHP is how the bridge reaches hardware**, and a harness that has no interest in MCP at all can use the OpenMHP client SDK or the CLI directly, skipping the top layer entirely.

### Layers

OpenMHP consists of two layers, the same split MCP makes:

- **Data layer.** The JSON-RPC 2.0 protocol itself: capability negotiation, the six primitives, and notifications. This is the inner layer — everything a driver author or a client author actually reasons about.

- **Transport layer.** How bytes move between a client and a server: stdio for a driver next to the instrument, HTTP (+ Server-Sent Events for notifications) for one reachable across the lab network, or through a [gateway](https://openmhp.com/gateway) when the lab network is closed. This is the outer layer; the same JSON-RPC messages cross any of them unchanged.

## The data layer protocol

### Capability negotiation

Every connection opens with `initialize`, which a server MUST answer before anything else. The response carries the negotiated protocol version and a set of booleans — a client MUST NOT call a method whose capability is false, so a device with no watchdog, or no method-driven action, says so up front instead of failing later.

```
→ {"jsonrpc":"2.0","id":1,"method":"initialize",
   "params":{"protocolVersion":"2026-09-12","clientInfo":{"name":"claude-lab","version":"1.0"}}}
← {"jsonrpc":"2.0","id":1,"result":{
     "protocolVersion":"2026-09-12",
     "device":{"id":"thermocycler-01","class":"thermocycler","make":"SimBio","model":"TC-96"},
     "capabilities":{"signals":true,"settings":true,"actions":true,"methods":false,
                     "subscribe":true,"lease":true,"estop":true}}}
```

### Primitives

MCP defines three things a server can offer: tools, resources, prompts. OpenMHP defines six, shaped around operating something rather than informing something:

| Primitive | Wire methods | What it's for |
|---|---|---|
| **Describe** | `device/describe` | The card, the operating instructions, and the full machine-readable spec, at three tiers of detail — the closest analogue to MCP's resources, but always about the device itself. |
| **Signals** | `signals/read`, `signals/subscribe` | Read-only measurements: a temperature, a door sensor, a reading. |
| **Settings** | `settings/write` | A value the device holds and acts on continuously, like a setpoint — distinct from an action because it has no notion of "finished." |
| **Actions** | `actions/invoke`, `jobs/*` | Something that takes time and returns a job — MCP's tools, but able to run for an hour and be paused, resumed or cancelled while it does. |
| **Safety** | `safety/limits`, `safety/estop`, `safety/reset`, `session/*` | No MCP equivalent. Emergency stop, verified recovery, and the lease a session holds while it controls a device — covered in its own section below. |
| **Methods** | `methods/*` | Also no MCP equivalent. Named, versioned parameter sets an instrument keeps for itself, for procedures that change per project or compound (see [SPEC.md §4.5](https://github.com/kushalsinha/openmhp/blob/main/SPEC.md)). |

A signal read looks almost exactly like an MCP resource read:

```
→ {"method":"signals/read","params":{"names":["block_temperature","lid_closed"]}}
← {"result":{"values":{"block_temperature":22.0,"lid_closed":true},"ts":1788991266.5}}
```

Invoking an action looks almost exactly like an MCP tool call, except it comes back with a job instead of a result, because a 30-cycle PCR program does not finish inside one request:

```
→ {"method":"actions/invoke","params":{"name":"run_protocol",
     "params":{"steps":[{"temp":95,"hold_s":30},{"temp":58,"hold_s":30},{"temp":72,"hold_s":45}],"cycles":30}}}
← {"result":{"job":{"id":"job_04324008","action":"run_protocol","state":"queued","progress":0.0}}}
```

### The safety envelope — why this isn't just MCP with new tool names

> The safety model is the reason OpenMHP exists as a separate protocol rather than a library of MCP tools. Every rule below runs **inside the server**, on the device side of the wire, so it holds even when the agent asks for the wrong thing, has lost context, or is actively adversarial.

Every `settings/write` and `actions/invoke` passes six gates, always in this order, before any vendor code runs at all:

| # | Gate | Refuses with |
|---|---|---|
| 1 | State | `estop` or `fault` blocks everything |
| 2 | Approval | `forbid` always; `confirm` without a real confirmation |
| 3 | Interlocks | a named signal that isn't exactly `true`, live, right now |
| 4 | Value or params | wrong type, out of bounds, or fails the driver's own validation |
| 5 | Lease | another session holds control, or a watchdog device has no lease held at all |
| 6 | Busy | a job that can't run alongside another is already running |

A dry run (`dryRun: true`) evaluates all six without touching the device, so a rehearsal can show a person exactly what would happen. Two of these gates are worth calling out by name, because there's nothing like them in a protocol for software tools:

- **Approval and the trust boundary.** `approved: true` means a specific person said yes to this specific request — never something the model can assert about itself. The host strips any `approved` value the model sends, presents the request to a person through MCP elicitation, and only on an explicit yes does it resend the same request with its own `approved: true`. No elicitation channel means no trusted way to ask, so confirm-gated actions are simply unavailable rather than silently allowed.

- **The watchdog and fail-closed state.** A device that declares a watchdog requires the calling session to hold a lease, renewed by a heartbeat; go silent past the window and the device stops itself. Any write whose outcome is uncertain, or any exception mid-job, latches the device in `fault` rather than assuming it's fine — recovery needs a `safety/reset` that verifies the device, not one that just clears a flag.

### Notifications

Like MCP, OpenMHP servers push notifications — JSON-RPC messages with no `id`, expecting no reply — so a client doesn't have to poll for what changed:

```
← {"method":"notifications/jobs/finished","params":{"job":{"id":"job_04324008","state":"done",
     "progress":1.0,"result":{"cycles_completed":30,"final_block_temperature":72}}}}
```

Signal updates, job progress and completion, safety events (estop, fault, reset) and saved methods all arrive this way, over whatever transport connects the device. The reference MCP bridge subscribes to every device it opens and relays what it receives, so an agent reads `mhp_data op='updates'` instead of polling an instrument that produces a new result every few seconds.

## Example: a full exchange

Putting the pieces together — a host operating a thermocycler's lid, which is deliberately confirm-gated because it's hot enough to burn someone.

### 1. Capability negotiation

The host's client sends `initialize`, shown above. It sees `"actions": true`, so it knows `actions/invoke` is safe to try.

### 2. Describe, at the tier the moment needs

Before doing anything, the host asks for a summary — card plus operating instructions plus a slim capability table, under 1,000 tokens regardless of how large the full descriptor is:

```
→ {"method":"device/describe","params":{"detail":"summary"}}
← {"result":{"id":"thermocycler-01","class":"thermocycler","state":"idle",
     "instructions":"...","actions":[{"name":"open_lid","duration":"short",
     "approval":"confirm","interlocks":["lid_cool"]}], ...}}
```

### 3. Try the action — and get refused

The model asks for `open_lid`. The host sends the request with no approval, because it never asserts one on the model's behalf:

```
→ {"method":"actions/invoke","params":{"name":"open_lid"}}
← {"error":{"code":-32012,"message":"'open_lid' requires a person's confirmation",
     "data":{"approval":"confirm"}}}
```

### 4. The host asks a person

Through MCP elicitation, the host shows the device, the action and the descriptor's notes to whoever is at the keyboard, and waits for an explicit answer. Nothing about this step is visible to the model — it is a conversation between the host and a human.

### 5. Confirmed, the same request succeeds

```
→ {"method":"actions/invoke","params":{"name":"open_lid","approved":true}}
← {"result":{"job":{"id":"job_9a21","action":"open_lid","state":"running","progress":0.0}}}
```

### 6. The result arrives pushed, not polled

```
← {"method":"notifications/jobs/finished","params":{"job":{"id":"job_9a21","state":"done",
     "progress":1.0,"result":{"lid_closed":false}}}}
```

Six steps, and every one of them is something a plain MCP tool call cannot express on its own: a refusal enforced by the server rather than a convention the model follows, a confirmation that only a host can grant, and a result delivered instead of fetched. That's the whole difference between wrapping an instrument in MCP tools and giving it an OpenMHP driver.

## Where to go next

[**Specification**The normative contract this page is a walkthrough of, one page per section.](https://openmhp.com/spec) [**Design principles**Why the protocol is shaped this way, not just what the shape is.](https://openmhp.com/design) [**Features**Every capability this architecture makes possible, grouped by what it's for.](https://openmhp.com/features) [**Add an instrument**Put a real driver behind these primitives.](https://openmhp.com/add-a-device)
