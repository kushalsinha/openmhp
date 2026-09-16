<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/hero-dark.svg">
  <img src="assets/hero.svg" alt="OpenMHP" width="480">
</picture>

<br/>
<br/>

**The open protocol that lets any AI agent find, understand and safely run lab instruments.**

Describe an instrument once, in plain language. Any agent harness can then find it, learn how to use it from the people who own it, rehearse a procedure, and run it — within limits the instrument itself enforces, not the agent's judgment.

<br/>

[![npm](https://img.shields.io/npm/v/openmhp-cli?label=openmhp-cli&color=3FB59A)](https://www.npmjs.com/package/openmhp-cli)
[![PyPI](https://img.shields.io/pypi/v/openmhp?label=openmhp&color=3FB59A)](https://pypi.org/project/openmhp/)
[![license](https://img.shields.io/badge/license-Apache%202.0-1f1f1f.svg)](LICENSE)
[![docs](https://img.shields.io/badge/docs-openmhp.com-2B8F78)](https://openmhp.com)

[Quickstart](https://openmhp.com/quickstart) · [Features](https://openmhp.com/features) · [Design principles](https://openmhp.com/design) · [Cookbook](https://openmhp.com/cookbook) · [Instruments](https://openmhp.com/instruments) · [Specification](https://openmhp.com/spec) · [Contributing](CONTRIBUTING.md)

</div>

<br/>

## What it is

OpenMHP (Open Model Hardware Protocol) is MCP for lab and factory hardware. MCP gave AI applications one standard way to reach software tools; OpenMHP does the same for physical instruments. An instrument described once can be operated by any agent harness, and an agent that speaks OpenMHP can operate any instrument, without a bespoke integration for every pair.

It is built for the part of running an instrument that is real work but not the science: finding what's on the bench, learning its limits and quirks, checking interlocks, rehearsing a procedure before committing reagent or time to it, and watching a long run without babysitting it.

- **Safety lives in the driver, not the agent.** Limits, interlocks and approval levels are written by the instrument's owner and checked on the device side of the wire on every call — an agent cannot talk its way past them.
- **An instrument teaches like a colleague would.** Descriptions are written in plain language, load progressively like an Agent Skill, and cost an agent's context about the same whether the lab has two devices or two thousand.
- **Nothing moves without a plan.** Plan mode rehearses a whole procedure through every safety gate first, so a person sees exactly what will happen before anything heats, moves, or spends a sample.
- **Long runs don't need babysitting.** Jobs, a per-lease watchdog, and pushed events mean a thirty-cycle PCR program or an overnight monitor reports back on its own.
- **Bridges what you already run.** OPC UA, ROS 2, SiLA 2, MADSci, PyLabRobot and MQTT devices join in a few lines; nothing is replaced underneath.

## Status

Experimental preview. The runtime is tested against simulators and against fakes of each vendor client library — no physical instrument or vendor system has been exercised yet. Use it on real hardware only under supervision, with hardwired safety systems in place. [§16 of SPEC.md](SPEC.md) lists what is not yet specified.

## Install

```bash
npx openmhp-cli setup
```

This installs the runtime and registers the MCP server with whatever agent harness it finds. Try it with nothing plugged in first:

```bash
npx openmhp-cli demo      # adds two simulated instruments: a thermocycler and a plate arm
```

Python only, no npm:

```bash
pip install "openmhp[all]"      # [all] adds mDNS discovery and serial support
```

## First task

Open your agent harness — Claude Code, Codex, OpenClaw, Hermes, Claude Science, Open Science, or any MCP client — and just talk to it:

```text
Onboard my hotplate, then run a reflux at 80 °C for two minutes, stirring at 400 rpm.
```

The agent interviews you about the instrument (what it is, where it sits, what can be set, how to stop it), writes and validates the device package itself, reads you a safety card, then rehearses the procedure and shows you the plan before running anything. Nothing about this needs code from you.

## What you can do

| You say | What happens |
|---|---|
| "find the instruments on my network" | Scans for devices that speak MHP and lists them, with what each one is for. |
| "onboard my hotplate" | The server interviews you, writes the device package, validates it, reads you a safety card, and adds it. Hand-operated and USB-serial instruments need no code at all. |
| "run a 30-cycle PCR at 95/58/72 and hold at 4 °C" | Finds a matching recipe, rehearses it in plan mode with every step shown, then runs it and reports what it actually read. |
| "which method should I use for ethanol on the GC?" | Asks the instrument for the methods filed under your project; one match runs, several get put to you, none gets you asked for parameters to save. |
| "watch the incubator overnight" | A background run logs readings as the instrument pushes them, and raises alerts; in the morning, ask what happened. |
| "stop everything, now" | Emergency-stops every device the session has touched, at once, regardless of what else is going on. |

## How it works

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

- **Six safety gates, one fixed order**, on every write and invoke: state → approval → interlocks → typed value or params → lease → busy. Whatever the agent asks for, only the driver decides what actually happens.
- **The host is trusted, the model is not.** `approved: true` means a person confirmed *this exact request*, set only by the host after real MCP elicitation — never something the model can assert about itself.
- **Fail closed.** An uncertain write outcome, or a controlling process going silent past a declared watchdog window, latches the device safe rather than guessing it's fine. Emergency stop always wins.
- **Every device pushes.** Signal updates, job progress and completion, and safety events arrive without being asked, over whatever transport connects it — an agent reads them instead of polling.

The full reasoning behind these choices is in [Design principles](https://openmhp.com/design); the normative contract is [SPEC.md](SPEC.md).

## Features

Six primitives (describe, signals, settings, actions, safety, and **methods** for instruments that run a named procedure per project or compound), device packages shaped like Agent Skills, plan mode with virtual time, a per-lease watchdog, pause and resume, evidence-based safety cards, server-run onboarding, simulated twins, adapters for OPC UA/ROS 2/SiLA 2/MADSci/PyLabRobot/MQTT, a community package registry, and a tool surface that stays at eleven calls whether the lab has two devices or two thousand.

The full list, grouped by what each piece is for, is at **[openmhp.com/features](https://openmhp.com/features)**.

## Documentation

| Topic | Guides |
|---|---|
| First use | [Quickstart](https://openmhp.com/quickstart), [Features](https://openmhp.com/features), [Design principles](https://openmhp.com/design) |
| Connect an instrument | [Add an instrument](https://openmhp.com/add-a-device), [Adapters](https://openmhp.com/adapters), [Instruments supported](https://openmhp.com/instruments) |
| Run something | [Recipes](https://openmhp.com/recipes), [Cookbook](https://openmhp.com/cookbook) |
| Reference | [Specification](https://openmhp.com/spec), one page per section |
| Project | [Roadmap](https://openmhp.com/roadmap) — what's shipped, what's next, what stays out of scope |

## Repository

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
openmhp/adapters/        BoundDriver; sila2, pylabrobot, madsci, opcua, ros2, mqtt
openmhp/skills/          Agent Skills: onboard-device, adapt-fleet, operate
openmhp/devices/         bundled simulated thermocycler, arm and gas chromatograph, as packages
packages/                community packages: ika-c-mag-hs7, opentrons-flex, manual-benchtop-centrifuge
npm/                     the npx openmhp-cli launcher
```

A device package itself is a folder:

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

```bash
git clone https://github.com/kushalsinha/openmhp && cd openmhp && pip install -e ".[all]"
python examples/pcr_run.py                     # orchestrate a robot arm and a thermocycler
python examples/scale_demo.py                  # 2,000 devices, ~1k tokens
python tests/test_adapters.py && python tests/test_runs.py && python tests/test_safety_gates.py && python tests/test_methods.py
mhp serve pkg:openmhp/devices/thermocycler-01 --http 18921     # serve a device package on the LAN
mhp node ~/instruments --http 18900                            # every package under a folder, one process, auto-advertised
mhp-mcp --http 18800                           # the MCP bridge over HTTP: bearer token from ~/.openmhp/http_token
```

[CONTRIBUTING.md](CONTRIBUTING.md) has the checks a pull request needs and how to add a device package, an adapter, or a recipe.

## Community and support

Bugs and feature requests: [GitHub Issues](https://github.com/kushalsinha/openmhp/issues) — a good report includes the device package or script that reproduces it. Questions about using OpenMHP in your lab or connecting a specific instrument are welcome there too.

This is a pre-1.0, experimental protocol: expect breaking changes between minor versions until it settles, tracked in [SPEC.md](SPEC.md) and the [roadmap](https://openmhp.com/roadmap).

## License

Apache License 2.0. See [LICENSE](LICENSE).

OpenMHP is an independent, community-driven project. It is not affiliated with, endorsed by, or sponsored by Anthropic, the OPC Foundation, Open Robotics, the SiLA Consortium, MADSci, PyLabRobot, or any instrument vendor. Names are used only to describe compatibility.
