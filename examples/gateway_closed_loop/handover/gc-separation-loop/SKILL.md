---
name: gc-separation-loop
description: Pick the next GC conditions (carrier flow, oven ramp) that separate every neighbouring peak in the shortest run, from the injections made so far. Use when optimising a chromatographic separation one injection at a time.
---

# GC separation loop

Keep every injection in `history.json` as a list of
`{"carrier_flow_ml_min": .., "ramp_c_min": .., "resolution_min": .., "run_time_s": ..}`.
Ask for the next condition with:

```bash
python suggest.py history.json
```

It prints one JSON object: `{"carrier_flow_ml_min": .., "ramp_c_min": .., "why": ".."}`, or
`{"done": true, "best": {...}, "why": ".."}` when more injections will not help.

A condition is good when `resolution_min >= 1.5`; among good ones, shorter `run_time_s` wins.
Bounds: carrier flow 0.5 to 5 mL/min, ramp 2 to 40 C/min.
