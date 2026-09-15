# Contributing to OpenMHP

The two contributions that help most are **device packages** for instruments people own and
**recipes** for procedures people run. Both are folders or files; no changes to the core are
needed.

## A device package

1. Create `packages/<make-model>/` with `DEVICE.md`, `descriptor.yaml`, `driver.py`, and ideally
   `sim.py` (a simulated twin) and `references/` (the manual excerpt you used).
2. `DEVICE.md` frontmatter: `id`, `class`, `make`, `model`, `tags`, a `description` that says
   what it is and when to pick it, and `driver`/`sim` entries. The body is the operating
   procedure, what to watch, and a resources list. See `openmhp/devices/thermocycler-01`.
3. Every numeric setting has `limits`. Every action that heats or moves has `interlocks` or
   `approval: confirm`. Actions with params have `examples`.
4. Run `mhp validate packages/<name>` and `mhp lab add packages/<name> --sim` followed by a
   safety card (`mhp_lab op="safety_card"` from an agent, or `python -c` against `openmhp.safety`).
   Paste the safety card into the pull request.
5. Add an entry to `openmhp/registry.json`.

Routes: `openmhp.drivers.serial_ascii` for text commands (declare them in `descriptor.yaml`),
`openmhp.drivers.manual` for operator-run instruments, the adapters in `openmhp/adapters/` for
OPC UA, ROS 2, SiLA 2, MADSci and PyLabRobot, or a `Driver` subclass for a vendor SDK.

## A recipe

1. Add `openmhp/recipes/<name>.py` with the header lines `# recipe`, `# needs`, `# asks`,
   `# summary` and a `PARAMS = {...}` block, then the body. See the existing recipes.
2. Choose devices with `lab.find(..., cls=..., state="idle")` unless a PARAMS id is given, hold
   leases with `with`, save data under `run_dir`, print one summary line, never catch and hide
   a refusal.
3. Run it in plan mode and for real against simulated twins; paste both outputs into the pull
   request.

## Code

Tests are plain Python files: `python tests/test_adapters.py`, `python tests/test_runs.py`,
`python tests/test_safety_gates.py` (the safety-gate and runtime-guarantee regressions) and
`python tests/test_methods.py` (the methods rules M1..M10 and pushed events reaching the agent).
They run against injected fakes and the bundled simulators; no hardware. Keep the tool surface
at ten MCP tools, keep safety enforcement in the driver, and keep device descriptions readable
by a person.

## Conduct

Be direct and kind. Assume the other person is a scientist with a broken instrument and a
deadline.
