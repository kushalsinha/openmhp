# Setting up

The package only reads and writes files, so it runs from any Linux, macOS or Windows machine that mounts
two folders on the CrystalClear PC. CrystalClear itself is Windows and is operated by a person.

## What you need

- A Crystal16 with CrystalClear (Technobis) on its PC.
- Two folders on that PC shared to the machine serving this package: one for program files (writable) and
  one that CrystalClear exports data reports into (readable).
- CrystalClear's CSV export (Technobis: "Data export: CSV, Word report, XML") pointed at the export folder,
  with the file named after the program; one CSV per block.

## Install

1. `pip install openmhp`
2. Copy `config.example.json` to `config.json`: `program_dir`, `export_dir`.
3. `mhp serve pkg:<this folder> --http <port>` and read `connected`.

## The program file

No import format is published by Technobis. The file this package writes uses the step vocabulary
CrystalClear echoes into its own exports (`Heat to,60, at ,1, °C/min`, `Cool to`, `Hold at ... sec`,
`Stir (Bottom) at ... rpm`, `Block,A`). On the first hardware test compare it with what CrystalClear's
import expects and adjust `program_lines()` in driver.py; if the software cannot import at all, a person
types the program in from the file, which is short.

## First hardware test

1. Read `connected`.
2. Invoke `run_program` with the example on four vials of a known solubility system (for example
   paracetamol in water at 5, 10, 20 and 40 mg/mL in block A, `blocks: [A]`).
3. Import or type the program in CrystalClear and start it. Watch the job's phase.
4. When the run ends, export the data report CSV into the export folder with the program's name.
5. Compare the job's clear and cloud points with CrystalClear's own analysis; adjust `CLEAR_PCT` and
   `CLOUD_PCT` in driver.py if your probes read differently.

## Status

twin tested. The export layout is from real files (Version 1014); the program file format is unverified;
not yet run against a Crystal16.
