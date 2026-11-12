# RheoCompass job files and ASCII exports

What the package writes and reads, with the source for each detail. "unverified" means it was
not read in an Anton Paar document; the first hardware test checks it.

Sources read:

- Anton Paar, "Rheometer Software: RheoCompass" product page (part no. 315624): Test Analysis
  Designer workflows with drag-and-drop actions, Report Designer, barcode fields, a central or
  remote SQL database, export "to PDF, XML, ASCII" "to automatically exchange data with a LIMS";
  system requirements Windows 10/11. No automation API, OPC, COM, command line or external start
  is documented. Application report "Migration of Rheoplus Measurement Templates to RheoCompass":
  data are no longer file-based but in a Microsoft SQL database; "project templates".
- Anton Paar, "AP Connect" (lab execution system: REST API, task lists that start measurements on
  "selected instruments", Windows 10/11, SQL Server) and the application report "Automate your
  measurements with the AP Connect tasklist": whether MCR rheometers are task-list instruments
  is not stated.
- Anton Paar, MCR Evolution brochure C92IP001EN-O (2022): MCR 102e/302e/502e/702e torque 5/1/
  100/1 nNm to 200/230/300/230 mNm, max speed 314 rad/s (3000 rpm), max frequency 100 Hz, normal
  force -50 to 50 N (502e Power -70 to 70 N), Toolmaster, T-Ready, TruGap, SafeGap (a force
  limiter during gap setting), P-PTD 220 / H-PTD 220 hood -50 to 220 degC, C-PTD 200, CTD 450/600
  ovens; the "Peltier Systems" page: plate Peltier -50 to 220 degC, an optional actively heated
  hood; "Convection Temperature Devices" page: CTD 180/450/600/1000. The former MCR 72/92
  accessory listing (H-PTD 200 -40 to 200 degC, P-PTD 200/AIR -10 to 200 degC) was seen only in
  search snippets.
- Open-source readers of real RheoCompass exports: the `rheojax` anton_paar reader (UTF-16 with
  BOM, tab-separated, `key:<TAB>value` metadata lines, `Interval and data points:<TAB>n[<TAB>count]`,
  the `Interval data:` column header, units as `Name [unit]` or on a bracketed line beneath, empty
  and `n.a.` cells, a locale-dependent decimal separator; columns Time, Angular Frequency,
  Frequency, Shear Stress, Shear Strain, Shear Rate, Storage Modulus, Loss Modulus, Viscosity,
  Complex Viscosity, Phase Angle, Temperature, Normal Force, Torque) and an R loader for an older
  layout (`Name:`, `Measuring Date/Time:`, `Number of Data Points:`, `Meas. Pts.` header, `Data
  Series Information` separator, decimal commas). A vendor sample of the export was not found.
- A university quick-start guide for an MCR 302e (export by right-clicking the table, "export to
  CSV"), an MCR 702e SOP (start from the start action block, enter the sample name) and the
  Physica MCR xx1 manual C22ib50-e (main switch, head moves with high force, no e-stop button).

## The job file (written to `job_dir/<token>.csv`) -- unverified as a whole

RheoCompass publishes no import format, so this package writes its own small CSV (one header row,
one test row, CRLF) and the lab maps it. The columns, in order:

| column | example | meaning |
|---|---|---|
| job_id | mhp_20261111_a1b2c3 | the token; also in the export file name |
| sample_name | batch12_gel | sample name written to the test |
| test_type | flow_curve | flow_curve (CSR ramp) or frequency_sweep (oscillation at constant strain) |
| measuring_system | CP50-1 | the geometry RheoCompass expects Toolmaster to see |
| temperature_c | 25.0 | temperature device setpoint |
| shear_rate_start, shear_rate_end | 0.1, 1000 | flow curve, 1/s (empty for a sweep) |
| strain_pct, frequency_start_hz, frequency_end_hz | 1, 0.1, 100 | frequency sweep (empty for a flow curve) |
| points | 21 | measuring points |
| point_duration_s | 10 | per point (flow curve); the sweep's point duration is RheoCompass's own |
| log | true | logarithmic spacing (flow curve) |
| result_file | batch12_gel_mhp_..._.txt | the export file name the workflow writes |

The package treats the file's disappearance as "taken" and `result_file` appearing in
`results_dir` as "measured".

## The ASCII export (read from `results_dir/<result_file>`)

| detail | status |
|---|---|
| UTF-16 with BOM (UTF-8 and latin-1 are also decoded) | from the rheojax reader of real files; unverified for every version |
| tab-separated; `key:<TAB>value` metadata lines before the data | same source |
| `Interval and data points:<TAB>n<TAB>count` per interval | same source; the package takes the first interval |
| `Interval data:<TAB>col1<TAB>col2...` header, then a units line `<TAB>[]<TAB>[s]<TAB>[1/s]...` (or units embedded as `Name [unit]`) | same source; both forms are handled |
| decimal comma, `n.a.`, empty cells | same source |
| columns read: Temperature (mean), and at the last point Shear Rate, Shear Stress, Viscosity, Storage Modulus, Loss Modulus, Frequency or Angular Frequency | names as the reader maps them; your version's wording is unverified |

## The live export (`live_export_file`, optional)

The same layout; the last Temperature value is the `temperature` signal. Whether a workflow can
keep writing an export during a test is unverified.

## The hood state file (`hood_state_file`)

A one-line text file reading `closed` or `open`, written by the lab. The MCR does not report the
hood; Anton Paar documents interlocked enclosures only for the HTR robotic cells.

## The twin

The twin removes the job file 3 s (scaled) after it was written, writes a live export whose
Temperature settles toward the setpoint with a 60 s time constant, and after 60 s plus the test
time writes the export in UTF-16 with a decimal comma: a Carreau flow curve (12 Pa.s zero-shear
viscosity, n 0.4) or a weak gel's frequency sweep (G' about 800 Pa, G'' a quarter of it).
