---
mhp: "2026-09-12"
id: quantum-design-ppms-01
class: cryostat
make: Quantum Design
model: PPMS / DynaCool / MPMS3 (VersaLab and OptiCool by the same shape)
location: ""
tags: [cryostat, magnet, low-temperature, ppms, dynacool, mpms3, multivu, materials-characterization]
description: Quantum Design PPMS, DynaCool or MPMS3 cryostat driven through the MultiVu socket server (the vendor's MultiPyVu package, MIT, on PyPI). Pick it to read the sample temperature, the magnetic field and the chamber state, to set a temperature or field setpoint with a ramp rate and approach mode, to ramp and wait for stability as one job, and to seal, purge or pump the sample chamber. The MultiVu PC is Windows; this client runs anywhere on the network. Not for the measurement options (resistivity bridge, VSM, ACMS) and not for the rotator.
driver: driver.py:PpmsCryostat
sim: sim.py:SimPpmsCryostat
---

# PPMS / DynaCool / MPMS3 (MultiVu socket server)

MultiVu owns the cryostat. Quantum Design's MultiPyVu runs a small socket server next to MultiVu on
the instrument PC and a client anywhere else; the client reads temperature, field and chamber state
and sets their setpoints. Only the sample environment is reachable this way: the measurement
options (bridges, VSM, ACMS) are not. This package wraps that client: every call lives in
`PpmsBackend`, the twin swaps it for a model that ramps temperature and field at the rates you ask.

## Operating procedure

1. Read `connected`, `temperature`, `temperature_status`, `field`, `field_status` and
   `chamber_state`. Nothing should be written until `temperature_status` and `field_status` read
   as stable states and `chamber_state` is what the sample needs (sealed or purged and sealed for
   a cooled sample).
2. Temperature: write `temperature_rate` (K/min) and `temperature_approach` first if the defaults
   are wrong, then `temperature_setpoint` (K); or run `set_temperature_and_wait` with the target,
   rate, approach and a `settle_s`, which returns when MultiVu reports the temperature stable.
3. Field: `field_setpoint`, `set_field_and_wait` and `discharge_magnet` need a person's confirmation
   because they energise a superconducting magnet; write `field_rate` and `field_approach`
   (linear, no_overshoot, oscillate) first. On a PPMS the magnet can be left persistent or driven
   (`field_driven_mode`); every other platform refuses that setting.
4. `set_chamber` seals, purges, vents or pumps the sample chamber; venting a cold chamber ices the
   sample space, so it needs confirmation. Wait for `chamber_state` to settle before loading.
5. A ramp that is cancelled from here is not stopped on the instrument: MultiVu keeps driving to
   the setpoint it was given. Write a new setpoint to change where it goes.

## What to watch

- `field_status` reading `Charging`, `Discharging` or `Iterating` while a temperature job runs:
  the magnet is still moving and the sample is not at a stable field.
- `temperature_status` reading `Pot Operation` or `Impedance Control Error` for more than a few
  minutes: MultiVu is struggling with the cooling annulus; look at the instrument.
- `chamber_state` reading `Flooding` or `Venting continuously`: the sample space is at atmosphere
  and must not be cooled below the dew point.
- The status words are MultiVu's own and are passed through unchanged; see `references/multipyvu.md`
  for the ones this package has been told about.

## Resources

- `references/setup.md`: installing MultiPyVu, starting the server on the MultiVu PC, the port,
  the first hardware test.
- `references/multipyvu.md`: the MultiPyVu calls this package uses, their units and modes, the
  source document and what is unverified.
- `config.example.json`: host and port of the MultiVu socket server.
