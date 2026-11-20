<!-- generated from https://openmhp.com/features by scripts/build_guide.py; edit the website, not this file -->

# Features

Everything OpenMHP does today, grouped by what it's for. If you're deciding whether to build on it or contribute to it, this is the map.

## Protocol core

- **Six primitives.** Describe, signals (read), settings (write), actions (jobs), safety — and **methods**, for instruments that run a different named procedure per project or compound (an HPLC or GC method, a PCR program, a diffraction scan). Every device answers all six; only the instruments that need methods keep any.

- **JSON-RPC 2.0**, the same wire shape MCP uses, over stdio or HTTP, with capability negotiation on connect and version fallback so a newer bridge still talks to an older device.

- **Three-tier progressive disclosure.** A device's full descriptor can run to hundreds of lines; `device/describe` serves a ~40-token card, a summary under 1k tokens, or the full detail for named items only, so search results cost the same whether the lab has two devices or two thousand.

- **Device classes and free-text notes.** A vocabulary for common instrument kinds, plus natural-language fields everywhere for the tacit knowledge a manual never wrote down.

## Safety, enforced in the driver

- **Six gates, one fixed order.** State → approval → interlocks → typed value or params → lease → busy, on every write and invoke, dry runs included. Nothing about it depends on what the agent believes.

- **Typed, bounded values.** A setting or an action parameter is checked for type, finiteness and limits before any vendor code runs; a number cannot smuggle a string, an integer cannot smuggle a float, and control characters are refused outright.

- **Approval levels.** `auto`, `confirm` or `forbid`, written by the device's owner. `confirm` is enforced through MCP elicitation; a model cannot set `approved: true` on its own request — only the host can, and only after a person actually said yes to that exact call.

- **Fail-closed state machine.** An exception mid-job, or a write whose outcome is uncertain (the command may or may not have reached the device), latches `fault` with `outcome: unknown`. Recovery needs `safety/reset`, which verifies the device rather than clearing a flag.

- **A watchdog that arms itself.** Whenever a session holds a lease on a device that declares one, a background scheduler checks it; go silent past the declared window and the device fails safe on its own. The reference client renews it with a heartbeat, so correct use never notices it.

- **Emergency stop, unconditionally.** Allowed regardless of lease, approval or interlock state, and run outside the request lock so it never waits behind a blocking vendor call. One call can e-stop every device a session has touched.

## Human in the loop

- **Pause and resume** on long-running jobs, so a person can step in without reaching for the emergency stop.

- **Operator-run instruments.** A "manual" device's action waits in `waiting_operator` until a person acknowledges it — the protocol never reports something done before a human actually did it.

- **Safety cards.** Generated per device, evidence-based: each probe reports `passed`, `failed`, or explicitly `not exercised` (an e-stop and a watchdog can't be safely tested without hardware). No readiness verdict — the card says outright it is not a safety certification.

## Long-running work, data and events

- **Jobs.** An action returns immediately with a job id; poll it, wait on it, or subscribe, with states that include `waiting_operator` and an uncertain `outcome` for a failure whose physical effect is unknown.

- **Every device pushes.** Signal updates, job progress and completion, safety events and saved methods arrive as notifications without being asked, over whatever transport connects the device — in-process, HTTP Server-Sent Events, or stdio, all handled the same way.

- **`mhp_data op='updates'`.** An agent reads what a device already pushed instead of polling it, which matters for an instrument producing a new result every few seconds.

- **Background runs with real records.** Each run gets its own directory, its saved files, and now an `events.jsonl` of everything a device it used pushed while it ran.

- **A restart-safe run log.** Append-only, sequence numbers that persist across a bridge restart, so an agent's history of what happened doesn't reset when the process does.

## Plan mode

- **Every write and invoke becomes a dry run** through all six safety gates — nothing physically moves, but every refusal, every approval point, every interlock is evaluated for real.

- **Virtual time.** A script that waits 30 minutes for a setpoint rehearses in effectively no time.

- **A step budget** bounds a runaway loop instead of letting a rehearsal hang.

- **A strict read-only allowlist** on raw RPC calls, so the one general-purpose escape hatch in the client can never become a way to actuate hardware from inside a plan.

- The result: the ordered plan, which steps need a human, which are long-running, and the first step that would be refused — something concrete to show a person before anything heats or moves.

## Methods

- **Named, versioned, project-owned parameter sets.** The same GC runs a different method for every compound and every project; a method is data the device keeps, not something baked into a driver.

- **Validated before it's ever saved.** Saving a method runs it through the device's own parameter gate first — a method that would be refused is never written.

- **Device-assigned versions and content hashes.** Full history retained; deleting a method retires it rather than erasing it.

- **Provenance on every job.** A result is always traceable to the exact method, version and hash (plus any one-off overrides) that produced it.

- **"Which one?" is the first move, not a fallback.** A method-driven action invoked with nothing to go on tells the agent exactly what to ask: one match, use it; several, ask a person (or take the current project's, in an unattended loop); none, ask for the parameters and save them.

## Getting instruments connected

- **Server-run onboarding.** An interview in plain language writes the whole device package — card, operating instructions, safety envelope, and for manual or serial instruments a working driver — with no code from the person answering.

- **No-code drivers.** `manual` for hand-operated instruments, `serial_ascii` for anything that takes text commands over a USB or serial port with the command list pasted straight from a manual.

- **Adapters for existing ecosystems.** OPC UA, ROS 2, SiLA 2, MADSci, PyLabRobot and MQTT devices join in a few lines each, on a shared `BoundDriver` scaffold, without OpenMHP replacing anything already working underneath.

- **Simulated twins.** Every bundled and community package ships a `sim.py`, so a procedure can be rehearsed or demoed with nothing plugged in.

- **A community registry.** Contributed packages, added by `github:` target — one instrument someone else already described is one your lab doesn't have to.

- **Lab PCs behind a firewall.** `mhp node --join` dials out over HTTPS to an `mhp gateway` on the company network and registers its instruments; agents reach them at the gateway. Pairing is a one-time code, every connection is outbound, a request is delivered once or not at all, and the gateway is the approval boundary. [How it works](https://openmhp.com/gateway).

## Scale and harness ergonomics

- **A directory that scales past thousands of devices.** Cards, not descriptors, indexed with BM25 search; live state is pinged only for the candidates a query actually needs and never baked into the static index.

- **A constant tool surface.** An MCP host sees eleven tools whether the lab has two devices or two thousand — never one tool per device.

- **Worked examples everywhere.** Every tool schema and every descriptor action carries realistic `input_examples`, because a schema alone doesn't teach conventions.

- **Recipes.** Tested, parameterized scripts an agent finds and adapts instead of writing from scratch, runnable directly or rehearsed through plan mode first.

- **Three Agent Skills** matching the three real workflows: onboarding one instrument, adapting a whole existing fleet, and day-to-day operation.

- **Three control surfaces, one protocol.** The MCP bridge (stdio, or bearer-token and Origin-checked HTTP) for an agent; a CLI for scripting and debugging from a terminal; a Python SDK for code that chains steps across devices, for work that runs longer or faster than an agent should reason about live.

## Where to go next

[**Design principles**The thought process behind these choices, and what stays fixed as the protocol grows.](https://openmhp.com/design) [**Architecture**Who talks to whom, and a full worked example on the wire.](https://openmhp.com/architecture) [**Quickstart**One command, then talk to your agent.](https://openmhp.com/quickstart) [**Specification**The normative contract, one page per section.](https://openmhp.com/spec) [**Roadmap**What's shipped, what's next, and what stays out of scope.](https://openmhp.com/roadmap)
