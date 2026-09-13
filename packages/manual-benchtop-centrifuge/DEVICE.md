---
mhp: "2026-09-12"
id: centrifuge-01
class: centrifuge
make: generic
model: benchtop
location: ""
tags: [spin, biology, manual]
description: A benchtop centrifuge operated by a person. The agent asks the operator to load, balance and run it, and records the result. Use for pelleting cells, spinning down plates or tubes. Copy this package and edit the limits for your model.
driver: driver.py:Device
sim: sim.py:Sim
---

# Benchtop centrifuge (operator-run)

No cable, no code: the agent gives instructions and the operator does the work. Edit `speed` limits
in descriptor.yaml to your rotor's rating and set `location`.

## Operating procedure

1. Ask the operator to load tubes and balance them within 0.1 g (`balanced` must be recorded true).
2. Write `speed` and `duration_s`, then invoke `spin`; the operator starts the run and tells the agent when it stops.
3. Invoke `record` for anything the operator reads off the display (actual speed, temperature).
4. The operator unloads; the agent confirms and marks `door_open`.

## What to watch

- Never ask for a spin while `balanced` is not recorded true; the interlock refuses it.
- If the operator reports vibration or noise, invoke nothing further and note it in the run log.

## Resources

- none yet; add your model's rotor table under `references/`.
