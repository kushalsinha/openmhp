# TRIOS run lists and text exports

What the package writes and reads, with the source for each detail. "unverified" means it was
not read in a TA Instruments document; the first hardware test checks it.

Sources read:

- TA Instruments application notes TB106 / TB107 / TB109 "TRIOS Software and JSON Export"
  (tainstruments.com): TRIOS exports plain text (ASCII), CSV, Excel and, from TRIOS 5.8, JSON;
  the DSC column labels used there are "Temperature / °C" and "Heat Flow (Normalized) / W/g"
  (JSON form; the text export carries the unit on its own row).
- hermes-rheo `trios_rheo_txt.py` (3M, open source) and RheoJAX "TA Instruments TRIOS Format"
  (readthedocs): the "Export to LIMS" text file has header lines `Filename`, `Instrument serial
  number`, `Instrument name`, `operator`, `rundate`, `Sample name`, optional `[Geometry
  Parameters]` and similar sections, then `[step]` blocks, each with `Step name`, a
  tab-separated column-name row, a units row and tab-separated data rows (`Number of points`
  and a "Data point" prefix appear in RheoJAX's example but not in hermes-rheo's reader, so
  the package accepts rows with or without them: a row is data when its cells are numbers).
  Both readers are for rheometers; the DSC/TGA export shares the mechanism (same TRIOS
  export dialog) but its column names here are an assumption (`Time`, `Temperature`,
  `Heat Flow (Normalized)`; `Weight`, `Weight (%)`), which is why the parser finds columns by
  the words "temperature", "heat flow" and "weight" rather than exact names.
- TA Instruments Discovery DSC practical training and university SOPs (TRIOS 5): the
  procedure editor's segment wording "Ramp 10.00 °C/min to 300.00 °C", "Isothermal for 5.00
  min", the autoloader (pan robot) rack positions, standby at 25 degC.

## The run list (written to `run_dir/<token>.csv`) -- unverified as a whole

TA publishes no run-list import format for TRIOS Auto / the autoloader run queue (the brief
notes `.tri` or CSV run lists; nothing documenting their columns was found). The package writes
a comma-separated file, CRLF, with a header row and one row:

| column | value |
|---|---|
| Sample Name | as given |
| Instrument | DSC or TGA |
| Pan Position | rack position, empty for a pan already in the cell |
| Sample Mass (mg) | three decimals |
| Procedure | segments joined with `; ` in TRIOS' wording, e.g. `Ramp 10.00 °C/min to 300.00 °C; Isothermal for 5.00 min` |
| Data File | `<token>.tri` |
| Export File | `<token>.txt`, the name the package waits for in `export_dir` |

The lab's TRIOS administrator maps these columns to the installed import (or a person imports
them). The file's disappearance is read as "TRIOS has the run"; the export's appearance as
"finished".

## The text export (read from `export_dir/<token>.txt`)

Tab-separated. Header lines are `key<TAB>value` until the first `[step]`; inside a step the
first non-numeric row is the column names, the next non-numeric row the units, every row whose
cells are all numbers is data. Several `[step]` blocks are concatenated. Columns are found by
word: Temperature (any column containing "temperature"), the DSC signal (containing "heat
flow"; the normalised one when both exist), the TGA signal (containing "weight", preferring
"weight (%)").

| detail | status |
|---|---|
| header lines `Filename`, `Instrument name`, `operator`, `rundate`, `Sample name` | verified for the rheometer LIMS export (hermes-rheo, RheoJAX) |
| `[step]`, column row, units row, tab-separated data | verified for the rheometer export; assumed identical for DSC/TGA |
| DSC/TGA column names | unverified (TB107 gives "Temperature", "Heat Flow (Normalized)" in the JSON form) |
| encoding UTF-8 with `°C` | assumed; the parser reads with replacement so a cp1252 degree sign does not break it |

## The onset, peak and mass loss estimates

Documented as estimates; TRIOS' own analysis is the reportable one.

- Baseline: least-squares line through the first tenth of the points (temperature vs signal).
- Peak (DSC): the temperature of the largest deviation from that baseline.
- Onset: the tangent at the steepest point of the leading edge (between the baseline region
  and the peak) extrapolated to the baseline, the usual "extrapolated onset" construction, with
  the leading edge found numerically.
- TGA: mass loss = 100 x (mean of the first tenth - mean of the last tenth) / first tenth, on
  the weight column; onset by the same tangent construction on the weight curve; peak = the
  temperature of the fastest loss (the DTG peak).
- Null when fewer than 20 rows, no recognisable columns, or no deviation from the baseline.

## The twin

The twin reads the run list 2 s (scaled) after it is written, keeps `live.txt` updated with
the programmed temperature while the run "runs", and after 300 s plus the program's duration
(scaled) writes the export with the header lines, `[step]`, `Step name`, columns, units and
rows. DSC: a melting endotherm at 168 degC (4 degC wide) on a sloping baseline, normalised
heat flow in W/g. TGA: a 42 % single-step loss centred at 310 degC, weight in mg and %.
