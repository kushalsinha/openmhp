---
mhp: "2026-09-12"
id: thermo-orbitrap-iapi-01
class: mass_spectrometer
make: Thermo Fisher Scientific
model: Orbitrap Fusion / Lumos / Eclipse / Ascend (Tribrid) via IAPI
location: ""
tags: [mass-spectrometer, orbitrap, proteomics, iapi, custom-scan, windows]
description: A Thermo Orbitrap Tribrid (Fusion, Lumos, Eclipse, Ascend) controlled through the Instrument API (IAPI) on its instrument PC. Pick it to watch the scans the instrument is producing (scan number, TIC) and to request single custom full scans with a chosen m/z window, resolution, AGC target, injection time and polarity, getting back the centroid list as CSV. It does not start acquisitions or methods, does not control the LC or the source, and runs only on the Windows instrument PC with Thermo's licensed IAPI assemblies.
driver: driver.py:OrbitrapIAPI
sim: sim.py:SimOrbitrapIAPI
---

# Thermo Orbitrap Tribrid (IAPI)

The IAPI is a .NET interface the instrument PC exposes while Tune runs; this package reaches it through
pythonnet. It subscribes to the scan stream and can place custom scans into the queue the instrument is
executing. Everything else, from source conditions to running a method, stays with Tune and Xcalibur,
which is deliberate: the API grants real-time control of what the instrument scans next, not of what it
is physically doing.

## Operating procedure

1. Read `connected` and `instrument_state`; it must be `On` (not `Standby` or `Off`) for scans to arrive.
   Read `last_scan_number` twice a few seconds apart: a rising number proves the instrument is scanning.
2. Invoke `request_custom_scan` with the m/z window and resolution. The job waits for the scan carrying
   the request's access id, writes its centroids to `peaks_csv`, and returns the scan number and TIC.
3. Cancel the job, or invoke `cancel_custom_scan`, to withdraw a request the instrument has not taken.
4. Read the CSV for peak picking; the package does no deisotoping or charge assignment.

## What to watch

- A job that times out with "no scan arrived" almost always means the instrument is in Standby, or Tune
  is not acquiring. Check `instrument_state` and `acquisition_state` before retrying.
- `tic` and `last_scan_number` follow every scan, including those the instrument takes on its own.
- Custom scan parameter names other than ScanType, FirstMass, LastMass, OrbitrapResolution, AGCTarget
  and MassAnalyzer are unverified; check the first scan's header on hardware (see `references/iapi.md`).
- Emergency stop cancels pending custom scans only; stop the instrument from Tune.

## Resources

- `references/setup.md`: the IAPI licence and assemblies, pythonnet, config.json, the first hardware test.
- `references/iapi.md`: the IAPI types and members used, with the unverified ones listed.
- `config.example.json`: assembly folder, instrument index, data folder, scan timeout.
