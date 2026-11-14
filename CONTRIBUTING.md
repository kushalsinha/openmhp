# Contributing to OpenMHP

OpenMHP is a protocol and reference architecture for connecting AI agents to physical devices.
Contributions should help define that protocol, improve interoperability, strengthen the
reference implementation, or make independent implementations easier to build and verify.

Lab-specific device packages, SOPs, and recipes normally belong in the lab's own repository.
They often contain local topology, operating limits, procedures, or vendor material that is not
appropriate for the protocol repository. The packages and recipes in this repository are
reference examples and test fixtures.

## Where contributions help

- **Protocol and architecture:** clarify lifecycle, job, lease, event, discovery, descriptor,
  method, transport, error, and safety semantics in `SPEC.md`.
- **Roadmap:** implement or refine work listed on the
  [OpenMHP roadmap](https://openmhp.com/roadmap).
- **Interoperability:** improve the bridges to ROS 2, OPC UA, SiLA 2, MADSci, PyLabRobot,
  MQTT, and other established lab-automation systems.
- **Conformance:** add behavioral tests that independent servers and clients can use to agree
  on protocol behavior.
- **Reference implementation:** improve the Python client, server, MCP bridge, lab node,
  discovery, jobs, events, safety gates, methods, or developer tooling.
- **Documentation and examples:** explain how to build a compatible OpenMHP server, expose a
  lab through the reference architecture, or operate it from an agent.
- **Security and safety review:** identify concrete boundary failures and add regression tests
  for them.

## Before writing code

For a substantial change, open a GitHub issue first. Explain:

1. the protocol or interoperability problem;
2. the systems and implementations affected;
3. the behavior you propose; and
4. how another implementation could verify that behavior.

This keeps protocol decisions visible and prevents the reference implementation from becoming
the specification by accident. Small documentation corrections and focused bug fixes can go
directly to a pull request.

## Development setup

```bash
git clone https://github.com/kushalsinha/openmhp.git
cd openmhp
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[all]"
```

Run the test suite:

```bash
python tests/test_adapters.py
python tests/test_runs.py
python tests/test_safety_gates.py
python tests/test_inclusion.py
python tests/test_methods.py
```

## Repository guide

| Path | Purpose |
|---|---|
| `openmhp/driver.py` | Driver base class, state machine, jobs, safety gates, and notifications |
| `openmhp/package.py` | Device-package loading and progressive description tiers |
| `openmhp/mcp_bridge.py` | Fixed MCP tool surface over a lab or directory |
| `openmhp/client.py` | Python client and multi-device `Lab` API |
| `openmhp/runs.py` | Plans, background runs, logs, and run artifacts |
| `openmhp/methods.py` | Versioned instrument methods and project history |
| `openmhp/adapters/` | OPC UA, ROS 2, SiLA 2, MADSci, PyLabRobot, MQTT, and callable bindings |
| `openmhp/drivers/` | Declarative drivers with no package code: `serial_ascii`, `scpi_visa`, `modbus`, and `manual` for operator-run instruments |
| `openmhp/rubric.py` | `mhp rubric`: scores a package against the device-level autonomous-ready procurement criteria |
| `scripts/build_registry.py` | Refreshes `openmhp/registry.json` and the supported-devices table (classes, twins, rubric scores) |
| `openmhp/devices/` | Bundled reference devices and simulated twins |
| `openmhp/recipes/` | Reusable multi-step procedures |
| `supported-devices/` | Ready-made device packages for specific instruments, each with a simulated twin |
| `openmhp/gateway.py` | `mhp gateway`: the relay agents reach when lab PCs sit behind a firewall |
| `openmhp/relay.py` | Node side of the relay: `mhp node --join` dials out and serves through the gateway |
| `openmhp/supervisor.py` | Gateway runs: the planner, the run's session, and the scientist's questions and approvals |
| `openmhp/gw_shell.py` | `mhp-gw`: the verbs a scientist's agent sends to the gateway over SSH |
| `openmhp/node_add.py` | `mhp node add <package>`: puts a ready-made device package on the instrument PC |
| `openmhp/node_setup.py` | `mhp node setup`: the questions (from `config.schema.json`), `config.json`, the driver's probe, gateway pairing, the service |
| `tests/` | Simulator and fake-client coverage, plus relay and gateway end-to-end tests |

## Pull-request expectations

- State the protocol, architecture, interoperability, or correctness problem being solved.
- Update `SPEC.md` when externally observable behavior changes.
- Add meaningful tests for behavior involving safety, state, concurrency, jobs, leases,
  events, transports, or adapters.
- Keep the specification, implementation, examples, and documentation consistent.
- Preserve the fixed, device-independent MCP tool surface.
- Fail closed when hardware state or command outcome is uncertain.
- Document the external system and versions used for an adapter change. Tests should use
  injected fakes when real hardware is not available, and clearly say what was not exercised.
- A device package for `supported-devices/` must pass `mhp inclusion <folder>` in both tiers.
  Run it before opening the PR; `tests/test_inclusion.py` runs it over every shipped package.
- Keep commits focused and describe validation in the pull request.

## Building your own lab integration

You do not need to contribute your device packages or recipes upstream to use OpenMHP. Follow
the [architecture guide](https://openmhp.com/architecture) and
[add-an-instrument guide](https://openmhp.com/add-a-device) to build and deploy them in your own
environment. The [adapter guide](https://openmhp.com/adapters) shows how existing automation
stacks map into OpenMHP.

If that work exposes a missing protocol concept, ambiguous behavior, or reusable adapter
improvement, open an issue with the smallest general form of the problem. That is the part that
belongs in this project.

## Releasing

For maintainers. `openmhp` (PyPI) and `openmhp-cli` (npm) are published by
`.github/workflows/release.yml` when a version tag is pushed. Nothing else publishes.

1. A PR bumps the version in `pyproject.toml`, `openmhp/__init__.py` and `npm/package.json` to the
   same number, and merges to `main`.
2. Tag the merge commit: `git tag -a v0.11.0 -m "openmhp 0.11.0" && git push origin v0.11.0`.
3. The workflow checks the tag is on `main` and matches all three versions, then publishes PyPI and
   stages npm side by side. Both wait on the `release` environment together, so one approval from
   its reviewer starts both.
4. npm does not let CI publish directly. The npm job runs `npm stage publish`; once the PyPI job has
   succeeded (the launcher installs `openmhp` from PyPI), approve the staged version on npmjs.com (package → Staged versions, or `npx npm@latest stage list` and
   `stage approve`), which asks for 2FA.

The workflow holds no secrets: PyPI and npm each trust this repository, workflow file and
environment. One-time setup, in the web UIs:

- GitHub → Settings → Environments → `release`, with yourself under Required reviewers and
  Deployment branches and tags set to selected, with a tag rule `v*` (a tag push is not a branch).
- pypi.org → `openmhp` → Publishing → add a GitHub publisher: owner `kushalsinha`, repository
  `openmhp`, workflow `release.yml`, environment `release`.
- npmjs.com → `openmhp-cli` → Settings → Trusted Publisher → GitHub Actions, the same four values,
  with the `npm stage publish` permission (npm no longer allows direct publishing from CI).

The names must match exactly; a mismatch is refused by the registry, not by the workflow.

## Conduct

Be direct and kind. Assume the other person is a scientist, engineer, or operator with real
equipment and limited time.

## How this code was written

Parts of this codebase were written with Claude (Anthropic) as a coding collaborator, working
from the maintainers' design decisions. Commits carry co-author trailers where that applies.
