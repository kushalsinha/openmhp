<!-- generated from https://openmhp.com/recipes by scripts/build_guide.py; edit the website, not this file -->

# Recipes

Tested procedures an agent can find, adapt and rehearse. A recipe is an ordinary script with a header and a PARAMS block; the agent searches them by describing the experiment, overrides the parameters, plans the run, and only then executes.

## How an agent uses one

1. **Find.** `mhp_lab op="recipes" query="pcr with plate transfer"` returns the name, which device classes it needs, what it will ask the human, and its parameters.

2. **Adapt.** The agent fills PARAMS from the conversation: which plate slot, how many cycles, which device if there are several.

3. **Plan.** `mhp_run recipe="pcr-with-plate-transfer" params={...} plan=true` rehearses it. Reads are real; every write and action is a dry run through all the safety gates; nothing moves. The result lists each step, the ones that will ask a person, the long-running ones, and the first one the driver would refuse. The agent shows this to you.

4. **Run.** The same call without `plan`, or with `background=true` for anything long. Output and saved files land in the run folder; `mhp_data` reads them back.

## Bundled recipes

| Recipe | Needs | Does |
|---|---|---|
| `pcr-with-plate-transfer` | robot arm, thermocycler | moves a plate from the deck to the thermocycler, pre-heats the lid, runs the program, holds at 4 °C, returns the plate |
| `timed-hold` | any device with a setpoint | reaches a setpoint, holds it for a duration while logging readings to CSV, returns to a safe setpoint |
| `setpoint-sweep` | any device with a setting and a signal | steps through a list of setpoints, settles, records the measured value at each, saves a CSV and prints the table; calibration and characterisation |
| `periodic-readings` | any device with readable signals | logs chosen signals every N seconds for hours, with optional alert bands; run it in the background overnight |

## Writing your own

Put a file in `~/.openmhp/recipes/` (or a package's `scripts/` folder for a single-instrument procedure). The header lines are what the agent searches; PARAMS is what it overrides.

```
# recipe: bradford-assay
# needs: liquid_handler, plate_reader
# asks: which plate holds the samples; the standard curve wells
# summary: Dispense Bradford reagent into a sample plate, incubate 5 min, read absorbance at 595 nm, save the plate as CSV.
PARAMS = {"handler": None, "reader": None, "sample_plate": "deck_A1", "reagent": "trough_1", "volume_ul": 200}

import time, os
lh = lab[PARAMS["handler"] or lab.find("pipette reagent into plate", cls="liquid_handler", state="idle")[0]["id"]]
rd = lab[PARAMS["reader"] or lab.find("absorbance plate reader", cls="plate_reader", state="idle")[0]["id"]]
with lh, rd:
    lh.wait(lh.invoke("dispense", source=PARAMS["reagent"], target=PARAMS["sample_plate"], volume_ul=PARAMS["volume_ul"]))
    time.sleep(300)
    job = rd.wait(rd.invoke("read_absorbance", wavelength_nm=595))
with open(os.path.join(run_dir, "absorbance.csv"), "w") as f:
    f.write(job["result"]["csv"])
print("bradford read; absorbance.csv saved")
```

Rules that make a recipe safe to hand to an agent: choose devices by `lab.find` with a class and `state="idle"` unless a PARAMS id is given; hold leases with `with`; save data to `run_dir`; print one summary line; never catch and hide a refusal.

## What the plan looks like

```
{"verdict": "ok; 1 step(s) need a human's confirmation",
 "steps": [
  {"step": 1, "device": "arm-01", "kind": "write",  "target": "speed", "value": 30, "gate": "ok"},
  {"step": 2, "device": "arm-01", "kind": "invoke", "target": "home", "gate": "ok"},
  {"step": 3, "device": "thermocycler-01", "kind": "read", "target": "lid_closed", "value": true},
  {"step": 4, "device": "arm-01", "kind": "invoke", "target": "pick_plate", "params": {"location": "deck_A1"}, "gate": "ok"},
  {"step": 7, "device": "thermocycler-01", "kind": "invoke", "target": "run_protocol", "gate": "ok", "long_running": true},
  {"step": 9, "device": "thermocycler-01", "kind": "invoke", "target": "open_lid", "gate": "ok", "asks_human": true}],
 "refused": [], "asks_human": [{"step": 9, "target": "open_lid"}]}
```
