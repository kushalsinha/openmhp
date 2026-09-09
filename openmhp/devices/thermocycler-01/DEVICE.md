---
mhp: "2026-09-09"
id: thermocycler-01
class: thermocycler
make: SimBio
model: TC-96
location: bay 3, bench 3
tags: [pcr, heating, 96-well]
description: 96-well PCR thermocycler with heated lid, 4 to 105 degC block. Use for PCR, denaturation, ligation holds and any timed temperature program on a 96-well SBS plate. Not for tubes, not for cooling below 4 degC.
driver: driver.py:SimThermocycler
---

# Thermocycler-01

Sits on bench 3 in bay 3, immediately left of the liquid handler; the plate arm reaches it at
location `thermocycler`. The block ramps about 4 °C/s. The lid heater needs about 40 s to reach
105 °C, so turn `lid_heater` on before loading the plate to avoid condensation.

## Operating procedure

1. Confirm `lid_closed` reads true. `run_protocol` refuses to start otherwise.
2. Set `lid_heater` true. Wait for `lid_temperature` above 100 °C.
3. Invoke `run_protocol` with the steps and cycle count. It returns a job; poll it. A 30-cycle
   three-step program takes about 75 minutes on this block.
4. When the job is done, write `target_temperature` 4 to hold the plate.
5. Only open the lid (`open_lid`, needs human confirmation) once `lid_temperature` is below
   60 °C, or ask someone with gloves to be present.

## What to watch

- Edge wells lag the centre by about 0.5 °C; read `block_temperature` as the centre value.
- Steps above 105 °C or below 4 °C are refused by the driver, inside protocols too.
- A failed job leaves the device in `fault`; read `block_temperature`, then `safety/reset` after
  a human agrees the cause is understood.

## Resources

- `references/protocols.md`: standard PCR programs for common polymerases.
- `scripts/pcr.py`: a complete run through `mhp_run`, including the 4 °C hold.
