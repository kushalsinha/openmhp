---
mhp: "2026-09-12"
id: srs-rga-01
class: mass_spectrometer
make: Stanford Research Systems
model: RGA100 / RGA200 / RGA300
location: ""
tags: [residual-gas-analyzer, mass-spectrometer, vacuum, filament, serial]
description: Stanford Research Systems RGA100/200/300 residual gas analyzer head over its RS-232 port (28800 baud). This package covers the ionizer and detector configuration and safety side of the head, filament emission on and off, electron and ion energy, focus and electron-multiplier voltages, the status and error registers, and electrometer calibration. Mass spectra and single-mass or total-pressure readings come back as 4-byte binary currents that this text-only driver does not read, so pick this package to put the filament and detector under agent control with interlocks and leave spectrum acquisition to RGA Windows, srsinst.rga or a code driver.
driver: driver.py:Device
sim: sim.py:Sim
---

# SRS RGA head

A quadrupole residual gas analyzer bolted to a vacuum chamber, with its electronics control unit
(ECU) talking RS-232 at a fixed 28800 baud. Everything that configures the ionizer and detector
and reports the head's health answers in ASCII and is declared here. Everything that measures,
`MR` (single mass), `TP?` (total pressure), `SC`/`HS` (scans), answers with 4-byte binary
currents and is **not** available through this package: use the vendor's RGA Windows software,
SRS's own `srsinst.rga` Python package, or write a code driver that subclasses this one.

## Operating procedure

1. Read `identity`, then `status_byte` (0 means no error) and `filament_ok`.
2. Make sure the chamber is below 1e-4 Torr (about 1.3e-4 mbar) on an independent gauge: the head does
   not read pressure for you here, and a filament switched on above that is damaged or shut off by
   the head's own protection. Then write `emission_setpoint` (typically 1.0 mA); it needs a person's
   confirmation. Read `emission_current`: it should match within 0.02 mA, and `filament_ok` should stay true.
3. Set `electron_energy_setpoint` (70 eV), `ion_energy_setpoint` (1 = 12 eV), `focus_setpoint` (90 V) if the defaults are not wanted.
4. Only below about 5e-6 Torr, and only on a head with the CDEM option (`cdem_installed`), write `cdem_setpoint` (1400 V typical); also confirmed by a person. `cdem_setpoint` 0 returns to the Faraday cup.
5. Invoke `calibrate_all` (confirm; up to two minutes) before quantitative work; it rezeros the detector and leaves the RF off.
6. When done invoke `filament_off`, or `standby` (filament and CDEM off, defaults restored).

## What to watch

- `filament_error` non-zero (bits: 0x20 chamber pressure too high, 0x40 cannot reach the set emission, 0x80 no filament) means the head shut the filament off; fix the vacuum before trying again. The head clears it only after a successful switch-on.
- The ECU answers hardware commands (`FL`, `EE`, `IE`, `VF`, `HV`, `IN`, `CA`) with its STATUS byte once the action completes, which for the filament takes a few seconds; `replies` on an action carries that byte.
- Any command sent during a scan started elsewhere aborts the scan; do not share the port with RGA Windows.

## Resources

- `references/setup.md`: cable, port, serial settings, first hardware test, and what this package deliberately leaves out.
- `references/protocol.md`: the command set and error-byte tables this package uses, from the SRS manual.
