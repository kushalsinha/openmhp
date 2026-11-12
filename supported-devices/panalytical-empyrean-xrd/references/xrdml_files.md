# Data Collector job files, `.xrdml` results and `.xrdmp` programs

What the package writes and reads, with the source for each detail. "unverified" means it was
not read in a Malvern Panalytical document; the first hardware test checks it.

Sources read:

- Malvern Panalytical, "Data Collector" product page (malvernpanalytical.com/en/products/
  category/software/x-ray-diffraction-software/data-collector): measurement programs are stored
  as XRDMP files, batch programming, the Automatic Processing Program (APP, a post-measurement
  command hook), the Operator Interface option, downloads "XRDML schema 2.4 and all previous
  versions" and "XRDMP schema 2.2 and all previous versions"; Windows 8.1/10 64-bit. The Data
  Collector brochure (data_collector_brochure_tcm57-52031.pdf) for the same.
- Malvern Panalytical, Empyrean brochure PN260408-530: 4 kW generator (60 kV, 100 mA max),
  goniometer -111 < 2theta < 168 deg, smallest addressable increment 0.0001 deg. Aeris Research
  edition page: -4 < 2theta <= 142 deg, smallest increment 0.001 deg, 600 W tube (40 kV). Aeris
  Metals edition page: belt and robot integration, 6- and 67-position changers, LIMS protocols.
- Malvern Panalytical, "Universal Automation Interface" page (TCP/IP, a semantic protocol for host
  integration) and "Industry" software page (remote control via an automation network with a
  file-transfer protocol): no protocol details are published.
- The XRDML schemas 1.0, 1.5 (XRDMeasurement15.xsd, 05/03/2010) and 2.1 (XRDMeasurement21.xsd,
  30/08/2018) as bundled by open-source readers (xrdtools, FAIRmat data-modeling), and real files
  from an Empyrean (schema 1.5, Data Collector 4.0a; xylib samples/empyrean.xrdml), an Empyrean
  (2.0, Data Collector 6.0a; datalab example data), an X'Pert (2.1, Data Collector 6.1) and an
  Aeris (2.1, Data Collector 6.1a; 2.2, Aeris Instrument Suite 1.4b).
- Open-source readers: xrayutilities `panalytical_xml.py` (intensities then counts, divides by
  counting time, skips Aborted scans), GSAS-II `G2pwd_Panalytical.py` (namespace from the root
  tag), FAIRmat readers-xrd, xylib `xrdml.cpp`, xrdtools.
- A real `.xrdmp` from an Aeris (2023): root `MProg:measurementProgramFile` in the
  `http://www.Panalytical.com/MeasurementProgram/1.4` namespace with a scan range, mode, time per
  step and an enveloped XML signature (RSA-SHA1).

## The job file (written to `job_dir/<token>.xml`) -- unverified as a whole

Data Collector publishes no job or batch import format, so this package writes its own small XML
and the lab maps it (Operator Interface job, batch script, UAI client). The elements:

```
<MeasurementJob Id="mhp_<date>_<job>" Source="openmhp">
  <SampleId>batch12_formA</SampleId>
  <Position>2</Position>                       empty when the holder on the stage is measured
  <ProgramFile>Powder_5_80.xrdmp</ProgramFile>  optional .xrdmp in Data Collector's program folder
  <ResultFile>batch12_formA_mhp_<date>_<job>.xrdml</ResultFile>
  <Scan ScanAxis="Gonio" Mode="Continuous">
    <StartPosition axis="2Theta" unit="deg">5.0000</StartPosition>
    <EndPosition axis="2Theta" unit="deg">60.0000</EndPosition>
    <StepSize unit="deg">0.0260</StepSize>
    <CommonCountingTime unit="seconds">50.000</CommonCountingTime>
  </Scan>
</MeasurementJob>
```

The attribute and element names follow the XRDML vocabulary (ScanAxis, Mode, 2Theta positions,
commonCountingTime) so the mapping is obvious, but the file is not an XRDMP: writing a signed
`.xrdmp` is not attempted, because whether Data Collector accepts an externally written,
unsigned program is unverified. The package treats the file's disappearance as "taken" and
`ResultFile` appearing in `results_dir` as "measured".

## The `.xrdml` result (read from `results_dir/<ResultFile>`)

| detail | status |
|---|---|
| namespace `http://www.xrdml.com/XRDMeasurement/<version>`, root `xrdMeasurements` with `status` | verified (XSDs 1.0, 1.5, 2.1; files 1.3 to 2.2); the reader takes the namespace from the root tag |
| `xrdMeasurement` attributes `measurementType`, `status`; `sample/id`, `sample/name` | verified (XSDs); `sample` absent in one 1.3 file, so it is optional here |
| `scan` attributes `appendNumber`, `mode` (Continuous, Pre-set time, Pre-set counts), `scanAxis` (Gonio, 2Theta, 2Theta-Omega, Omega, ...), `status` (Completed, Aborted, Not finished) | verified (XSDs) |
| `dataPoints/positions axis="2Theta" unit="deg"` with `startPosition`/`endPosition` or `listPositions`; `commonCountingTime unit="seconds"` or per-point `countingTimes` | verified (XSDs and files); `listPositions` is read but no public file uses it (xylib marks it untested) |
| `intensities unit="counts"` in schema 1.x, `counts unit="counts"` in 2.x; whitespace-separated | verified (XSDs 1.5 and 2.1; 138 public 1.5 files use intensities, 2.x files use counts); the reader accepts both |
| `usedWavelength` kAlpha1 1.5405980 A for Cu; `incidentBeamPath/xRayTube` tension (kV), current (mA), anodeMaterial | verified in every public file; not reported in the result |
| multi-scan files (Repeated scan, maps) | the reader takes the first scan only |

Points are reported as counts, not normalised by counting time (xrayutilities divides; HighScore
reads the raw file).

## The `.xrdmp` measurement program

A signed XML (MeasurementProgram 1.4 namespace) with metadata, a `singleScanType` program (mode,
time per step, scan range start/end in deg, steps, axis) and hardware settings. The package only
names one in the job file; it never writes or reads a program.

## The twin

The twin writes `<ResultFile>` as an XRDML 2.1 file (sample, usedWavelength, xRayTube 40 kV
15 mA Cu, one scan with 2Theta and Omega start/end positions, commonCountingTime, counts) after a
scaled wait of 60 s plus points x time per step; the job file is removed 3 s (scaled) after it was
written. The pattern is nine Gaussian peaks on a falling background with Poisson-like noise.
