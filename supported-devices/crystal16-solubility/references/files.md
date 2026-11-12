# Crystal16 / CrystalClear files

## Export: "Crystal16 Data Report File, Version: 1014" (documented from real files)

Sources: raw export CSVs published with a polymer solubility dataset
(github.com/mona2442/Polymer-Solubility-Data_Crystal16, `Unprocessed_Data/data/*.csv`) and the parser in
github.com/Ramprasad-Group/csst_analyzer (`csst/experiment/__init__.py`); onset detection in
github.com/CatSci/Crystal16-Processing. Technobis product page (crystallizationsystems.com/products/crystal16):
"Data export: CSV, Word report, XML"; CrystalClear "Import your project data files ... Visualize and
(optionally) edit Clear and Cloud points ... Meta Stable Zone Width".

Layout (comma separated, UTF-8, one file per block of four reactors):

```
Crystal16 Data Report File,Version: 1014

Experiment details
ExperimentNumber,0
Experimentor,<name>
Project,<name>
Reactor1,<free text, what is in the vial>
Reactor2,...  Reactor3,...  Reactor4,...
Labjournal
Description
<free text>
Start of Experiment,9/15/23 11:27
Temperature Program
Block,A
Heat to,20, at ,20, °C/min
Stir (Bottom) at,900, rpm
Hold at,20, for ,180, sec
Tune
Cool to,10, at ,0.5, °C/min
Data Block
Date Time,Decimal Time [mins],Temperature Setpoint [°C],Temperature Actual [°C],Reactor1 Transmission [%],Reactor2 Transmission [%],Reactor3 Transmission [%],Reactor4 Transmission [%],Stirring Rate [rpm]
9/15/23 11:27,0:00:01,24.6,25,100,100,100,100,0
```

- About one row per second; transmission is an integer percent; "Decimal Time" is `H:MM:SS` (and
  `D.H:MM:SS` after a day); dates are locale formatted.
- The `Stirring Rate` column read 0 in the public files even with `Stir (Bottom) at 900`.
- No clear or cloud point table is in the file: those come from CrystalClear's analysis. This package
  detects them from the trace: clear point = first actual temperature at which transmission reaches 90
  percent on a heating segment; cloud point = first temperature at which it falls below 80 percent on a
  cooling segment; averaged over cycles.

## Program file written by this package (unverified)

```
Crystal16 Temperature Program,<name>
Blocks,ABCD
Temperature Program
Block,A
Stir (Bottom) at,700, rpm
Heat to,60, at ,1, °C/min
Hold at,60, for ,600, sec
Cool to,5, at ,0.5, °C/min
...
```

No import format is published; the step vocabulary is the export's echo. The lines `Crystal16 Temperature
Program` and `Blocks` are this package's, not Technobis's.

## Instrument facts (Technobis product page, 2026)

16 reactors in 4 temperature zones (Peltier and heater); -20 to 150 degC (-25 to 150 in all four blocks in
parallel with the optional chiller); accuracy 0.5 degC; heating and cooling rate 0 to 20 degC/min (this package
bounds it at 0.1 to 20); stirring 0 to 1250 rpm (600 to 800 advised); standard 11.5 mm flat-bottomed 1.5 mL
HPLC vials, 0.5 to 1.0 mL working volume; turbidity probe per reactor.

## Unverified

- The program import format and file extension; whether CrystalClear imports programs at all (its page
  speaks of importing "project data files" for analysis).
- The XML export schema and whether a live log is written during a run (the block temperature signals
  depend on it and read null otherwise).
- Whether one export can hold all 16 reactors (only one-block files were seen).
- The export file naming (this package matches files containing the program name).
- "CrystallineClear" as a product name: Technobis calls the software CrystalClear for both instruments.
