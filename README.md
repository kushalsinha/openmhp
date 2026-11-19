<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/kushalsinha/openmhp/main/assets/hero-dark.svg">
  <img src="https://raw.githubusercontent.com/kushalsinha/openmhp/main/assets/hero.svg" alt="OpenMHP" width="480">
</picture>

### Give AI agents a safe, shared interface to physical devices

OpenMHP is an open protocol for discovering, understanding, and operating lab instruments,
robots, and industrial equipment. MCP connects an agent to a software tool for a request and
response. OpenMHP extends that model for physical work that may run for minutes, hours, or days.

[![npm](https://img.shields.io/npm/v/openmhp-cli?label=openmhp-cli&color=3FB59A)](https://www.npmjs.com/package/openmhp-cli)
[![PyPI](https://img.shields.io/pypi/v/openmhp?label=openmhp&color=3FB59A)](https://pypi.org/project/openmhp/)
[![license](https://img.shields.io/badge/license-Apache%202.0-1f1f1f.svg)](https://github.com/kushalsinha/openmhp/blob/main/LICENSE)
[![docs](https://img.shields.io/badge/docs-openmhp.com-2B8F78)](https://openmhp.com)

[Quickstart](https://openmhp.com/quickstart) · [Set up a lab](https://github.com/kushalsinha/openmhp#set-up-a-lab-step-by-step) · [Experiment flow](https://openmhp.com/experiment-flow) · [Design](https://openmhp.com/design) · [Architecture](https://openmhp.com/architecture) · [Roadmap](https://openmhp.com/roadmap) · [Specification](https://github.com/kushalsinha/openmhp/blob/main/SPEC.md) · [Contributing](https://github.com/kushalsinha/openmhp/blob/main/CONTRIBUTING.md)

</div>

> **MCP calls a tool. OpenMHP stays with the machine.**
>
> An OpenMHP operation acquires a lease on the device, starts a durable job, and listens for
> telemetry, progress, results, and safety events until the work is complete. The agent can
> leave and return without losing the state of the physical process.

```text
MCP:      request ──────────────────────────────────────────────► response
OpenMHP:  lease ─► job ─► live telemetry and events ─► result ─► release
```

![AI agents connect through MCP and OpenMHP to physical devices such as lab instruments, robots and existing control stacks (OPC UA, ROS 2, SiLA 2, MADSci, PyLabRobot, MQTT), with safety enforced at the device and live telemetry flowing back. A dashed line marks the lab firewall: lab PCs dial out through it, nothing is opened inbound.](https://raw.githubusercontent.com/kushalsinha/openmhp/main/assets/openmhp-overview.svg)

## Why OpenMHP?

Connecting an agent to a centrifuge, robot arm, microscope, or PLC is not an API call. The work
lasts hours, the instrument talks back while it runs, the know-how lives in manuals and
operators, a bad request can waste a sample, and every vendor is different. OpenMHP gives these
devices one agent-facing layer without replacing the control systems underneath:

- **Jobs for long-running work:** progress, results, and files survive the agent leaving.
- **Pushed observations:** signals, progress, and safety events come to the agent; no polling.
- **Progressive context:** a small card first, full instructions only for the device chosen.
- **Safety at the edge:** the server beside the instrument checks limits, interlocks, approvals,
  leases, and state before any vendor code runs.
- **Wrap what the lab has:** OPC UA, ROS 2, SiLA 2, MADSci, PyLabRobot, and MQTT stay in place.

An agent may propose an action; the device server decides whether it runs. OpenMHP complements
hardwired e-stops, PLC safety logic, and lab procedures; it does not replace them. More in the
[design principles](https://openmhp.com/design).

## Try it in five minutes

No hardware needed. You need Python 3.10+ and an agent such as Claude Code or Codex. Install one of two
ways; both give the same result.

**With pip** (Python only):

```bash
pip install -U "openmhp[all]"
```

```bash
mhp skills install
```

If your shell then says `mhp: command not found`, pip installed into a different Python than the one on
your PATH. Install with `python3 -m pip install -U "openmhp[all]"` instead; with pyenv, run `pyenv rehash`
afterwards. If pip refuses with `externally-managed-environment` (Homebrew or system Python), use
[pipx](https://pipx.pypa.io): `pipx install "openmhp[all]"`.

Register the MCP server with your agent. For Claude Code:

```bash
claude mcp add --scope user openmhp -- mhp-mcp
```

Any other harness takes `{"mcpServers": {"openmhp": {"command": "mhp-mcp"}}}`. Then add two simulated
instruments, a thermocycler and a plate-handling arm:

```bash
mhp lab demo
```

**With npx** (needs Node.js 18+ as well): one command installs everything and registers the MCP server with
Claude Code and Codex.

```bash
npx -y openmhp-cli@latest setup
```

```bash
npx -y openmhp-cli@latest demo
```

**Then restart your agent and ask:**

```text
Find a thermocycler, show me its operating instructions, and rehearse a
3-cycle PCR at 95/58/72 °C before running it.
```

Ask for a 200 °C setpoint too: the driver refuses it and returns the allowed range. To check the install
at any time:

```bash
mhp status
```

(With npx: `npx -y openmhp-cli@latest mhp status`.) It shows each part of this machine's setup, its state, and
the exact command for anything that needs doing.

## What you can ask for

| You ask | OpenMHP does |
|---|---|
| “Find the instruments on my network.” | Scans mDNS and known hosts for OpenMHP devices and returns compact device cards. |
| “Onboard my hotplate.” | Interviews the owner, writes and validates a device package, and produces a safety card for review. |
| “Run a 30-cycle PCR and hold at 4 °C.” | Finds a compatible device or recipe, rehearses the procedure, runs it as a job, and reports measured results. |
| “Watch the incubator overnight.” | Runs a background monitor and stores readings and alerts with the run. |
| “Which GC method should I use for ethanol?” | Searches versioned methods associated with the device and project. |
| “Stop everything now.” | Requests e-stop for every device touched by the session. |
| “Get the lab to find GC conditions that separate ethanol from isopropanol, using my retention model and BO skill.” | Hands your request, model and optimizer to the lab gateway, relays its questions, reads you its plan, and once you approve, the gateway runs the closed loop and the results come home. |

## How it works

1. **Device package:** a card, operating instructions, a machine-readable descriptor,
   references, scripts, and a driver or adapter.
2. **Device server or lab node:** runs beside the instrument, translates calls into the native
   control API, publishes events, and enforces the device boundary.
3. **MCP bridge:** gives an agent one fixed set of tools whether the lab has two devices or two
   thousand.
4. **Gateway** (optional): for lab networks nothing outside may enter. Bench PCs dial out to it.

Adapters map OPC UA, ROS 2, SiLA 2, MADSci, PyLabRobot, and MQTT onto the same job, lease,
telemetry, and safety contract ([adapter guide](https://openmhp.com/adapters)). The
[architecture guide](https://openmhp.com/architecture) describes the components, and
[SPEC.md](https://github.com/kushalsinha/openmhp/blob/main/SPEC.md) is the normative protocol.

### Device packages

A device package works like an [Agent Skill](https://agentskills.io): the agent loads more
detail only as the task narrows, from a card while searching, to operating instructions once it
picks a device, to exact signals, actions, and tested scripts when it acts.

![A device package loads progressively: a compact card during search, operating instructions after selection, and exact specifications or procedures on demand](https://raw.githubusercontent.com/kushalsinha/openmhp/main/assets/device-as-agent-skill.png)

In the 2,000-device scale demo, finding five candidates, opening one, and loading what it needs
takes about 1,270 tokens instead of 1.22 million. The model's context helps it reason; it is not
the safety boundary. The driver checks every call, and only the device's owner can change a
package's limits.

## Supported devices

[`supported-devices`](https://github.com/kushalsinha/openmhp/tree/main/supported-devices) holds 81 ready-made packages, each with a driver, a
simulated twin, operating instructions, a setup note, and a self-assessed score against the
device-level criteria of Gottstein et al.'s autonomous-ready procurement profile. Full table:
[openmhp.com/instruments](https://openmhp.com/instruments).

| Field | Packages | Instruments |
|---|---|---|
| Pharma, small molecule | 16 | HPLC/UPLC under Empower, OpenLab CDS and Chromeleon; EasyMax/OptiMax reactor; Karl Fischer titrator; 708-DS dissolution; Rotavapor R-300; Crystal16; Vapourtec R-Series; DSC/TGA under TRIOS; Bruker NMR (ICON-NMR); D8 PXRD; Cary UV-Vis/FTIR; LyoStar freeze dryer; Mettler Toledo and Sartorius balances |
| Pharma, biologics | 14 | Biostat bioreactor; ÄKTA avant; CLARIOstar/PHERAstar, SpectraMax and Spark plate readers; Hamilton STAR; Vi-CELL BLU; Octet BLI; Zetasizer DLS; Maurice CE; QuantStudio qPCR; Cytek Aurora cytometer; Innova shaker; Heracell CO2 incubator; Sigma centrifuge; BINDER stability chamber |
| Materials, synthesis and processing | 8 | Eurotherm and Nabertherm furnaces; MBRAUN glovebox; Quantos powder dosing; Laurell and Ossila spin coaters; Retsch planetary mill; AJA/Lesker sputter tools |
| Materials, characterization | 9 | Rigaku SmartLab and Panalytical Empyrean XRD; Phenom, TESCAN and ZEISS SEM; Instron under Bluehill; Anton Paar rheometer; Quantum Design PPMS; Dektak profilometer |
| Energy storage | 3 | Neware and Arbin battery cyclers; Gamry potentiostat (EIS) |
| Chemistry | 13 | IKA C-MAG and EUROSTAR; JULABO circulators; BioLogic SP-300 and PalmSens potentiostats; Ocean Insight and Wasatch/Blaze spectrometers; SRI 8610C GC; Orbitrap (IAPI); LC-MS worklists for MassLynx, SCIEX OS, MassHunter, Xcalibur; Elveflow OB1 and MUX; FloPro sampler |
| Biology | 7 | Opentrons Flex and OT-2; Micro-Manager microscopes; New Era and Tecan Cavro syringe pumps; Atlas Scientific EZO sensors; benchtop centrifuge (operator-run) |
| Physics | 6 | Keithley 2400 SMU; Lake Shore 33x/350; Pfeiffer TPG gauges; SRS SR830 lock-in; SRS RGA; Thorlabs PM100D |
| Engineering | 5 | Alicat flow controllers; LabJack T-series; NI-DAQmx; Rigol DP8xx supply; Rigol DS1000Z scope |

## Set up a lab, step by step

A lab uses up to three kinds of machine. Trying OpenMHP needs only the first.

| Machine | Who sets it up | What runs there |
|---|---|---|
| **Agent machine**: a scientist's laptop or workstation, where Claude Code, Codex or another agent runs | each scientist | the MCP server and the Agent Skills |
| **Instrument PC**: the computer wired to an instrument; no agent on it | whoever looks after the instrument | `mhp node`, serving that PC's instruments in the background |
| **Lab gateway**: an always-on machine on the company network | the lab's operator | the relay, pairing, and experiments run for scientists |

You need the gateway when the lab network is closed to the outside (instrument PCs dial out to it; nothing
is opened inbound), or when scientists hand whole experiments to the lab. On an open lab network, agent
machines find instrument PCs directly.

Two rules avoid most surprises: start npx as `npx -y openmhp-cli@latest`, and pip as `pip install -U`.
Plain `npx openmhp-cli` reuses whatever version npx cached the first time, and plain `pip install` keeps
whatever version is already installed. Installed with npx, run each `mhp ...` command below as
`npx -y openmhp-cli@latest mhp ...`: the launcher keeps its own copy and does not put `mhp` on your PATH.

### 1. Lab gateway (the operator, once)

Any always-on Linux, macOS or Windows machine on the company network that lab PCs and agent machines can
reach.

1. Install OpenMHP:
   ```bash
   pip install -U openmhp
   ```
2. Make this machine the gateway. It asks for the address others will use and a port (take 8443), and
   makes a certificate:
   ```bash
   mhp gateway init
   ```
3. Run it now and after every reboot:
   ```bash
   mhp gateway serve --install-service
   ```
4. Only if scientists will run experiments through the lab: give each scientist a folder reached over SSH.
   Run this, then the one `sudo` line it prints:
   ```bash
   mhp gateway ssh
   ```
   For one Linux user per scientist instead of one shared account, run `mhp gateway ssh users`; then
   `pair-agent` below runs with `sudo`, because it creates each scientist's user.
   Also install the agent harness (for example Claude Code) on the gateway and sign it in once with the
   lab's account; the gateway starts a session of it for each run.
5. Check everything:
   ```bash
   mhp gateway check
   ```

Then pair each machine. Every code works once.

- **For each instrument PC**, print a code (valid 15 minutes) and the line to paste there:
  ```bash
  mhp gateway pair
  ```
- **For each scientist**, print a code (valid 1 hour) and send it to them in chat. Naming them sets their
  folder on the gateway, so they type no name:
  ```bash
  mhp gateway pair-agent alice
  ```

After updating OpenMHP on the gateway (`pip install -U openmhp`), restart it:

```bash
mhp gateway restart
```

Guide: [Gateway and relay](https://openmhp.com/gateway).

### 2. Instrument PC (once per PC)

No agent is needed on it. Every ready-made package ships inside OpenMHP, so this needs no web or git access.

1. Install OpenMHP:
   ```bash
   pip install -U "openmhp[node]"
   ```
2. List the ready-made packages:
   ```bash
   mhp node add
   ```
3. Add the instrument you are standing next to:
   ```bash
   mhp node add waters-empower-hplc
   ```
   It asks only what a person knows and checks the answers against the instrument. If the lab has a
   gateway, paste the line from `mhp gateway pair` when it asks. Its last question installs the background
   service, so the instrument stays served after a reboot.
4. Check it:
   ```bash
   mhp status
   ```

With Node instead of pip: `npx -y openmhp-cli@latest node add waters-empower-hplc`. For an instrument not on
the list, tell your agent *“Onboard my IKA hotplate. I have the manual.”* Guides:
[Add an instrument](https://openmhp.com/add-a-device), [Lab nodes](https://openmhp.com/lab-nodes).

### 3. Scientist's machine (once per scientist)

1. Install OpenMHP as in [Try it in five minutes](#try-it-in-five-minutes) (pip, `mhp skills install` and
   the MCP server; or `npx -y openmhp-cli@latest setup`).
2. Join the lab gateway with the code the operator sent. Use the gateway's address with its port, as
   `mhp gateway status` prints it:
   ```bash
   mhp agent --join https://gw.office:8443 <code>
   ```
   Installed with npx:
   ```bash
   npx -y openmhp-cli@latest join https://gw.office:8443 <code>
   ```
   It shows the gateway's certificate fingerprint. **Stop if it differs from what the operator's
   `pair-agent` printed.** If the operator ran `pair-agent` without a name, add `--name alice`: the name
   becomes your folder on the gateway. Joining also installs the `openmhp-lab-gateway` skill, and sets up
   `ssh mhp-gateway` if the gateway offers SSH. There are no keys to paste.
3. Check the connection. `gateway link` should say `connected`:
   ```bash
   mhp status
   ```
4. Restart your agent. It now reaches every instrument behind the gateway. Ask it in plain English, for
   example *“Find the GC on the lab gateway”*, or *“Ask the lab to find GC conditions that separate ethanol
   from isopropanol, using my retention model.”*
5. Optional: hear about your runs (questions, plans to approve, results) even when no agent is open:
   ```bash
   mhp agent watch --install-service
   ```

Your agent drives the gateway for you with the skill. To do it by hand, these are the commands, in order:

1. Open a run. It answers with the run's ID:
   ```bash
   ssh mhp-gateway mhp-gw open
   ```
2. Hand over your skills, scripts and data:
   ```bash
   rsync -a ./my-run/ mhp-gateway:runs/<run id>/in/
   ```
3. Say what you need in plain English; a planner starts:
   ```bash
   ssh mhp-gateway mhp-gw request <run id> < request.md
   ```
4. Wait for its questions and its plan:
   ```bash
   ssh mhp-gateway mhp-gw wait <run id>
   ```
5. Read the plan:
   ```bash
   ssh mhp-gateway mhp-gw show <run id>
   ```
6. Approve exactly that plan, using the digest `show` printed:
   ```bash
   ssh mhp-gateway mhp-gw approve <run id> --charter-digest <digest>
   ```
7. Bring the results home when it ends:
   ```bash
   rsync -a mhp-gateway:runs/<run id>/out/ ./results/
   ```
8. After checking them, let the gateway delete its copy:
   ```bash
   ssh mhp-gateway mhp-gw ack <run id>
   ```

Every answer says the run's state, who it is waiting on, and the exact commands that make sense next:
`answer` a question, `message` the agent, `stop`, or `resume` after a gateway restart. To see your runs:

```bash
ssh mhp-gateway mhp-gw list
```

The story behind it: [Experiment flow](https://openmhp.com/experiment-flow).

### Updating

On an agent machine:

```bash
pip install -U "openmhp[all]" && mhp skills install
```

Installed with npx:

```bash
npx -y openmhp-cli@latest update
```

Then restart the agent. Instrument PCs never update themselves; see
[Lab nodes](https://openmhp.com/lab-nodes#updating). The gateway: `pip install -U openmhp`, then
`mhp gateway restart`.

### No web access?

The whole user guide ships inside the package, for machines (and agents) with no web or git access:

```bash
mhp guide
```

```bash
mhp guide troubleshooting
```

`mhp guide search <words>` finds a command. `mhp --version` says which OpenMHP a machine has;
`mhp gateway --version`, `mhp node --version` and `mhp agent --version` also say what the running gateway,
the instrument PC's service, or the gateway it joined runs.

## Instruments behind the lab firewall

The instrument PC connects **outward** over HTTPS to a gateway on the company network; agents talk to
the gateway. No port is opened, and working from home over the VPN is the same as at your desk.

![Bench PCs on the lab network dial out through the firewall to one gateway on the company network; agent machines in the office or on the VPN reach the same gateway with an agent token. Every arrow points at the gateway, none enters the lab.](https://raw.githubusercontent.com/kushalsinha/openmhp/main/assets/openmhp-gateway.svg)

![One call through the relay: the lab PC holds a long-poll open on the gateway; the agent posts its request with its token; the gateway queues it under the agent's name and hands it to the open poll once; the driver runs it on the bench with every limit enforced; the reply comes back the same way. Offline means 503 at once, no answer means 504, and nothing is re-sent.](https://raw.githubusercontent.com/kushalsinha/openmhp/main/assets/openmhp-relay-flow.svg)

A request reaches the lab PC once or not at all, and the gateway is the approval boundary. More:
[Gateway and relay](https://openmhp.com/gateway).

## Experiments on the lab gateway

A scientist asks for an experiment in plain English, from their own agent, and hands over their own
models, optimizer and skills; the gateway plans it with them and, once they approve, runs the closed
loop on the lab's instruments.

![An experiment in six steps across three lanes, Alice and her agent, the lab gateway and the chromatograph: ask, plan with a dry run, propose a charter and data preview, approve, the loop (start an injection, the finished job wakes the session, fit her model, ask her BO for the next condition), and results home, checked and acknowledged.](https://raw.githubusercontent.com/kushalsinha/openmhp/main/assets/openmhp-experiment-flow.svg)

The story, what it makes possible and how to set it up: [Experiment flow](https://openmhp.com/experiment-flow).
[`examples/gateway_closed_loop/`](https://github.com/kushalsinha/openmhp/tree/main/examples/gateway_closed_loop) runs it on one machine against a simulated chromatograph.

## Contributing

Contributions that make the protocol clearer, more interoperable, or better tested are welcome,
as are packages for instruments others also own. Open an issue before a substantial change.
[CONTRIBUTING.md](https://github.com/kushalsinha/openmhp/blob/main/CONTRIBUTING.md) has the development setup, the repository guide, and
pull-request expectations; the [roadmap](https://openmhp.com/roadmap) lists open work.

## Project status

OpenMHP is a pre-1.0 experimental protocol; expect breaking changes between minor versions.
Before real operation, have the instrument owner review `DEVICE.md`, verify limits and
interlocks against the manual, prove out-of-range requests are refused, test e-stop and
loss-of-contact behavior, and keep the manufacturer's safety systems in place. Supervise real
hardware deployments.

## License

Apache License 2.0. See [LICENSE](https://github.com/kushalsinha/openmhp/blob/main/LICENSE).

OpenMHP is an independent, community-driven project. It is not affiliated with, endorsed by,
or sponsored by Anthropic, the OPC Foundation, Open Robotics, the SiLA Consortium, MADSci,
PyLabRobot, or any instrument vendor. Names are used only to describe compatibility.
