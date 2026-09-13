<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/hero-dark.svg">
    <img src="assets/hero.svg" alt="OpenMHP" width="520">
  </picture>
</p>

<h3 align="center">The open protocol for AI agents to run lab instruments</h3>

<p align="center">Install it once. Tell your agent to find your instruments, onboard the rest by interview, rehearse a procedure, and run it within limits the instrument itself enforces.</p>

<p align="center">
  <a href="https://www.npmjs.com/package/openmhp-cli"><img alt="npm" src="https://img.shields.io/npm/v/openmhp-cli?label=openmhp-cli&color=3FB59A"></a>
  <a href="https://pypi.org/project/openmhp/"><img alt="PyPI" src="https://img.shields.io/pypi/v/openmhp?label=openmhp&color=3FB59A"></a>
  <a href="LICENSE"><img alt="license" src="https://img.shields.io/badge/license-Apache%202.0-blue"></a>
  <a href="https://openmhp.com"><img alt="docs" src="https://img.shields.io/badge/docs-openmhp.com-2B8F78"></a>
</p>

<p align="center">
  <a href="https://openmhp.com/quickstart">Get started</a> ·
  <a href="https://openmhp.com/features">Features</a> ·
  <a href="https://openmhp.com/design">Design principles</a> ·
  <a href="https://openmhp.com/cookbook">Cookbook</a> ·
  <a href="https://openmhp.com/instruments">Instruments</a> ·
  <a href="https://openmhp.com/spec">Specification</a> ·
  <a href="CONTRIBUTING.md">Contributing</a>
</p>

---

**OpenMHP (Open Model Hardware Protocol)** is MCP for lab equipment. It gives any AI agent
harness one way to find a physical device among thousands, learn how to use it from the
people who own it, operate it safely, and hand it long-running work.

```bash
npx openmhp-cli setup
```

Then, in Claude Code, Codex, OpenClaw, Hermes, Claude Science, Open Science or any MCP client:

| You say | What happens |
|---|---|
| "find the instruments on my network" | scans for devices that speak MHP and lists them |
| "onboard my hotplate" | the server interviews you, writes the device package itself, validates it, reads you a safety card, adds it. Hand-operated and USB-serial instruments need no code |
| "run a 30-cycle PCR at 95/58/72 and hold at 4 °C" | finds a recipe, rehearses it in plan mode and shows every step, then runs it and reports what it read |
| "watch the incubator overnight" | a background run logs readings and alerts; in the morning, ask what happened |

Try it with nothing plugged in: `npx openmhp-cli demo` adds two simulated instruments.

## Status

Experimental preview. The runtime is tested against simulators and against fakes of each vendor client library; no physical instrument or vendor system has been exercised yet. Use it on real hardware only under supervision, with hardwired safety systems in place. §16 of [SPEC.md](SPEC.md) lists what is not yet specified.

## Why

Every instrument has its own interface, and the knowledge that makes it safe to use lives in
manuals and people's heads. OpenMHP takes the shape of MCP and Agent Skills and applies it to
hardware, so that an instrument described once can be operated by any agent, and an agent that
speaks OpenMHP can operate any instrument, without a bespoke integration for each pair.

The full story, in prose, is [Design principles](#design-principles) below and at
[openmhp.com/design](https://openmhp.com/design); the normative contract is [SPEC.md](SPEC.md).

## Features

**Protocol core**
- Five primitives — describe, signals (read), settings (write), actions (jobs), safety — plus
  **methods** as a sixth: named, versioned parameter sets for instruments that run a different
  procedure per project or compound (HPLC, GC, MS, PXRD, PCR programs), kept and validated on the
  device itself (SPEC §4.5).
- JSON-RPC 2.0 over stdio or HTTP, the same shape MCP uses, with capability negotiation on connect
  and progressive protocol-version fallback.
- Three-tier progressive disclosure of a device's descriptor (card → summary → full, plus `select`
  for named items), so a search result costs about the same whether the lab has two devices or two
  thousand.

**Safety, enforced in the driver, never by the agent**
- Six safety gates, always in the same order: state → approval → interlocks → typed value or
  params → lease → busy. A value is type-checked, bounded and rejected if non-finite or malformed
  *before* any vendor code runs, and the same check applies to a dry run.
- Approval levels (`auto` / `confirm` / `forbid`) written by the device's owner; `confirm` is
  enforced through MCP elicitation, and a model cannot set `approved: true` itself — only the host
  can, and only after a person actually confirmed that exact request.
- Fail-closed state machine: any exception mid-job, or a write whose outcome is uncertain, latches
  the device in `fault` with `outcome: unknown`; recovery needs a `safety/reset` that verifies the
  device rather than just clearing a flag.
- A per-lease **watchdog**, armed automatically whenever a session holds control: if the holder
  goes silent longer than the declared window, the device fails safe on its own. The reference
  client renews it with a heartbeat, so correct use is invisible and silence is the only way to
  trip it.
- **Emergency stop** that is always allowed, runs outside the request lock so it never waits behind
  vendor I/O, and can be sent to every device a session has touched at once.

**Human in the loop**
- Pause and resume on long-running jobs, so a person can step in without a full e-stop.
- Operator-run ("manual") instruments: an action waits in `waiting_operator` until a person
  acknowledges it — completion is never claimed before they act.
- A **safety card** that reports evidence per probe (passed / failed / not exercised) instead of a
  verdict, and says plainly that it is not a safety certification.

**Long-running work, data and events as first-class citizens**
- Jobs: an action returns immediately and runs on the device; poll it or subscribe to it, with
  states covering `waiting_operator` and an uncertain `outcome`.
- **Every device pushes** signal updates, job progress and completion, and safety events without
  being asked, over whatever transport connects it (in-process, HTTP Server-Sent Events, or
  stdio) — an agent reads `mhp_data op='updates'` instead of polling.
- Background runs get their own directory, saved files, and an `events.jsonl` of everything a
  device pushed while that run used it; a restart-safe, append-only run log keeps history across a
  bridge restart.
- **Plan mode** rehearses a whole script: every write and invoke becomes a dry run through all six
  gates, time is virtual so a 30-minute wait costs nothing to rehearse, a step budget bounds a
  runaway loop, and a strict read-only allowlist keeps the escape hatch (raw RPC) from ever
  actuating anything for real.

**Getting instruments connected**
- **Server-run onboarding**: an interview in plain language that writes the whole device package —
  DEVICE.md, descriptor.yaml, and for manual or serial instruments, a working driver — with no code
  from the person answering questions.
- No-code drivers for hand-operated ("manual") and USB/serial ASCII-command instruments.
- **Adapters** that bridge the ecosystems labs already run — SiLA 2, PyLabRobot, MADSci, OPC UA,
  ROS 2 — in a few lines each, on top of a shared `BoundDriver` scaffold.
- **Simulated twins** (`sim.py`) for every bundled and community package, so a procedure can be
  rehearsed or demoed with nothing plugged in.
- A **community registry** of contributed packages, added by `github:` target, so one contributed
  package is one every other lab doesn't have to write.

**Scale and harness ergonomics**
- A **directory** that indexes cards (not descriptors) with BM25 search, pinging live state only
  for the candidates a query actually needs.
- A tool surface that never grows: **eleven tools** whether the lab has two devices or two
  thousand, with worked `input_examples` on every one of them.
- **Recipes**: tested, parameterized scripts an agent finds and adapts instead of writing from
  scratch, runnable directly or rehearsed through plan mode first.
- Three ready-made **Agent Skills** matching the three real workflows: onboarding a device,
  adapting an existing fleet, and day-to-day operation.
- Three control surfaces over one enforced protocol: the **MCP bridge** (stdio or bearer-token,
  Origin-checked HTTP), a **CLI** for scripting and debugging, and a **Python SDK** for code that
  chains steps across devices faster or longer than an agent should reason about live.

## Design principles

The high-level thought process behind the protocol, in the order decisions actually got made:

1. **Where it came from.** Anthropic solved the equivalent problem for software with the Model
   Context Protocol, and showed how to package procedural knowledge with Agent Skills. OpenMHP is
   the same idea carried to hardware: one open, shared way for any AI agent to connect to lab and
   factory instruments the way MCP connected agents to digital tools.
2. **The agent is not the enforcement point.** Everything that keeps a run safe — limits,
   interlocks, approval, lease ownership, whether an outcome is even certain — is checked in the
   driver, on the device side of the wire, on every call including a dry run. An agent can ask for
   anything; only the driver decides what actually happens. Changing a limit is a code review, not
   something reachable at run time.
3. **The host is trusted, the model is not.** `approved: true` means a person confirmed *this exact
   request*. It is stripped from whatever the model sends and set only by the host, after MCP
   elicitation. This one rule is what makes "confirm-gated" mean something instead of being a
   suggestion the model could talk itself past.
4. **An instrument should teach an agent the way a colleague would.** A device package is written
   in the owner's own words, with the tacit knowledge that used to live in a manual or in someone's
   head — what a lid's cool-down actually feels like, what a value "usually" is, what to never do.
   It loads the way an Agent Skill does: a ~40-token card in search results, the operating summary
   once chosen, full detail only for the item about to be used. An agent's context is a resource
   the protocol protects, the same lesson MCP's own tool-search work taught about long tool lists.
5. **Fail closed, always.** An uncertain outcome is worse than a stopped one, so a failure latches
   the device rather than guessing it's fine. A watchdog protects against a controlling process
   going silent, not just against malice. E-stop always wins regardless of lease, approval or
   interlock state. Physical actions are not idempotent, so retries are the caller's job, never
   automatic.
6. **Show the plan before doing the thing.** Plan mode exists so an agent can rehearse a whole
   procedure — every gate evaluated, nothing physically moving — and hand a person something
   concrete to say yes to, rather than narrating an intention in prose.
7. **Physical work does not fit inside one request/response turn.** Jobs, leases, background runs
   and pushed events all exist because chemistry and mechanics run on their own clock. An agent
   should have results pushed to it and a run should survive a restart, not require babysitting a
   poll loop for the length of a PCR program.
8. **Methods are data, owned by the project, not baked into the instrument.** The same GC runs a
   different method per compound and per project; hard-coding one method into a driver would be
   wrong on day one. So a method is a versioned record the device validates and keeps, and the
   protocol's first move for a method-driven action is "ask which one," not "guess."
9. **Bridge existing ecosystems; don't compete with them.** SiLA 2, PyLabRobot, MADSci, OPC UA and
   ROS 2 represent years of vendor and lab investment. OpenMHP's job is to be the layer an agent
   sees, translating what already works underneath, not replacing it.
10. **The protocol is the product, not any one implementation.** A written, versioned SPEC.md,
    JSON-RPC 2.0 as an ordinary wire format, and conformance defined behaviorally — pass an
    equivalent test suite — so a second, independent implementation is possible and welcome, on
    any language or platform.

## For developers

```bash
pip install "openmhp[all]"                     # runtime; [all] adds mDNS discovery and serial
python examples/pcr_run.py                     # orchestrate a robot arm and a thermocycler
python examples/scale_demo.py                  # 2,000 devices, ~1k tokens
python tests/test_adapters.py && python tests/test_runs.py && python tests/test_safety_gates.py && python tests/test_methods.py
mhp serve pkg:openmhp/devices/thermocycler-01 --http 18921     # serve a device package on the LAN
mhp-mcp --http 18800                           # the MCP bridge over HTTP: bearer token from ~/.openmhp/http_token
```

A device is a folder:

```
devices/hotplate-01/
├── DEVICE.md          card (YAML frontmatter) + operating instructions
├── descriptor.yaml    signals, settings with limits, actions, interlocks, safety
├── driver.py          code: a Driver subclass, a BoundDriver, or an adapter
├── sim.py             optional simulated twin
├── references/        SOPs, manual excerpts
├── scripts/           tested mhp_run scripts
└── methods/           optional: saved methods per project, for actions marked methods: true (SPEC 4.5)
```

Adapters: `openmhp.adapters.sila2`, `.pylabrobot`, `.madsci`, `.opcua`, `.ros2`, and `BoundDriver`
for any Python callable. Community packages live in [`packages/`](packages/); recipes in
[`openmhp/recipes/`](openmhp/recipes/); Agent Skills in [`openmhp/skills/`](openmhp/skills/).

## Layout

```
openmhp/driver.py        Driver base class: primitives, six safety gates, jobs (pause/resume), detail tiers, resources, methods/*
openmhp/methods.py       the methods store: per-project records, versions, history, runs (SPEC 4.5 M1..M10)
openmhp/package.py       device packages: DEVICE.md frontmatter + body, descriptor.yaml, resources, sim twins
openmhp/directory.py     card index + BM25 search + live state pings; serves directory/*
openmhp/fleet.py         the lab's device list (~/.openmhp/fleet.json); github: targets; in-process hosting
openmhp/discovery.py     mDNS advertise/browse (optional zeroconf) and HTTP probe of /mhp.json
openmhp/onboarding.py    server-side interview -> writes the device package
openmhp/drivers/         no-code drivers: manual (human-operated) and serial_ascii (declared commands)
openmhp/runs.py          runs (background, run_dir, stdout), the run log, plan mode
openmhp/recipes/         tested cross-instrument procedures
openmhp/safety.py        the safety card
openmhp/registry.py      community package index
openmhp/mcp_bridge.py    mhp-mcp: eleven tools, elicitation, prompts, logging, pushed-event relay; stdio or HTTP
openmhp/transport.py     stdio and HTTP(+SSE) device transports; /mhp.json discovery
openmhp/client.py        Device / Lab client SDK
openmhp/cli.py           mhp: lab, validate, skills, serve, serve-directory, device verbs
openmhp/adapters/        BoundDriver; sila2, pylabrobot, madsci, opcua, ros2
openmhp/skills/          Agent Skills: onboard-device, adapt-fleet, operate
openmhp/devices/         bundled simulated thermocycler, arm and gas chromatograph, as packages
packages/                community packages: ika-c-mag-hs7, opentrons-flex, manual-benchtop-centrifuge
npm/                     the npx openmhp-cli launcher
```

## License

Apache 2.0. See [CONTRIBUTING.md](CONTRIBUTING.md) to add a device package or a recipe.
