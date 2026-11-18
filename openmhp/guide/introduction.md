<!-- generated from https://openmhp.com/ by scripts/build_guide.py; edit the website, not this file -->

# Let your AI agent run the lab.

OpenMHP is an open protocol that connects AI agents to lab instruments. It is an ordinary MCP server, so any harness can speak to it — but a tool call ends the moment it returns, and physical work does not. OpenMHP holds a lease on the instrument, runs the work as a job that outlives the conversation, and streams back what the device reports until it is done.

If you know MCP, you already understand most of OpenMHP. MCP gave AI applications one standard way to reach software tools and data. OpenMHP does the same for hardware: an instrument that speaks OpenMHP can be used by any agent, and an agent that speaks OpenMHP can use any instrument, without someone writing an integration for each pair. What it adds on top is everything a request-and-response call has no way to express — a lease, a job, a live event stream, and a safety gate no model can talk its way past.

[Figure: AI agents send intent through the OpenMHP MCP server and receive results. OpenMHP sends commands to physical devices and receives telemetry, with limits, interlocks, approvals and emergency stop enforced beside the hardware. A dashed line marks the lab firewall: lab PCs dial out through it and nothing is opened inbound.]

*OpenMHP gives every agent the same small toolset, while each device keeps its existing control layer and enforces its own safety envelope. Where the lab network is closed, the bench PC dials out through the firewall to a gateway; nothing is opened inbound.*

## MCP calls a tool. OpenMHP stays with the machine.

A software tool call is over when it returns. A thirty-cycle PCR runs for two hours, a plate arm is mid-move, an incubator has to be watched overnight. OpenMHP keeps the same MCP front door and adds the three things that gap needs: exclusive control while you have it, work that outlives the call, and a device that reports instead of waiting to be asked.

MCP

**request** **response**

One call. When it returns, the agent has nothing holding the device and no way to hear what happens next.

OpenMHP

**lease** **job** **live events** **result** **release**

The work is a job with an id. The agent can close the session, come back tomorrow and ask how it went.

*The same MCP wire, extended for work that takes minutes, hours or days.*

**The lease**

One session at a time holds the right to write and invoke, renewed by a heartbeat. It is also a dead man's switch: on an instrument that declares a watchdog, going quiet for longer than the window makes the device stop itself, cancel its jobs and latch safe rather than assume all is well. Reads, job status and emergency stop are never blocked by it.

**The job**

Invoking an action returns a job id immediately, not a result. It moves through queued, running and then done, failed or cancelled, and can be paused, resumed or cancelled while it runs. A failed job reports an unknown outcome and holds the device in fault until someone verifies it, because a half-finished physical action is not a safe thing to guess about.

**The live stream**

The device pushes. Signal changes, job progress and completion, safety events, faults and requests for a human all arrive as notifications, and the bridge records them against the run as they land. An agent reads what came in and decides what to do next. Nothing in that path polls the instrument.

## Each device loads like an Agent Skill

The second idea OpenMHP borrows is from Agent Skills rather than MCP: an instrument is packaged like knowledge, not like an API. A device package is the instrument owner's knowledge, split into layers. The agent sees a tiny card while searching, opens the operating guide when it chooses the device, and loads exact specs or tested procedures only when the task needs them.

**thermocycler/**

**DEVICE.md**the owner's guide

*1***Device card**Name · location · when to use it

*2***Operating instructions**How to run it · what to watch · what never to do

**descriptor.yaml**limits · interlocks · actions

**driver.py**talks to the hardware

**references/**manuals · SOPs

**scripts/**tested procedures

**loads only what is needed**

Agent context

1

**Search the whole lab**Cards only · about 40 tokens each

always cheap

2

**Choose one device**Card + operating instructions

under 1k

3

**Prepare the exact action**Named specs, references or scripts

on demand

The driver stays beside the hardware. Its safety rules are enforced on every call, whether or not they are in the agent's context.

*Progressive disclosure keeps the context cost flat while the device package can hold everything an owner wants an agent to know.*

From request to physical action

1. 01**“Run a 30-cycle PCR”**The scientist states the outcome.

2. 02**Find**Search 2,000 lightweight device cards.

3. 03**Understand**Load this thermocycler's operating guide.

4. 04**Select**Fetch only `run_protocol` and its settings.

5. 05**Enforce**The driver checks limits, interlocks and approval.

6. 06**Run**The instrument moves; progress streams back.

**1,270 tokens**to find one device among 2,000 and load the two items used

*The agent learns more only as its confidence narrows. The last word still belongs to the device-side safety gate.*

## What you can do with it

A day with OpenMHP, for a scientist who writes no code:

- **Ask for an experiment in plain words.** "Run a 30-cycle PCR on the plate in A1 and hold it at 4 °C." The agent finds the instruments, reads what their owners wrote, picks a tested recipe, rehearses every step and shows you the plan before anything moves.

- **Let an instrument choose its own method.** A GC or HPLC keeps its methods per project; the agent asks it, runs the match, adjusts within limits, and saves what worked as the next version.

- **Add an instrument by answering questions.** "Onboard my hotplate" starts a short interview: what is it, where is it, what can be set, what must never be set, how do you stop it. The description is written for you.

- **Trust the limits, and leave it running.** Caps, interlocks and "a person confirms this" are written by the owner and enforced by the driver on every call; a watchdog stops the instrument if the controller goes silent. Overnight runs log and alert on their own, and the agent reads the record back in the morning.

For builders, the agent sees eleven tools whether the lab has two devices or two thousand, and devices load like Agent Skills, so context stays small. Details on the [Features](https://openmhp.com/features) page.

## Instruments already supported

Ready-made packages, each with a driver, a simulated twin and a setup note. Full list with per-device scores on the [instruments page](https://openmhp.com/instruments).

## Connect your instruments in an afternoon

Two commands and no network changes. On the PC wired to an instrument, `mhp node add <instrument>` fetches the device package and asks a handful of questions a person can answer: which port, which address, which project. It checks the instrument, then keeps serving it after every reboot. If the lab network is closed to the outside, a gateway on the company network is the meeting point: bench PCs dial out to it, your agent talks to it, and IT opens nothing.

Lab PC, gateway, agent

In the lab **Bench PC** The computer already wired to the HPLC, the hotplate, the sampler. `mhp node add waters-empower-hplc` Answers four questions. Instrument checked, served, survives reboots.

*lab firewall*dials out

Company network **Gateway** One per lab. Keeps the list of every instrument and who may use it. `mhp gateway serve` Bench PCs and agents both come to it. Nothing goes into the lab.

connects

Anywhere on the VPN **Your agent** Claude Code, Codex or another harness on your laptop. `"Run the QC method on sample 12"` Finds every instrument the gateway lists and operates it within its limits.

- **No inbound firewall rule.** Every connection points at the gateway.

- **No code.** One command per instrument, questions in plain words.

- **One lab, every agent.** Add an instrument once; every agent can find it.

*Setting up the bench PC is on [Lab nodes](https://openmhp.com/lab-nodes); the gateway, pairing and what IT needs to know are on [Gateway and relay](https://openmhp.com/gateway).*

## Where to start

[**Quickstart**One command, then talk to your agent. Try it with two simulated instruments.](https://openmhp.com/quickstart) [**Features**Everything OpenMHP does today, grouped by what it's for.](https://openmhp.com/features) [**Design principles**The thought process behind the protocol, and what stays fixed as it grows.](https://openmhp.com/design) [**Cookbook**Four experiments walked through end to end, every step shown.](https://openmhp.com/cookbook) [**Lab nodes and gateway**Put an instrument on the network in one command, and reach it from outside a closed lab.](https://openmhp.com/lab-nodes) [**Add an instrument**The interview, the device package, and what the agent writes for you.](https://openmhp.com/add-a-device) [**Instruments supported**What runs under OpenMHP today, and how much work each route is.](https://openmhp.com/instruments) [**Architecture**Who talks to whom, and a full worked example on the wire.](https://openmhp.com/architecture) [**Specification**The protocol, one page per section.](https://openmhp.com/spec)

## Why it matters, by role

- **If you own an instrument,** you describe it once, in your own words, and every agent uses it within the limits you set.

- **If you build agents or harnesses,** you integrate once. Every OpenMHP instrument works, and the tool list never grows.

- **If you run experiments,** you get an agent that plans before it acts, asks before anything you flagged, and can always be stopped.

## Where OpenMHP came from

Anthropic solved the equivalent problem for software when it open-sourced the Model Context Protocol, and showed how to package procedural knowledge with Agent Skills. OpenMHP carries the same idea across to hardware: one open, shared way for any AI agent to connect to lab and factory instruments the way MCP connected agents to digital tools — and a small set of design principles that follow from it, like enforcing safety in the driver rather than trusting the agent, and treating an agent's context as a resource the protocol protects on purpose. The full reasoning, and what it means for a contribution, is on the [Design principles](https://openmhp.com/design) page.

## Common questions

**Does it replace OPC UA, ROS 2, SiLA 2 or MQTT?** No. It sits on top of them. An adapter turns an OPC UA server, a ROS 2 node, a SiLA feature, a MADSci node, a PyLabRobot machine or a set of MQTT topics into an OpenMHP device in a few lines, and adds the safety envelope and the agent-facing description those layers do not carry.

**Our instruments are behind the lab firewall. Does this work?** Yes, with nothing opened. The bench PC runs `mhp node` and dials *out* over HTTPS to a gateway on the company network; your agent talks to the gateway. IT has one line to check: lab PCs and agent machines can reach the gateway's address. See [behind the lab firewall](https://openmhp.com/gateway).

**Which AI model does it need?** Any. OpenMHP is an ordinary MCP server, so the model is whatever your harness runs.

**What stops an agent from doing something dangerous?** The driver, not the agent. Limits, interlocks and approval levels are written into the device package by the owner and checked on the device side of the wire on every call. Changing a limit is a code review, not something an agent can do at run time.

**Do I have to program to add my instrument?** Usually not. The agent interviews you and writes the package. Hand-operated and USB-serial instruments need no code; instruments on the supported ecosystems need a few lines of bindings; only a vendor SDK or a binary protocol needs a short driver class.
