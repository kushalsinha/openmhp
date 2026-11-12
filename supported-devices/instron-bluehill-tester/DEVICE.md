---
mhp: "2026-09-12"
id: instron-bluehill-tester-01
class: mechanical_tester
make: Instron
model: 3400 / 5900 / 6800 series under Bluehill Universal
location: ""
tags: [tensile, mechanical-testing, instron, bluehill, universal-testing-machine, modulus, template]
description: A template for an Instron 3400, 5900 or 6800 series electromechanical universal testing machine run by Bluehill Universal on its Windows PC, driven through the Bluehill Universal API (a WCF/.NET interface Instron documents only by name; every member here is unverified). Pick it to run one tensile, compression or flexure test from a saved Bluehill method at a typed crosshead rate with load and extension limits, to watch load, extension and crosshead state while it runs, and to get back the peak load and modulus from Bluehill's results export. Not for cyclic or fatigue programs, not for changing a method, and the specimen is loaded by a person.
driver: driver.py:InstronBluehill
sim: sim.py:SimInstronBluehill
---

# Instron 3400 / 5900 / 6800 under Bluehill Universal (template)

Bluehill Universal owns the frame: it holds the test methods (crosshead rate, limits, calculations,
export), runs the test, stops at the method's limits or at specimen break, and writes the results
and raw-data exports it is configured for. Instron ships a "Bluehill Universal API" (included with
the standard licence; .NET/C#/VB "or any language that connects to Windows Communication
Foundation"; documented use cases: import specimen inputs, open a method and start a test from an
external device, export results) but publishes no member names, so this package is a **template**:
`InstronBackend` holds every call against the shape such an API must have, each member name is
configurable in `config.json` and marked unverified, and the twin runs the same driver against a
fake frame. Results come from the results-table export Bluehill writes at the end of each test.

## Operating procedure

1. Read `connected`, `frame_ready` and `crosshead_state`. On a 3400 or 6800 the frame must be
   enabled at its own panel (DISABLED to SET UP to CAUTION); the API cannot do that.
2. A person fits the specimen in the grips, zeroes load and extension in Bluehill, and steps clear.
3. Find the project's method record: `methods/find {compound, project}`; invoke `run_test` with
   `method: {name, project}` and `params: {specimen: {...}}`; `approved: true` after a person
   confirmed. The package opens the Bluehill method, sets the specimen inputs and the crosshead
   rate and limits, and starts the test (on a 3400/6800 Instron's operator protection may still
   require the Start key on the frame's panel or handset).
4. Poll the job; read `load` and `extension` while it runs. The job ends when Bluehill reports
   the test finished (specimen break, a limit, or the method's end).
5. Read the result: `peak_load_N`, `modulus_MPa`, `file` (the results export), `raw_file`.
6. `stop_crosshead` halts the crosshead at once; `safety/estop` does the same and disables the
   frame. The frame's own red E-stop button removes drive power and must be reset by a person.

## What to watch

- Nothing here runs until the member names in `config.json` `api` are corrected from the API help
  installed with Bluehill (Start > Instron > Help > Bluehill Help > API) and the export file names
  match what the method writes (`references/bluehill_api.md`).
- `rate_mm_min` and the `limits` are bounded conservatively (0.001 to 500 mm/min, 50 kN, 500 mm);
  set `descriptor.yaml` to the frame's load cell and travel and ship that as a package edit.
- The modulus is Bluehill's own calculation from the method; it is null when the method's results
  table has no modulus column.

## Resources

- `references/setup.md`: Bluehill Universal, the API licence, the Windows PC and the first test.
- `references/bluehill_api.md`: what Instron documents, the assumed members, the export layout, unverified items.
- `config.example.json`: the WCF endpoint, outputs folder, API member names, export column names.
