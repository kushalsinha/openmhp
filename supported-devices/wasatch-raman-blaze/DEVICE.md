---
mhp: "2026-09-12"
id: wasatch-raman-blaze-01
class: spectrometer
make: BlazeMetrics / Wasatch Photonics
model: Blaze Raman probe on a Wasatch spectrometer
location: ""
tags: [raman, spectroscopy, in-situ, copper-oxide, co2rr]
description: In situ Raman through a BlazeMetrics Blaze probe coupled to a Wasatch Photonics spectrometer and laser, for example on the electrode of an electrochemical flow cell. Pick it to take a spectrum, or a timed series during electrolysis, and get back the intensity of the configured bands (Cu2O at 149, 219, 419, 630 cm-1 by default). Not a product analyser (use the GC) and each spectrum takes seconds, so it averages over pulses shorter than its exposure.
driver: driver.py:BlazeRaman
sim: sim.py:SimBlazeRaman
---

# Blaze Raman probe (Wasatch spectrometer)

The Blaze probe looks at the sample through the cell's optical window; the Wasatch spectrometer
and its laser connect to the bench PC by USB. This device drives the Wasatch directly. The
Blaze probe's own software (microscopy, turbidity) is not involved.

## Operating procedure

1. Read `connected` and `laser_enabled`.
2. Set `integration_time_ms` (the paper used 5000) and, if needed, `scans_to_average`.
3. A person turns the laser on: writing `laser_enable` true asks them to confirm. Do this once at
   the start of a campaign and leave it on; do not toggle it per spectrum.
4. Invoke `acquire` for one spectrum, or `acquire_series` (count and interval) to follow the
   catalyst during electrolysis. Each spectrum's band intensities are pushed as `last_spectrum`.
5. Read the job result: band intensities over time and the path of the saved spectra on the bench PC.
6. At the end of the campaign write `laser_enable` false.

## What to watch

- All four Cu2O bands falling toward zero during reduction means Cu+ is being reduced to metal;
  under pulsed operation they should persist.
- A spectrum taken with the laser off is a dark spectrum; `laser_enabled` is recorded in every result.
- Saturation (`saturated: true`) means the integration time is too long.
- Emergency stop turns the laser off.

## Resources

- `references/setup.md`: installation on the bench PC and config.json.
- `config.example.json`: spectrometer serial, band list, data folder, laser power cap.
