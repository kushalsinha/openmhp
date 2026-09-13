# Methods on GC-01

A method is the complete set of parameters for one injection. On this instrument:

| Parameter | Effect |
|---|---|
| `oven_program` | Start temperature and holds set how long early-eluting compounds are retained; ramps set how fast later ones come off. Slower ramps separate close peaks better and lengthen the run. |
| `carrier_flow_ml_min` | Higher flow shortens every retention time and broadens close peaks slightly; lower flow does the opposite. 0.5 to 5 mL/min. |
| `injection_volume_ul` | Scales every peak area. Above about 2 uL the inlet overloads and peaks broaden. 0.1 to 5 uL. |

Resolution between neighbouring peaks is `2 * (rt2 - rt1) / (w1 + w2)`. Baseline separation needs 1.5.

Typical starting points:

- Solvents (acetone, ethanol, toluene): 60 degC for 60 s, ramp 20 degC/min to 200 degC, 1 uL, 1.5 mL/min.
- Close-boiling isomers: 50 degC for 120 s, ramp 5 degC/min to 180 degC, 1 uL, 1.0 mL/min.

Methods are saved per project under `~/.openmhp/methods/` and versioned; the run log records the
method name, version and hash with every injection.
