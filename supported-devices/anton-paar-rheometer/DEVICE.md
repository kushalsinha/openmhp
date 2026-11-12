---
mhp: "2026-09-12"
id: anton-paar-rheometer-01
class: rheometer
make: Anton Paar
model: MCR 72 / 92 / 102e / 302e / 502e under RheoCompass
location: ""
tags: [rheometer, rheology, anton-paar, mcr, rheocompass, viscosity, flow-curve, oscillation]
description: An Anton Paar MCR rotational rheometer (72, 92, 102e, 302e, 502e or the new 303/503) run by RheoCompass on its Windows PC with a Peltier plate and its hood. Pick it to queue one flow curve (shear-rate ramp) or frequency sweep of a named sample at a set temperature with a project's saved test definition, to read the measured and setpoint temperature while it runs, and to get back RheoCompass's ASCII export with viscosity, shear stress or the moduli at the last point. Not for loading the sample, trimming, setting the gap or changing a measuring system, all of which a person does at the rheometer, and it cannot see the hood unless the lab writes its state to a file.
driver: driver.py:AntonPaarRheometer
sim: sim.py:SimAntonPaarRheometer
---

# Anton Paar MCR under RheoCompass

RheoCompass owns the rheometer: it holds the projects and test definitions in its SQL database,
drives the measuring head, the temperature device and the measurement, and exports a result as
ASCII, XML or PDF. Anton Paar publishes no automation interface for RheoCompass itself (its LIMS
route is AP Connect, a separate server product), so this package queues one test per request by
writing a job file into a folder the lab's RheoCompass workflow (Test Analysis Designer actions,
an AP Connect task list, or a person at the console) reads, waits for the ASCII export, and
parses it. Each queued test is confirm-gated.

## Operating procedure

1. Read `connected`, `hood_closed` and `temperature`. A person loads the sample on the lower
   plate, sets the gap, trims, lowers the hood and leaves the console at the start screen.
2. Find the project's test definition: `methods/find {compound, project}`. Invoke `queue_test`
   with `method: {name, project}` and `params: {sample_name}`; `approved: true` after a person
   confirmed. The job file carries the test type, measuring system, temperature and the ramp or
   sweep of the method.
3. Poll the job. `temperature_setpoint` reads the job's temperature while it runs; `temperature`
   follows the live export when the lab configured one. Progress rises with the expected test
   time (points times point duration, plus temperature equilibration).
4. Read the result: `file` (the ASCII export), `points`, `temperature_mean_c`, `summary`
   (viscosity and shear stress at the last point for a flow curve; storage and loss modulus for
   a frequency sweep). Open the file in RheoCompass or any reader of its tab-separated export.
5. To stop: cancel the job before it was taken (the file is removed); afterwards a person presses
   Stop in RheoCompass and lifts the head.

## What to watch

- The job file is this package's own CSV. RheoCompass publishes no import format: the lab's
  administrator maps it to a Test Analysis Designer workflow, an AP Connect task or an operator
  routine (see `references/rheocompass_files.md`). Until that mapping is done, nothing queued
  here runs.
- `hood_closed` is read from a one-line file the lab maintains (`hood_state_file`); without it
  the interlock reads false and `queue_test` refuses. The MCR does not report its hood.
- The export reader handles UTF-16 or UTF-8, tab separation, a decimal comma, `n.a.` cells and
  the `Interval data:` column header RheoCompass writes; the exact header lines of your
  RheoCompass version are unverified, so compare the first export with the parsed `columns`.
- Temperature is bounded -40 to 200 degC here (a P-PTD 200 Peltier plate); the lab sets its own
  for a CTD oven or a cooled plate.

## Resources

- `references/setup.md`: RheoCompass, the folders, the hood file, the Windows PC and the first test.
- `references/rheocompass_files.md`: the job file, the ASCII export, sources and unverified fields.
- `config.example.json`: job and results folders, live export, hood state file, bounds.
