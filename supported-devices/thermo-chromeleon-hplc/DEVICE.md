---
mhp: "2026-09-12"
id: thermo-chromeleon-hplc-01
class: chromatograph
make: Thermo Fisher Scientific
model: Vanquish or UltiMate 3000 under Chromeleon 7.x
location: ""
tags: [hplc, uhplc, chromatography, analysis, chromeleon, sdk]
description: An HPLC or UHPLC system (Vanquish, UltiMate 3000) controlled by Chromeleon 7.x, reached through the Chromeleon SDK on the Chromeleon client PC (Windows, 32-bit Python). Pick it to inject a list of samples (positions, volumes, an instrument method per sample) as one sequence in a data vault folder, follow it to the end and read the peak table. Not for writing methods, not for stopping a run (a person does that in the Chromeleon console), and not usable without an SDK-enabled Chromeleon client.
driver: driver.py:Device
sim: sim.py:Sim
---

# Thermo Chromeleon HPLC

Chromeleon owns the instrument, the methods, the audit trail and the data. This package runs inside a
Chromeleon client installation and does what a user could do there: create a sequence in a data vault
folder from a sample list, copy the methods in, queue it on the instrument and start the queue, then read
peak results through the SDK's report-formula evaluation.

## Operating procedure

1. Read `connected` and `instrument_status`. The instrument must be idle before a new sequence is queued.
2. Find the method: `mhp_method op='find'` for the project. A saved method here is the instrument method
   name, processing method, channel and injection volume for a sample type.
3. Invoke `run_samples` with the sample list. The package writes a sequence named after the job, queues it
   and polls until the SDK has reported every injection ended.
4. Read the job result: sequence name and URL, the final instrument status, and the peak table (name,
   retention time, area, height) per injection.
5. To stop a sequence, a person uses the Chromeleon console; the SDK members used here have no abort.

## What to watch

- `instrument_status.state` reporting an error or not ready (pump pressure, lamp, sampler) needs a person
  at the console.
- `robot_access_ready` is true while no sequence from here is running, so a handling system may load or
  unload sampler positions then; it does not see sequences started from Chromeleon itself.
- Injection volumes must suit the sampler's loop; the limits here are generic (0.1 to 100 uL).
- Peaks come from the processing method's integration on the named `channel`; an injection with no
  identified peaks returns an empty list, not an error.

## Resources

- `references/setup.md`: the SDK licence, 32-bit Python, pythonnet, config.json, keyring, first test.
- `references/chromeleon_sdk.md`: the SDK members this package calls, their sources, and the unverified ones.
- `config.example.json`: SDK folder, data vault folder, instrument, user.
- `methods/_shared/assay-c18.yaml`: an example method record.
