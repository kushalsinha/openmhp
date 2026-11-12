# SmartLab Studio II job files, `.ras` and `.rasx` result files

What the package writes and reads, with the source for each detail. "unverified" means it was
not read in a Rigaku document; the first hardware test checks it.

Sources read:

- Rigaku, "SmartLab Studio II" product page and brochures (EN brochure CED434A/170810E; JA
  brochure BDSLS20_JAJPA1, which carries the operating-environment table: Windows 10/11 Pro
  64-bit, SQL Server, CodeMeter dongle): flows and Package Parts, the "new data format (RASX)
  for XML", CSV output as a paid option. No file format is published there.
- Rigaku, "LabLinc Studio" and "Rigaku Automation Interface" pages (rigaku.com/products/lablinc-
  studio, .../rai): RAI is a TCP/IP client-server layer with a Python API and "CSV-based
  scripting for recipe-style measurement"; no protocol, port, column layout or document number
  is published.
- Rigaku, MiniFlex brochure BR_23_MiniFlex_Rev0723: 40 kV / 15 mA, scanning range -3 to 145 deg
  (theta-2theta), scanning speed 0.01 to 100 deg/min, minimum step width 0.005 deg, ASC-8
  changer, controlled by SmartLab Studio II. SmartLab SE brochure BR_23 (ASC-6/-10/-48 changers,
  minimum step 0.0001 deg); SmartLab brochure BR_25 (3 kW sealed tube 20-60 kV / 2-50 mA, 9 kW
  rotating anode 20-45 kV / 10-200 mA).
- A public Studio II `.ras` export (NIMS M-DaC_XRD repository, `XRD_RIGAKU.ras`, 2017) and a
  public `.rasx` (FAIRmat readers-xrd test data, SmartLab XE, 2021), read directly.
- Open-source readers: xrayutilities `rigaku_ras.py`, GSAS-II `G2pwd_rigaku.py`, reductus
  `reflred/rigaku.py`, openreadout `docs/formats/xrd.md`, rietx `rasx.py`, the rigakuXRD R
  package: block markers, `*KEY "value"` lines, the three-column rows, the zip members and the
  vendor's `MesurementConditions0.xml` spelling.

## The job file (written to `job_dir/<token>.csv`) -- unverified as a whole

Studio II publishes no job import format, so this package writes its own small CSV (one header
row, one scan row, CRLF) and the lab maps it (flow template, Package Part, or an RAI client).
The columns, in order:

| column | example | meaning |
|---|---|---|
| job_id | mhp_20261111_a1b2c3 | the token; also in the result file name |
| sample_id | batch12_formA | sample name written to the measurement |
| position | 2 | ASC changer position; empty for the holder on the stage |
| axis | TwoThetaTheta | Studio II internal axis name (TwoThetaTheta, TwoTheta, TwoThetaOmega) |
| mode | CONTINUOUS | CONTINUOUS or STEP (the STEP spelling is unverified; CONTINUOUS is what every public file carries) |
| start, stop, step | 5.0000, 60.0000, 0.0200 | 2theta in deg |
| speed_deg_min | 10.0000 | scan speed in deg/min (Studio II's unit) |
| result_file | batch12_formA_mhp_..._.rasx | the file name the flow saves the measurement as |

The package treats the file's disappearance as "taken" and `result_file` (or its `.ras` twin)
appearing in `results_dir` as "measured".

## The `.ras` text file (read from `results_dir/<name>.ras`)

ASCII with CRLF line ends in every public file (Japanese installations may write Shift-JIS
sample names; the reader decodes UTF-8 and falls back to latin-1). Layout, verified against the
NIMS file and four readers:

```
*RAS_DATA_START
*RAS_HEADER_START
*DISP_LINE_COLOR "0"
*FILE_SAMPLE "Test Sample"
*HW_XG_TARGET_NAME "Cu"
*MEAS_COND_XG_CURRENT "30"
*MEAS_COND_XG_VOLTAGE "40"
*MEAS_DATA_COUNT "3501"
*MEAS_SCAN_AXIS_X "TwoThetaTheta"
*MEAS_SCAN_MODE "CONTINUOUS"
*MEAS_SCAN_SPEED "8.0000"
*MEAS_SCAN_SPEED_UNIT "deg/min"
*MEAS_SCAN_START "25.0000"
*MEAS_SCAN_STEP "0.0100"
*MEAS_SCAN_STOP "60.0000"
*RAS_HEADER_END
*RAS_INT_START
25.0000 13.0000 1.0000
...
*RAS_INT_END
*RAS_DATA_END
```

| detail | status |
|---|---|
| `*RAS_DATA_START` wrapper, `*RAS_HEADER_START/END` and `*RAS_INT_START/END` per scan | verified (NIMS file; GSAS-II and reductus require line 1 == `*RAS_DATA_START`) |
| header lines `*KEY "value"`, indexed keys `*MEAS_COND_AXIS_NAME-3` | verified (xrayutilities strips the quotes) |
| rows `angle intensity attenuation`, row count = `*MEAS_DATA_COUNT` | verified; the third column is constant 1.0 in every public file and its meaning (attenuator factor) is the readers' inference, so the package reports the raw intensity |
| keys read here: `*FILE_SAMPLE`, `*HW_XG_TARGET_NAME`, `*MEAS_COND_XG_VOLTAGE` (kV), `*MEAS_COND_XG_CURRENT` (mA), `*MEAS_SCAN_SPEED` (deg/min), `*MEAS_SCAN_START/STOP/STEP`, `*MEAS_SCAN_MODE`, `*MEAS_SCAN_AXIS_X` | verified in the NIMS file |
| multi-scan files repeat HEADER+INT blocks | verified (GSAS-II counts banks); the package reads the first scan only |

## The `.rasx` zip (read from `results_dir/<name>.rasx`)

A plain zip. Members verified in the FAIRmat file: `root.xml` (UTF-8 BOM, `<Root Version="1.1.0.0">`
with content hashes and an XML signature), `Data0/Profile0.txt` (UTF-8 BOM, CRLF, tab-separated
`angle<TAB>intensity<TAB>attenuation`, no header, intensity may be non-integer) and
`Data0/MesurementConditions0.xml` (the vendor's spelling, UTF-8 BOM) whose `ScanInformation`
(AxisName, Mode, Start, Stop, Step, Speed, SpeedUnit, DataCount), `HWConfigurations/XrayGenerator`
(TargetName, Voltage, Current, WavelengthKalpha1) and `GeneralInformation/SampleName` hold the scan,
and whose `RASHeader` repeats the legacy `*KEY` pairs. Multi-scan files use `DataN/ProfileN.txt`.
The package opens `Profile0.txt`, reads the XML's `RASHeader` pairs, then fills any missing key from
`ScanInformation` and `XrayGenerator`. The signature is not checked.

## The twin

The twin writes both `<result_file>.ras` and `.rasx` (root.xml, Profile0.txt, the conditions XML
with the vendor spelling, RASHeader pairs) after a scaled wait of 90 s plus (stop - start) / speed
minutes; the job file is removed 3 s (scaled) after it was written. The pattern is nine Gaussian
peaks on a falling background with Poisson-like noise, tube Cu 40 kV 30 mA.
