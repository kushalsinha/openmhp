<!-- generated from https://openmhp.com/design by scripts/build_guide.py; edit the website, not this file -->

# Design principles

OpenMHP extends MCP for physical work: devices can run for minutes or hours, stream observations back to the agent, and enforce safety beside the instrument.

## Extend MCP with jobs, not longer tool calls

An action returns a job immediately. The instrument keeps working independently while the agent does other work, disconnects, or returns later. Progress, results, logs, and output files remain attached to the run instead of being trapped inside one request/response turn.

## Put a small server beside the instrument

Each device is served by a lightweight OpenMHP node on the bench computer already connected by USB or the vendor network. It translates MHP into the native driver, relays telemetry over stdio or HTTP/SSE, and keeps the safety path local. This provides a low-latency edge relay without pretending the agent is a real-time controller. When the bench network is closed to the outside, the node dials out to a gateway on the company network and agents reach it there, so the firewall stays as IT left it.

## Push observations so the agent can decide

Devices publish signal changes, job progress, completion, and safety events as they happen. The bridge makes recent updates available to the agent and records run-specific events and artifacts. The agent can inspect the new evidence, decide what to do next, and issue another command without continuously polling the instrument.

> **Control loop:** agent request → MHP job → local device server → instrument instrument events → SSE or stdio → bridge and run log → agent decision

## Treat each device like a Skill

A device package combines a compact device card, operating guidance, a machine-readable descriptor, and its driver. Agents first see a small summary, then load exact signals, settings, actions, limits, references, or scripts only when needed. This keeps context small while preserving the practical knowledge required to operate real hardware.

## Enforce safety where commands become motion

The model may propose an action; the device server decides whether it may run. State checks, approvals, interlocks, parameter limits, leases, watchdogs, and e-stop behavior live at the device boundary and fail closed. Safety therefore survives an agent crash, a lost connection, or a malformed request.

## Wrap the lab you already have

OpenMHP adds an agent-facing layer instead of replacing established control systems:

- **ROS 2:** topics become signals and settings; actions keep feedback and cancellation.

- **MADSci:** node metadata, actions, status, and safety controls map into the same device model.

- **OPC UA:** variables become signals or settings, and methods become actions.

- **SiLA 2:** properties and commands retain observable progress and cancellation.

- **PyLabRobot:** a machine's operations become actions under the same job model.

- **MQTT:** topics a lab already streams time-varying sensor data on become signals, each with a staleness window; command topics become settings and actions.

Adapters preserve the infrastructure's native capabilities while giving every device the same discovery, job, telemetry, and safety interface.

## In practice

- Represent long-running physical work as a durable job.

- Push telemetry and events; do not make agents babysit a polling loop.

- Keep interlocks and emergency behavior at the device edge.

- Adapt existing control systems instead of rebuilding them.

## Where to go next

[**Architecture**See how the node, bridge, jobs, and events fit together.](https://openmhp.com/architecture) [**Features**Explore the protocol from an operator's perspective.](https://openmhp.com/features) [**Specification**Read the normative protocol contract.](https://openmhp.com/spec)
