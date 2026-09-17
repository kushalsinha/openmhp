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
python tests/test_methods.py
```

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

## Conduct

Be direct and kind. Assume the other person is a scientist, engineer, or operator with real
equipment and limited time.

## How this code was written

Parts of this codebase were written with Claude (Anthropic) as a coding collaborator, working
from the maintainers' design decisions. Commits carry co-author trailers where that applies.
