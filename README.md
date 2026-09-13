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
  <a href="https://openmhp.com">Documentation</a> ·
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
hardware:

- **Five primitives.** Describe, signals (read), settings (write), actions (jobs), safety. Plus methods on every device: the named, versioned parameter sets an HPLC, GC, MS, PXRD or thermocycler runs, kept on the instrument per project and compound, validated by the device when saved, and stamped on every job. The agent asks the instrument which method to run; results are pushed back so it can adapt the next run.
- **A device package per instrument**, shaped like a skill: a card, operating instructions, and detail loaded only when asked. Two thousand devices cost the agent the same handful of tokens as two.
- **Safety enforced in the driver.** Limits, interlocks and "ask a person first" are checked on the device side of the wire, whatever the agent asks for. E-stop is always allowed.
- **Bridge, don't replace.** SiLA 2, PyLabRobot, MADSci, OPC UA and ROS 2 devices join through adapters in a few lines.
- **Recipes and plan mode.** Tested procedures the agent adapts, rehearsed through every gate before anything moves.

The full story is at [openmhp.com](https://openmhp.com); the protocol is in [SPEC.md](SPEC.md).

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
