---
mhp: "2026-09-12"
id: agilent-cary-uvvis-ftir-01
class: spectrometer
make: Agilent
model: Cary 60/3500 UV-Vis (Cary WinUV) and Cary 630 FTIR (MicroLab)
location: ""
tags: [uv-vis, ftir, spectroscopy, absorbance, identity, cary]
description: Agilent Cary 60 or 3500 UV-Vis spectrophotometer under Cary WinUV and Cary 630 FTIR under MicroLab, reached through a watched request folder on the instrument PC and the CSV spectra the vendor software exports. Pick it for a UV-Vis absorbance scan (190-1100 nm; A280, lambda-max, a UV identity) or an FTIR scan (4000-650 /cm; raw-material identity) of a sample a person has already placed, and to read the spectrum's points and maximum back. Not for kinetics, temperature ramps, multicell changers or library matching; those stay in the vendor software.
driver: driver.py:Device
sim: sim.py:Sim
---

# Agilent Cary UV-Vis and FTIR

Cary WinUV (UV-Vis) and MicroLab (FTIR) own the instruments, the methods and the data. This package
does what a person at that PC would be asked to do by a note: it drops one request file per scan into
a watched folder, waits for the exported CSV spectrum carrying the request's token, and turns it into a
result. A helper script on the instrument PC may act on the request unattended (Cary WinUV's ADL
scripting language is the tool for that; MicroLab has none), or a person reads the request and exports
the scan by hand. Either way the result file is what counts.

## Operating procedure

1. Read `connected` (both folders reachable) and `queue_depth` (requests nobody has picked up yet; if
   it grows, the helper or the person at the PC is not keeping up).
2. Find the method: `methods/find` with the assay's compound and project. A saved method here is the
   scan window, step and baseline choice for one assay; `methods/_shared/uvvis-a280-scan.yaml` is the
   example.
3. Make sure the sample is in place: a cuvette in the Cary 60, or the ATR crystal cleaned and loaded on
   the Cary 630. The package cannot check this.
4. Invoke `scan` with the method (`actions/invoke {method: {name, project}}`) or explicit params; a person
   confirms the call. Poll the job: a 100 nm UV-Vis scan with baseline takes about a minute, an FTIR scan
   about 45 s, plus however long the helper takes to pick the request up.
5. Read the result: exported file, number of points, maximum absorbance and, for UV-Vis, its wavelength.
   The full spectrum stays in the CSV; read it from `file`.

## What to watch

- A job that fails with "no export ... within result_wait_s" left its request in the watched folder on
  purpose: a person can see what was asked. Clear it or run it by hand, then retry.
- `queue_depth` above zero while nothing is busy means stale requests from an earlier session.
- Absorbance above about 2.5 (Cary 60) or a flat line at the FTIR's resolution limit means the sample,
  not the scan, needs attention.
- The lamp, the sample compartment cover interlock and the instrument's own stop belong to the vendor
  software; an e-stop here only withdraws requests not yet taken.

## Resources

- `references/setup.md`: the helper, the two folders, config.json, Windows, first hardware test.
- `references/file_formats.md`: the request file this package writes, the ADL sketch, and the CSV export
  formats it reads, with what is verified and what is not.
- `config.example.json`: request and results folders, software version, timeouts.
