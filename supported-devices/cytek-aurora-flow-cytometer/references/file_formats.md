# Files this package writes and reads

## Sources

- *Aurora User's Guide*, Cytek Biosciences, document 52-70001-0C (January 2019): "SpectroFlo
  software saves flow cytometry data in the FCS 3.1 format", raw and unmixed; FCS files are
  stored in the Export folder by default (Storage Preferences); an experiment can be exported as
  a ZIP with its FCS files and imported into another SpectroFlo; stopping rule "number of events
  to record, stopping time (in seconds), or stopping volume (in uL)", acquisition stops at the
  first criterion met, set at experiment, group or tube level; Flow Rate Low (15 uL/min), Medium
  (30 uL/min), High (60 uL/min); statistics boxes on a worksheet can be exported as a CSV file
  (appended or overwritten); QC reports are exported as CSV to the Setup folder
  (`C:\CytekbioExport\Setup`); sheath indicators yellow (about 5 minutes left) and red (empty);
  the plate loader takes 96-well plates and a 40-tube rack with Loader settings (default, high
  throughput, low carryover) and an acquisition order.
- *Data File Standard for Flow Cytometry, Version FCS 3.1, Normative Reference* (ISAC; Spidlen
  et al., Cytometry A 77:97-100, 2010): sections 3.1 (HEADER), 3.2 (TEXT), 3.3 (DATA), 3.5 (CRC).
- Core-facility SOPs (URMC, UNC, Pittsburgh, Tübingen) for SpectroFlo: experiment import takes
  only SpectroFlo's zipped experiment; worksheets and templates are imported from exports.

Nothing above documents a worklist or sample-list import (CSV) into SpectroFlo, nor an automation
interface. The worklist this package writes is therefore the note a helper or person acts on,
**unverified** as anything SpectroFlo itself reads.

## Worklist (written by this package): `import_dir/mhp_<job>.csv`

```
Position,Sample Name,Template,Stop Events,Stop Time (s),Flow Rate,Export
A1,lot 42 viability mhp_job_1a2b3c4d,Viability_7AAD,10000,,Medium,mhp_job_1a2b3c4d.fcs
```

Written as `.part` and renamed; the helper deletes it once the sample is acquired; `queue_depth`
counts the ones left; an e-stop deletes them. `Flow Rate` is SpectroFlo's word (Low/Medium/High).

## FCS 3.1 file (read by this package): `results_dir/*mhp_<job>*.fcs`

What the reader uses, from the normative reference:

| Bytes | Content |
|---|---|
| 0-5 | `FCS3.1` (no space) |
| 6-9 | four spaces |
| 10-17, 18-25 | ASCII offsets, right-justified in 8 bytes, of the first and last byte of the primary TEXT segment |
| 26-33, 34-41 | the same for the DATA segment (0 when the segment lies beyond byte 99,999,999: then `$BEGINDATA`/`$ENDDATA` in TEXT hold the offsets) |
| 42-49, 50-57 | the same for the ANALYSIS segment (0 or blank when absent) |

The primary TEXT segment starts with its delimiter character (any ASCII 1-126; `/` in the
examples) and holds `/keyword/value/` pairs; a delimiter inside a value is doubled; empty values
are not allowed. Required keywords (section 3.2.18): `$BEGINANALYSIS`, `$BEGINDATA`,
`$BEGINSTEXT`, `$BYTEORD` (`1,2,3,4` little-endian or `4,3,2,1` big-endian), `$DATATYPE` (`I`
integer, `F` single float, `D` double, `A` ASCII), `$ENDANALYSIS`, `$ENDDATA`, `$ENDSTEXT`,
`$MODE` (`L` list mode; `C` and `U` deprecated), `$NEXTDATA` (0 for the only data set), `$PAR`,
`$TOT`, and per parameter `$PnB` (bits; always 32 for `F`), `$PnE` (`0,0` for float data), `$PnN`
(unique short name, no comma), `$PnR` (range). The 8 bytes after the last segment hold the CRC as
ASCII or eight spaces when none is stored.

The reader takes `$TOT`, `$PAR` and `$P1N..$PnN`, and for `$DATATYPE/F/` checks that the DATA
segment is `$TOT x $PAR x 4` bytes long and that the file reaches the declared DATA end, so an
export still being written fails the job as incomplete rather than reporting a short count. SpectroFlo's own extra keywords (`$CYT`, `$FIL`,
`TUBENAME`, channel names such as `V1-A`, `B2-A`) are passed through in `channels` only.

## Statistics CSV (optional, read for its path only): `results_dir/*mhp_<job>*.csv`

The worksheet statistics box exported as CSV: population name, events, % parent, and the
statistics chosen (median per channel, ...). **unverified** column headers; the package reports
the file's path and leaves the table to the caller.

## Status file (optional, written by the lab): `results_dir/status.json`

`{"sheath_ok": true}` makes `sheath_level_ok` answer true/false; without it the signal is null.
SpectroFlo writes no such file.

## Twin

The twin's fake acquisition PC takes 25 s of setup plus the time to reach the stopping rule at
800/1600/3200 events per second for low/medium/high flow (scaled by `OPENMHP_SIM_TIME_SCALE`;
events capped at 100,000 in the twin), then writes `mhp_<job>.fcs` exactly as above: a 58-byte
HEADER, a `/`-delimited TEXT segment with every required keyword, little-endian float32 DATA for
ten channels (Time, FSC-A, FSC-H, SSC-A, SSC-B-A, V1-A, V3-A, B2-A, YG1-A, R1-A) and eight spaces
in place of the CRC, plus `mhp_<job>_stats.csv` with All Events and Live rows.
