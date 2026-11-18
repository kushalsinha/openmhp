<!-- generated from https://openmhp.com/roadmap by scripts/build_guide.py; edit the website, not this file -->

# Roadmap

Where OpenMHP is going, and what it deliberately leaves out for now. Items move up this list when a partner lab needs them; tell us which ones.

## Shipped

Protocol and reference implementation: six primitives (describe, signals, settings, actions, safety, and methods for instruments that run named per-project parameter sets) with driver-enforced safety gates in a fixed order; device packages with three levels of disclosure; a live-pinging directory; adapters for OPC UA, ROS 2, SiLA 2, MADSci, PyLabRobot and MQTT; bearer tokens on the device HTTP transport; the relay (`mhp gateway`, `mhp node --join`) for lab PCs behind a firewall, with one-time pairing codes, pinned certificates and once-or-not-at-all delivery; `mhp node add` turning a bench PC into a persistent, auto-advertised host for everything wired into it; server-run onboarding with no-code manual and serial drivers; recipes and plan mode with virtual time and a read-only RPC allowlist; a per-lease watchdog and a fail-closed state machine for uncertain outcomes; background runs, data files and a restart-safe run log; every device pushing signal, job and safety events to a bridge that relays them without polling; human confirmation through MCP elicitation; pause and resume; evidence-based safety cards; a community package registry with simulated twins; the `npx -y openmhp-cli@latest` launcher; three Agent Skills. The full list, with the thinking behind it, is on [Features](https://openmhp.com/features) and [Design principles](https://openmhp.com/design).

## Next

| Item | Why | What it takes |
|---|---|---|
| **Desktop installer** | Scientists on Claude Desktop or similar apps should never open a terminal. Today `npx -y openmhp-cli@latest setup` needs Node and Python present. | A signed macOS and Windows installer that bundles a Python runtime, installs the launcher, registers the MCP server with the harnesses it finds, and updates itself. This is a packaging pipeline outside the protocol repository, with code signing and notarisation. |
| **Push packages to a node** | `mhp node add` and `mhp node --install-service` already serve every package in a folder as a persistent, auto-advertised background service. What is still manual is someone at the bench PC naming the package to add. | Let a node accept a package pushed from a scientist's laptop or the directory, so onboarding an instrument never requires touching the bench PC's filesystem by hand. |
| **Lab notebook export** | The run log and run folders already hold everything a notebook entry needs. | Render a run into a Markdown or ELN-ready record: what was asked, what was planned, what ran, every reading and refusal, who confirmed what. Connectors for common ELNs after the format settles. |
| **Instrument data formats** | Plate readers and microscopes produce vendor files. The agent needs standard tables and images, not vendor blobs. | Conventions for run files (CSV for tables, PNG or TIFF for images, JSON sidecars), and converters that emit Allotrope Simple Model for instrument output, so downstream analysis and LIMS ingestion work without custom parsing. |
| **Sandboxed runs** | The reference bridge executes `mhp_run` scripts in-process so simulated state is shared. Real labs want isolation. | Run scripts in a subprocess or container with only the MHP client available, resource limits, and the same run folder. The protocol does not change. |
| **Hosted registry** | The bundled index lists three packages. Growth needs a place to publish. | A registry at openmhp.com with search, versioning, a review step for safety cards, and `mhp_lab op="registry"` pointed at it by default. Package signing so a lab can trust what it pulls. |
| **Authentication, next steps** | The device HTTP transport and the gateway take bearer tokens today; a caller holding a token is trusted about who it is. | Mutual TLS as an option, per-client identities carried into leases and the run log, and an in-band `params.auth` for harnesses that cannot set headers. |
| **Multi-device transactions** | A plate transfer that fails halfway leaves two devices in inconsistent states. | A `transaction/` namespace: acquire leases on several devices at once, run a sequence, and define compensating actions the bridge runs on failure. |
| **Scheduling** | Overnight and multi-day experiments start at a time, not at a keystroke. | Scheduled and recurring runs in the bridge, with a calendar view in the lab status and notifications when they start, finish, or trip an alert band. |
| **Streaming signals** | Spectra and camera frames are streams, not polled values. | A `data/stream` primitive over SSE and WebSocket with backpressure, and recipe helpers that subscribe and aggregate without the agent in the loop. |
| **Fleet health** | Two thousand devices need a dashboard, not a chat. | A read-only web view over the directory, run log and safety cards: what is idle, busy, faulted, unreachable; what ran; which packages lack a safety review. |
| **More community packages** | Every package someone writes is one no one else has to. | Serial command maps for common hotplates, balances, pumps and thermocyclers; PyLabRobot-backed handlers; OPC UA templates for furnaces and chambers. Contributions with a safety card and a simulated twin are merged. |

## Principles that will not change

- Safety is enforced in the driver, on the device side of the wire, whatever the agent asks for.

- The tool surface stays constant as the lab grows: eleven tools, never one per device.

- A device is described by a package a person can read, and a scientist can produce one without writing code.

- Any agent harness that speaks MCP is a first-class host. OpenMHP is not tied to one model or product.

- Existing control layers are bridged, not replaced.

## How to influence this

Open an issue on [GitHub](https://github.com/kushalsinha/openmhp) with the instrument or workflow you are trying to run. Items that unblock a real experiment in a real lab move to the top.
