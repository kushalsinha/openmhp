---
name: openmhp-operate
description: Operate laboratory instruments and factory machines safely through the Open Model Hardware Protocol using the mhp-mcp tools (mhp_find, mhp_describe, mhp_read, mhp_write, mhp_invoke, mhp_job, mhp_estop, mhp_reset, mhp_run, mhp_lab, mhp_data, mhp_method). Use whenever a task involves running an experiment, protocol, calibration, measurement or physical process on connected hardware, or when an MHP lab, directory, thermocycler, liquid handler, robot arm, microscope or similar device is available as an MCP server.
license: Apache-2.0
compatibility: Needs an MCP connection to an mhp-mcp bridge (stdio or HTTP). Works in any harness that supports MCP tools.
metadata:
  author: openmhp
  version: "0.5"
---

# Operating hardware through OpenMHP

The lab may hold thousands of devices. You never list them. You search, open one, and act.
Every write and action is checked by the device's own driver against limits, interlocks and
approval levels; a refusal is information, not an obstacle to work around.

## If the lab is empty or the device is missing

`mhp_find` returning nothing is not the end. `mhp_lab op='scan'` finds MHP devices on the
network (pass `hosts` for specific machines); `mhp_lab op='add'` puts one in the lab. For an
instrument that does not speak MHP yet, offer to onboard it with the `openmhp-onboard-device`
skill: a short interview, then `mhp_lab` writes and registers the package.

## The loop

1. **Find.** `mhp_find` with a plain-language query and filters (`class`, `location`,
   `state: "idle"`). Read the cards. Never guess a device id.
2. **Open.** `mhp_describe(device)` gives the summary: every signal, setting and action with
   units, limits and approval level. Then `mhp_describe(device, select={"actions": [...],
   "settings": [...]})` for the full spec of only the items you will use, including `notes` and
   `examples`. Read the notes; they are the owner's tacit knowledge.
3. **Check.** `mhp_read` the interlock signals and anything the notes told you to check.
   If the summary lists `methods` (an action marked `methods: true`: HPLC, GC, MS, PXRD, a
   thermocycler's programs), the instrument runs saved methods. Ask it which one:
   `mhp_method op='find' device=... compound=... project=...`. One match: use it. Several: ask
   the person which (an autonomous loop with a declared project takes the project's own). None:
   ask the person for the parameters, run once with explicit params, then `op='save'` them under
   the project. Invoking such an action with neither a method nor params is refused
   (`MethodRequired`) and tells you the same thing.
4. **Rehearse.** `mhp_write` / `mhp_invoke` with `dryRun: true` first for anything that heats,
   moves or dispenses. A dry run runs every gate without touching hardware.
5. **Act.** Invoke. Long actions return a job; poll with `mhp_job`, do not spin in a tight loop.
6. **Verify.** Read the signals that prove the outcome before reporting success. Re-read until
   the value is stable: an instrument that just finished a job may report a stale reading until
   its measurement engine has recomputed.

## Rehearse before you act

For anything with more than one step, or anything that heats or moves: look for a recipe first
(`mhp_lab op='recipes'`), then `mhp_run plan=true` with the recipe or your script. Show the human
the plan: each step, the steps that will ask them, the first step that would be refused. Only
after they say go, run it. Use `background=true` when it takes more than a few minutes and
follow with `mhp_data`. A human can pause a job (`mhp_job op='pause'`) to step in.

## Multi-step work: use `mhp_run`

Anything with loops, several devices, or large intermediate data goes in a script passed to
`mhp_run`. The script sees `lab`; use `with lab["a"], lab["b"]:` to hold leases for the
duration, `dev.wait(dev.invoke(...))` to sequence, and print only the summary you need.
Readings, traces and images stay out of your context.

`lab["id"]` gives you the device API and only that: read, write, invoke, run_method, wait,
status, pause/resume/cancel, acquire/release, estop, reset, describe, resources, the method
calls. The driver object and untracked transport calls are not reachable from a script, and
reaching for them is refused and written to the run log. A limit that refuses you in a tool call
refuses you here too; report it rather than looking for a way around it. Some labs run no
scripts at all, and then `mhp_run` is simply absent: drive the instruments step by step.

```python
arm, tc = lab["arm-01"], lab["thermocycler-0411"]
with arm, tc:
    arm.wait(arm.invoke("pick_plate", location="deck_A1"))
    arm.wait(arm.invoke("place_plate", location="thermocycler"))
    j = tc.wait(tc.invoke("run_protocol", steps=PCR, cycles=30))
print(j["result"])
```

## Rules

- **`approval: confirm`** means a human must say yes to *this* call. If your harness supports
  elicitation the server asks them directly. Without an elicitation channel the call is simply
  unavailable: `approved: true` may only be set by the host after a person confirmed that exact
  request — never by you, and re-sending it yourself does not work. The ways out are human-held:
  the CLI prints the command to re-run with `--approved` once that person has checked it, and the
  SDK accepts an `approver` callback bound to the exact request — set on each `Device`; a
  `Lab(approver=...)` forwards it to every device it connects.
- **`approval: forbid`** is listed so you know the capability exists. Do not look for another
  path to it.
- **The package is the rulebook, not a workaround.** `descriptor.yaml` is what the server enforces,
  so editing a package to widen a limit is not a fix and will not work: the device keeps enforcing
  the configuration its owner accepted, and `mhp_lab op='reload'` asks them, naming the bound that
  would move. Report the refusal and the value you needed instead.
- **Every answer says what comes next.** `ping`, `mhp_describe` and every refusal (`mhpError`) carry
  the device's `state`, the facts behind it (`active_jobs`, `fault_reason`, `stop` with who stopped it
  and whether software can clear it) and `next`: steps as `{tool, does}`, most useful first. A step
  with no tool is for a person: say it to the user. Refusals also carry `transient` (can the same
  call work later), `effect` (what reached the instrument: `none`, `partial`, `unknown`) and
  `recovery` (`retry`, `retry_after`, `abort`, `operator`): never retry when `effect` is not `none`
  and `recovery` is `operator`; tell the user instead.
- **Refusals.** `LimitViolation` (-32010): the value is outside physical limits; choose a value
  inside `data.min..max` or ask. `InterlockOpen` (-32011): read the named signal, tell the user
  what must change (lid, door, person in cell). `ApprovalRequired` (-32012): see above.
  `EStopActive` / `DeviceFault`: tell the user what stopped and why, and ask them to check the
  instrument. Then `mhp_reset`: the server asks them to confirm (you cannot), and refuses while
  jobs still run or while a stop latched at the instrument is still engaged there (it says what must
  be done there). `mhp_find state='unreachable'` lists devices whose lab PC did not answer.
- **Methods.** Never invent parameters for a method-driven action when a method exists for the
  compound: find, then run by name so the job carries the method's project, name, version and
  hash. Adapt between runs with `overrides`; when the tuned values work, save them as the next
  version rather than leaving them only in your context. Results arrive without asking:
  `mhp_data op='updates' device=...` shows each pushed result; decide the next run from it.
- **E-stop.** `mhp_estop` is always allowed and never waits. Use it the moment a reading,
  a notification, or the user suggests something is wrong. Then report, do not resume. If the
  answer says `stopped: false`, the device's own stop step failed: tell the user at once, the
  instrument may still be moving or heating.
  `device: "*"` stops everything the lab is driving, including instruments a running script
  opened, and the result names each one; a stopped device needs a person to reset it.
- **Leases.** Hold a lease (`with dev:` in scripts) whenever a sequence must not be
  interleaved by another agent. Release it when done. A release while your jobs still run is
  refused (it would disarm the watchdog): wait for the jobs, or release with `stop=True` to wind
  them down. A script's run ends only when the jobs it started have ended.
  Trap: any actuating call auto-acquires a lease and starts a heartbeat thread that renews it
  indefinitely — dropping the Device object does not stop it, so the lease outlives the code that
  made it. The holder is a random session id (`client-…`), not the name passed to connect(); and
  within one process every connect() to the same package shares one driver instance, so a second
  connect() of your own counts as "another client". Reads never need a lease.
  On `leased to another client`: get the holder from the error data. Same process: find the old
  Device among live objects (match by display name) and call `release()` on it — that stops the
  heartbeat. A long-lived bridge holds its own leases: `mhp_lab op='release'` hands them back.
  Otherwise the lease dies only when the holder process does (TTL expires once heartbeats stop).
- **Report** what you read, not what you intended. "Block reached 95.0 °C at 14:02" beats
  "started the protocol".

## When the web is out of reach

On many company machines an agent has no web or git access. Everything on openmhp.com ships inside the installed
package, so read it there instead of guessing:

- `mhp guide`: the topics. `mhp guide <topic>` reads one (troubleshooting, quickstart, gateway, lab-nodes,
  experiment-flow, add-a-device, cookbook, adapters, spec, ...). `mhp guide search <words>` finds the lines that
  mention them.
- `mhp --version`: which OpenMHP is installed. `mhp gateway --version`, `mhp node --version` and
  `mhp agent --version` also say what the running gateway, the instrument PC's service, or the joined gateway runs.
- Installed with npx only: the same commands as `npx -y openmhp-cli@latest mhp guide ...`.

When a command is refused or answers oddly, check the versions first, then `mhp guide troubleshooting`.
