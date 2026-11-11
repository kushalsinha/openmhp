# Files this package writes and reads

## Sources

- *Maurice User Manual* (ProteinSimple; manualmachine.com copy of the Maurice/Maurice S/Maurice C
  manual) as summarised in search results: the Injection Report exports raw and analysed data, the
  pI/MW plot, the peaks table and sample/system information as PDF; *Export Spectra* exports the
  raw and analysed traces per injection as `.txt` or `.cdf`; the Peaks pane tabulates results for
  sample proteins and pI markers; the Injections pane is the per-injection view.
- Bio-Techne application note *Chromeleon software for Maurice*: data analysed in Compass for iCE
  can be exported to ChromPerfect, Chromeleon or Empower.
- Bio-Techne poster *iCE3 21 CFR Part 11* (WCBP 2013): the ANDI (`.cdf`) format carries the data
  trace to third-party chromatography software; batch tables are created in the software.
- *Compass for iCE User Guide* (Bio-Techne, resources.bio-techne.com): could not be fetched while
  writing this package. Everything marked **unverified** below is what a lab must confirm from it.

## Batch file (written by this package): `import_dir/mhp_<job>.csv`

```
Sample,Position,Method,Injection
mAb-7 lot 23 charge variants mhp_job_1a2b3c4d,A1,cIEF_mAb_pH3-10,1
mAb-7 lot 23 charge variants mhp_job_1a2b3c4d,A1,cIEF_mAb_pH3-10,2
```

One row per injection; the job token is part of the sample name so the export can be matched
without relying on file names or "newest file". **unverified**: whether a given Compass version
imports such a table directly and which column headers it expects. If it does not, the file is the
note a person builds the batch from. Written as `.part` and renamed; the helper deletes it after
import; `queue_depth` counts the ones left. The run file Compass saves (`.mbz`, proprietary,
**unverified** extension) is not read.

## Peak-table export (read by this package): `results_dir/*mhp_<job>*.csv`

Assumed layout (**unverified** header spellings; the parser matches loosely):

```
Sample Name,Injection,Peak Name,pI,Area,% Area
mAb-7 lot 23 charge variants mhp_job_1a2b3c4d,1,Acidic 1,8.42,21034,11.4
mAb-7 lot 23 charge variants mhp_job_1a2b3c4d,1,Main,8.71,112901,61.2
```

- sample column: `Sample Name`, `Sample` or `Name`; rows whose sample lacks the token are ignored.
- position column: `pI` (cIEF) or `Apparent MW (kDa)` / `Apparent MW` / `MW (kDa)` (CE-SDS).
- area: `Area`, `Peak Area` or `Corrected Area`; percent: `% Area`, `%Area`, `Area %`,
  `Percent Area` or `% Corrected Area`.
- label: `Peak Name`, `Label` or `Peak`; `main_peak_pct` takes the row labelled Main, Main peak,
  Monomer or Intact, else the largest `% Area`.
- Tab-separated exports are accepted too.

## Status file (optional, written by the lab): `results_dir/status.json`

`{"cartridge": true}` makes `cartridge_present` answer true/false; without it the signal is null.
Compass itself writes no such file.

## Twin

The twin's fake Compass PC imports the batch after 5 min plus 10 min per cIEF injection (35 min
per CE-SDS injection, chosen when the method name contains "sds"), scaled by
`OPENMHP_SIM_TIME_SCALE`, and writes `mhp_<job>_peaks.csv` in the layout above with a four-peak
charge-variant profile (Main about 62 %) or a reduced CE-SDS profile (LC, HC, Main, HMW).
