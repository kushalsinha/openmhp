# Files this package writes and reads

## Sources

- *Cary WinUV Software manual*, Varian publication 85 101625 00 (May 1999; the current Agilent
  edition has the same chapters): section 3.1.1 "ADL Shell" (ADL, the Applications Development
  Language, "a built-in spectroscopy language supplied with the WinUV software"), the Scan
  application's Auto Store options ("ASCII (csv)" and "ASCII (csv) with Log": at the end of a
  collection the data is stored both in the Cary format and as ASCII XY pairs), and File > Save
  Data As.
- Agilent community threads "Adding values to .CSV file output by Cary UV-vis software" and
  "cary adl function fconvert not working" (ADL `Save Data As` handles only data; `FConvert` is
  documented in the ADL Help under Continuum commands); "adl shell cary 50 uv vis" (Agilent: ADL
  help is in the software's Help; ADL scripts are not supported for the obsolete Cary 50).
- Agilent Cary 630 FTIR user guide (G8043-97001) and MicroLab FTIR software overview: results can
  be exported to a spreadsheet or other file type; "Previous results" holds saved results.
- Repligen/C Technologies KB19004 (2019): ADL Shell is "scripting language designed to manipulate
  the Cary WinUV environment"; batch data files have vendor-specific extensions (.BVP for SoloVPE).

Nothing above documents a command-line interface for the Scan application, nor an ADL command
reference. Everything marked **unverified** below is an assumption the lab must check.

## Request file (written by this package): `import_dir/mhp_<job>.json`

```json
{"token": "mhp_job_1a2b3c4d", "software": "Cary WinUV", "sample_name": "mAb lot 12 A280",
 "mode": "uvvis", "start": 240, "stop": 340, "step": 1, "baseline": true,
 "export": "mhp_job_1a2b3c4d.csv", "written": 1760000000.0}
```

Written as `mhp_<job>.part` and renamed, so the helper never reads a half-written file. `software`
is `Cary WinUV` for `uvvis` and `MicroLab` for `ftir`. `step` is the data interval in nm (uvvis) or
the resolution in /cm (ftir). The helper (or person) deletes the request once it has acted on it;
`queue_depth` counts the ones still there. An e-stop deletes them.

## ADL sketch (optional, `write_adl: true`): `import_dir/mhp_<job>.adl`

Three comment lines naming the window, interval, baseline choice and the export name. It contains
no executable ADL statements because none could be verified from a public source: the ADL command
set (wavelength range, data interval, baseline collection, `Save Data As` with the ASCII (csv)
type, `FConvert`) is documented only in the ADL Help inside Cary WinUV. **unverified**: a lab
that writes the helper fills the statements in from that Help.

## Cary WinUV ASCII (csv) export (read by this package): `results_dir/*mhp_<job>*.csv`

What the manual guarantees: an "ASCII XY pairs" file. What this package assumes (**unverified**
until the first hardware test):

```
mAb lot 12 A280 (mhp_job_1a2b3c4d)
Wavelength (nm),Abs
240.00,1.2345
241.00,1.2201
...
```

The parser ignores any number of title lines, takes the first non-numeric two-cell line as the
column header (x unit from `nm` or `cm`, y label as given, default `Abs`), and reads every line
whose first two cells are numbers. A file with several spectra side by side (WinUV can put each
sample in its own column pair) is read as its first pair only: export one sample per file.

## MicroLab CSV export (read by this package)

Assumed two columns, `Wavenumber (cm-1),Absorbance`, wavenumbers descending from 4000 to 650 at
the method's resolution. **unverified**: MicroLab's exact header text and whether it writes
absorbance or transmittance is set by the method's result options.

## Twin

The twin's fake instrument PC consumes the request after a scaled scan time (about 20 s plus 0.1 s
per nm for UV-Vis, doubled with a baseline; 45 s for FTIR) and writes the CSV in the layout above
with a protein-like UV spectrum (peaks at 225 and 280 nm) or an amide-like IR spectrum.
