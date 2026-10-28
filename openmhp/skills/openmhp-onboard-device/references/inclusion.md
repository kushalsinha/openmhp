# What a package must pass to be included in `supported-devices/`

Run it, do not read it:

```bash
mhp inclusion <device package folder>            # or: python scripts/check_inclusion.py <folder>
```

Every check below is one line of that report. `[x]` passed, `[ ]` failed, `[-]` was skipped
because it does not apply to this device — a skip is not a pass, and the report says why it
skipped. Two tiers: **Package** applies to any package anywhere, including one that never
leaves your lab, and is the one to run before you hand DEVICE.md to the owner. **Submission**
is what the openmhp repository additionally needs in order to carry the package.

## Package

| Check | What it means | If it fails |
|---|---|---|
| `mhp validate` reports no errors | the files are well formed | fix the errors it names; warnings are advice, not blockers |
| a driver does not change what it enforces | no assignment to `self.descriptor` outside `setup()`, and none ever to `_enforced`, `_index` or `_seal_digest` | move the edit into `setup()`, or into the package files where a person can see it |
| a driver does not override a safety gate | `_gate`, `_verify_seal`, `_reindex`, `_check_*` are not redefined | put vendor code in `setup`, `on_read`, `on_write`, `on_invoke`, `on_estop` |
| shipped scripts can run under the run sandbox | nothing in `scripts/` imports `openmhp` or `gc` | a script gets `lab`; use `lab['<device-id>']` and the device API |
| ships a simulated twin (`sim.py`) | somebody can rehearse, and CI can test without the instrument | write the twin; it is usually an afternoon and it is what makes the package reviewable |
| the safety block is declared, or says why it is not | `estop: true`, or `safety.notes` saying what stops this instrument instead; a watchdog window unless the device is operator-run; an example on every action that takes parameters | declare it, or write the sentence. A blank is read by somebody who cannot ask you what it meant |
| the twin loads with no vendor library and no `config.json` | import the vendor SDK inside `setup()`, not at module top | move the import; the twin must run on a laptop |
| all three describe tiers and `resources/list` answer | an agent reads card → summary → full in that order | |
| an unknown name is refused | `-32040`, not a silent `None` | |
| a refusal carries `ts`, `recovery`, `transient` and `effect` | an agent decides whether to retry from these fields, and cannot parse prose | raise the MHP error classes rather than bare exceptions |
| an out-of-range write is refused | `-32010` from the declared `limits` | |
| a confirm-gated action refuses without approval | `-32012` | |
| an open interlock refuses the action | `-32011` | |
| the first declared example of each action is accepted as a dry run | the worked example an agent will copy actually runs | fix the example, or the parameter declaration it contradicts |
| **no reported answer is a handle on the sealed configuration** | nothing a reporting RPC returns is an object *inside* what the gates read | return `copy.deepcopy(...)` |
| **loosening every reported rule changes nothing** | with every bound raised, interlock cleared, approval dropped and watchdog disarmed in the answers the device gave, the out-of-range call is still refused | as above: a reporting RPC is handing out the gate's own dict |
| **editing the sealed rules stops the device** | editing the sealed index in memory makes even a legal call refuse with `-32013` | your driver is not going through `Driver._gate`; do not answer writes in `on_write` alone |

The last three are the ones to understand rather than just pass. A device keeps two copies of
its configuration: `descriptor`, which it reports, and a sealed `_enforced`, which the gates
read. They are separate because they used to be the same, and a caller handed a bound could
raise it with one assignment to the answer it was given:

```python
dev.limits()["settings"]["target_temperature"]["max"] = 900     # and 900 was enforced
```

A run script is handed that API on purpose, and an agent writes run scripts, so every route
from a reported value back to an enforced one is a route from an agent to its own limits. The
base `Driver` closes it for you. A package reopens it by overriding a reporting RPC and
returning its own dict, or by rewriting `descriptor` while the instrument runs — which is why
those three checks are behavioural: they would catch the hole reappearing by a route nobody
has thought of yet.

## Submission

| Check | What it means |
|---|---|
| listed in `openmhp/registry.json` | name, description, tags, `target` ending in `supported-devices/<name>`, `sim: true` when there is a twin. Agents find packages through the registry |
| listed in the supported-devices table | a row in `supported-devices/README.md` with an honest status: `hardware tested`, `twin tested` or `template` |
| no site-specific values committed | no `config.json` in the package; ship `config.example.json` when the driver reads one |
| says how to reach the real instrument | `references/setup.md` with the vendor library, the host it needs, and a first-hardware-test section |

Then extend `tests/test_adapters.py` so the twin is exercised in CI, and open the PR. Status
starts at `twin tested`; change it to `hardware tested` only once someone has run the real
driver on the instrument and recorded the firmware and SDK versions in `references/setup.md`.

## Two things the gate cannot check for you

**Limits are the owner's, not the package's.** The shipped numbers are the instrument's range
or a conservative placeholder. Whoever installs the package has to set them to what their cell,
tubing or sample can take. Say so in `references/setup.md`.

**Changing a safety value is a file edit, reviewed by a person.** It is not a runtime action and
there is no API for it. Editing a package changes its fingerprint, so the lab that installed it
sees "changed on disk" and must accept the new version (`mhp_lab op='reload'`) before anything
runs — which is the point: a person sees the diff. Ship a limit change as a PR, not as a note
telling operators to edit the file.
