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

## The loop

1. **Find.** `mhp_find` with a plain-language query and filters (`class`, `location`,
   `state: "idle"`). Read the cards. Never guess a device id.
2. **Open.** `mhp_describe(device)` gives the summary: every signal, setting and action with
   units, limits and approval level. Then `mhp_describe(device, select={"actions": [...],
   "settings": [...]})` for the full spec of only the items you will use, including `notes` and
   `examples`. Read the notes; they are the owner's tacit knowledge.
3. **Check.** `mhp_read` the interlock signals and anything the notes told you to check.
4. **Rehearse.** `mhp_write` / `mhp_invoke` with `dryRun: true` first for anything that heats,
   moves or dispenses. A dry run runs every gate without touching hardware.
5. **Act.** Invoke. Long actions return a job; poll with `mhp_job`, do not spin in a tight loop.
6. **Verify.** Read the signals that prove the outcome before reporting success.

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

- **`approval: confirm`** means a human must say yes to *this* call. Ask them, show the action's
  notes, and only then re-send with `approved: true`. Never set it on your own judgment.
- **`approval: forbid`** is listed so you know the capability exists. Do not look for another
  path to it.
- **Refusals.** `LimitViolation` (-32010): the value is outside physical limits; choose a value
  inside `data.min..max` or ask. `InterlockOpen` (-32011): read the named signal, tell the user
  what must change (lid, door, person in cell). `ApprovalRequired` (-32012): see above.
  `EStopActive` / `DeviceFault`: report; call `safety/reset` only after a human agrees the
  cause is understood.
- **E-stop.** `mhp_estop` is always allowed and always succeeds. Use it the moment a reading,
  a notification, or the user suggests something is wrong. Then report, do not resume.
- **Leases.** Hold a lease (`with dev:` in scripts) whenever a sequence must not be
  interleaved by another agent. Release it when done.
- **Report** what you read, not what you intended. "Block reached 95.0 °C at 14:02" beats
  "started the protocol".
