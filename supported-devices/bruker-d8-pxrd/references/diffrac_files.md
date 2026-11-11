# DIFFRAC.SUITE job files, `.brml` raw files and `.xy` exports

What the package writes and reads, with the source for each detail. "unverified" means it was
not read in a Bruker document; the first hardware test checks it.

Sources read:

- Bruker product pages for DIFFRAC.MEASUREMENT CENTER (bruker.com, "DIFFRAC.SUITE software",
  V8.x): the job controller with scheduler and history (jobs can be stopped, deleted, resumed,
  restarted, re-prioritised); JOBLIST and START JOBS plug-ins with job templates for routine
  measurements; scripting support, an automation interface and a LIMS connection; client/server
  design. No file format is published there.
- GSAS-II `G2pwd_BrukerBRML.py` importer (GSAS-II, Argonne, open source) and the GSAS-II mailing
  list threads "Bruker brml files" (2022) and "Bug in BRML file import" (2024): a `.brml` is a
  zip of XML files; the pattern is in a `RawData<n>.xml` member under
  `RawData/DataRoutes/DataRoute/`; `ScanInformation/MeasurementPoints` and
  `TimePerStepEffective`; each `<Datum>` is comma-separated with the 2theta angle at index 2 and
  the counts at index 4 (index 3 in some files), index 0 the time per step; a "no scan"
  variant keeps `ScaleAxes/ScaleAxisInfo/Start,Stop,Increment` and one long `Datum`; the layout
  varies with scan type (continuous, static), and `MeasurementContainer.xml` and other members
  hold metadata.
- PRONOM fmt/1120 (UK National Archives): the Bruker BRML signature (a ZIP container).
- The brief's description of `.bsml` measurement method files and a job queue imported through
  the measurement centre's automation folder; nothing confirming a `.dql` extension was found.

## The job file (written to `job_dir/<token>.xml`) -- unverified as a whole

DIFFRAC.SUITE publishes no job import format, so this package writes its own small XML and the
lab maps it (job template, DIFFRAC.COMMANDER script or LIMS connection). The elements:

```
<MeasurementJob Id="mhp_<date>_<job>" Source="openmhp">
  <SampleId>batch12_formA</SampleId>
  <Position>2</Position>                     empty when the holder on the stage is measured
  <MethodFile>FormScreen_Cu.bsml</MethodFile> optional .bsml in the DIFFRAC method folder
  <ResultFile>batch12_formA_mhp_<date>_<job>.brml</ResultFile>
  <Scan Axis="TwoTheta" Mode="Coupled">
    <Start>3.0000</Start><Stop>40.0000</Stop><Increment>0.0200</Increment><TimePerStep>0.500</TimePerStep>
  </Scan>
</MeasurementJob>
```

The package treats the file's disappearance as "imported" and `<ResultFile>` appearing in
`results_dir` as "measured". A `.bsml` file (a DIFFRAC.SUITE measurement method, XML) carries
optics, generator and detector settings; its content is not written or read here.

## The `.brml` raw file (read from `results_dir/<ResultFile>`)

Zip container. The package opens the first member whose name contains `RawData` and ends with
`.xml` (`Experiment0/RawData0.xml` in the files GSAS-II users describe) and reads every
`<Datum>` element: fields split on commas, 2theta from index 2, counts from index 4 (index 3
when there is no index 4). Points are not normalised by `TimePerStepEffective` (GSAS-II does
that; here the count is what is reported). Elements read: `Datum` only; `MeasurementPoints`,
`ScaleAxisInfo` and the `Identifier` block are not needed for the result.

| detail | status |
|---|---|
| zip container with `RawData<n>.xml` members | verified (GSAS-II, PRONOM) |
| `DataRoutes/DataRoute/Datum` comma-separated, 2theta at index 2, counts at index 4 (or 3) | verified against GSAS-II's reader; the meaning of the other fields (time per step at 0; theta?) is the reader's inference |
| one `RawData` member per scan | assumed (GSAS-II assumes one; files with several need the `.xy`) |
| `ScaleAxisInfo Start/Stop/Increment` and `TimePerStepEffective` | present per GSAS-II; not read here |

## The `.xy` export (read from `xy_dir/<name>.xy`, `.txt` or `.xye`)

Two columns, 2theta and intensity, separated by spaces, tabs, commas or semicolons; lines that
are not two numbers (headers, comments) are skipped. DIFFRAC.EVA and the Result Manager export
such files; the exact header lines they prepend are unverified, which is why every non-numeric
line is ignored. A third column (`.xye` error) is tolerated by the two-number match at line start.

## The twin

The twin writes `<ResultFile>` as a zip holding `Experiment0/RawData0.xml` (Identifier,
MeasurementPoints, TimePerStepEffective, ScaleAxisInfo, one `Datum` per point as
`time,index,2theta,theta,counts`) and `Experiment0/MeasurementContainer.xml`, plus the `.xy`,
after a scaled wait of 60 s plus points x time per step; the job file is removed 3 s (scaled)
after it was written. The pattern is eight Gaussian peaks on a falling background with
Poisson-like noise.
