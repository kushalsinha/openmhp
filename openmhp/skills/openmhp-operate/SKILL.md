---
name: openmhp-operate
description: Operate laboratory instruments and factory machines safely through the Open Model Hardware Protocol using the mhp-mcp tools (mhp_find, mhp_describe, mhp_read, mhp_write, mhp_invoke, mhp_job, mhp_estop, mhp_run). Use whenever a task involves running an experiment, protocol, calibration, measurement or physical process on connected hardware, or when an MHP lab, directory, thermocycler, liquid handler, robot arm, microscope or similar device is available as an MCP server.
license: Apache-2.0
compatibility: Needs an MCP connection to an mhp-mcp bridge (stdio or HTTP). Works in any harness that supports MCP tools.
metadata:
  author: openmhp
  version: "0.2"
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
6. **Verify.** Read the signals that prove the outcome before reporting success.

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
  elicitation the server asks them directly; otherwise ask them, show the action's notes, and only
  then re-send with `approved: true`. Never set it on your own judgment.
- **`approval: forbid`** is listed so you know the capability exists. Do not look for another
  path to it.
- **Refusals.** `LimitViolation` (-32010): the value is outside physical limits; choose a value
  inside `data.min..max` or ask. `InterlockOpen` (-32011): read the named signal, tell the user
  what must change (lid, door, person in cell). `ApprovalRequired` (-32012): see above.
  `EStopActive` / `DeviceFault`: report; call `safety/reset` only after a human agrees the
  cause is understood.
- **Methods.** Never invent parameters for a method-driven action when a method exists for the
  compound: find, then run by name so the job carries the method's project, name, version and
  hash. Adapt between runs with `overrides`; when the tuned values work, save them as the next
  version rather than leaving them only in your context. Results arrive without asking:
  `mhp_data op='updates' device=...` shows each pushed result; decide the next run from it.
- **E-stop.** `mhp_estop` is always allowed and always succeeds. Use it the moment a reading,
  a notification, or the user suggests something is wrong. Then report, do not resume.
- **Leases.** Hold a lease (`with dev:` in scripts) whenever a sequence must not be
  interleaved by another agent. Release it when done.
- **Report** what you read, not what you intended. "Block reached 95.0 °C at 14:02" beats
  "started the protocol".
