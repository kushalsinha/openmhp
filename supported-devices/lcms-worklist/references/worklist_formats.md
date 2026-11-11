# The four import formats

What the package writes, column by column, and where each detail comes from. "verified" means
a vendor document says so; "unverified" means it is reconstructed from open-source generators or
is this package's own assumption, and the first import on a real system should check it.

Sources read (none of their code is copied):

- Waters KB WKB63781 "How do you create a comma-delimited text file that can be imported into
  MassLynx as a sample list?" and MassLynx 4.2 Getting Started Guide 715009602 Ver. 00, Table
  5-1 "Required sample list columns" (as summarised in the open-source driver notes below).
- SCIEX KB "Importing a .txt or .csv file into a batch in SCIEX OS software"; SCIEX OS Feature
  Guide for the Echo MS+ system RUO-IDV-05-15796-C, Table 4-1 (as summarised below).
- Agilent Community thread 12581 "How to format a CSV file for import as a new worklist for
  MassHunter" (the example file shipped in `D:\MassHunter\Worklist_Import`); Agilent Known Problem
  Report for LC/MS Acquisition ("-1" = As method).
- Thermo Xcalibur 2.2 Data Acquisition and Processing User Guide XCALI-97209 Rev. D, Appendix A
  (as summarised below).
- An open-source (Apache-2.0) MS worklist writer (README and format notes), which collects the above and states what it
  verified and what it assumed. Read for column names, quoting and sample-type words.

Common to all four: UTF-8, CRLF line endings, `csv` minimal quoting (a field is quoted only when
it contains the delimiter, a quote or a newline), one header row, one row per injection in run
order. Fields the package has no value for are written empty. Sample names are written as given;
generated data file names are `<yyyymmdd>_<job>_<row>_<name>` with Windows-forbidden characters
replaced by `_`.

## Waters MassLynx 4.x sample list (`vendor: masslynx`, `.csv`)

Import: File > Import Worksheet, file type "Comma Delimited (*.CSV, *.TXT)". Row 1 holds the
MassLynx FIELD IDs, which are case-sensitive; columns may be in any order (WKB63781, verified).

| column | written | status |
|---|---|---|
| FILE_NAME | data file name (no extension) | required column (715009602 Table 5-1, verified) |
| FILE_TEXT | sample name | verified (WKB18596: sample text) |
| MS_FILE | ms_method (name, no extension; MassLynx `.exp`) | required (verified) |
| MS_TUNE_FILE | config `tune_file` or empty | column verified; `.ipr` extension unverified |
| INLET_FILE | lc_method or empty | required (verified); MassLynx needs a value for an LC run |
| SAMPLE_LOCATION | position as given, e.g. `1:A,1` | required column (verified); the `1:A,1` notation is a common convention, unverified against a vendor document |
| TYPE | Analyte / Standard / Blank / QC | verified (example files of WKB63781) |
| ID | sample name | verified (WKB18596) |
| INJ_VOL | injection volume, uL | required (verified) |
| Index | row number from 1 | verified (WKB63781) |

Unquoted fields and CRLF come from the KB's example files. Comma delimiter only. Note the brief
mentioned a tab-delimited sample list; the Waters KB documents the comma-delimited worksheet
import, which is what is written here.

## SCIEX OS batch (`vendor: sciexos`, `.txt`)

Import: Batch workspace, Open > Import from file, then Save As. SCIEX's KB says the column
layout should come from a batch exported from your own SCIEX OS; the exact header strings are
not published. The header below is therefore **unverified as a whole**: the column names Sample
Name (under 252 characters), MS Method, Sample Type, Data File and Processing Method are
verified (RUO-IDV-05-15796-C Table 4-1); Rack Type, Rack Position, Plate Type, Plate Position
and Vial Position are named in a SCIEX KB; "Injection Volume", "LC Method", "Sample ID" and
"Comment" are assumed spellings.

| column | written |
|---|---|
| Sample Name | sample name |
| Sample ID | sample name |
| Sample Type | Unknown / Standard / Blank / QualityControl (verified words) |
| MS Method | ms_method (`.msm` on the PC) |
| LC Method | lc_method or empty (`.lcm`) |
| Rack Type, Rack Position, Plate Type, Plate Position | empty: depend on the configured LC; set them in SCIEX OS after import |
| Vial Position | position as given |
| Injection Volume | uL |
| Data File | data file name (several samples may share one in SCIEX OS; here one per row) |
| Processing Method | empty |
| Comment | empty |

## Agilent MassHunter Acquisition worklist (`vendor: masshunter`, `.csv`, UTF-8 with BOM)

Import: in the Worklist, right-click a row > "Add/Append Samples from... (csv, xlsx)" (older
versions: "Import Worklist..."). Headers that match the worklist column names import without a
map file (Agilent Community, verified). Header exactly as the example file shipped with
MassHunter: `Sample Name,Barcode,Rack Code,Sample Position,Method,Data File,Sample Type,Level
Name,Inj Vol (µL),Comment` (verified). The file is written with a UTF-8 byte-order mark because
the header carries a micro sign (Agilent Community: save as UTF-8; the BOM itself is unverified).

| column | written |
|---|---|
| Sample Name | sample name |
| Barcode, Rack Code | empty |
| Sample Position | position as given, e.g. `P1-A1` (verified notation) |
| Method | ms_method (a `.m` method folder name) |
| Data File | data file name with `.d` appended (unverified: MassHunter data files are `.d` folders) |
| Sample Type | Sample / Calibration / Blank / QC (Sample and Calibration verified; Blank and QC unverified) |
| Level Name | empty |
| Inj Vol (µL) | uL (`-1` would mean "As method", verified; not written here) |
| Comment | empty |

lc_method has no column: the LC method is part of the MassHunter method.

## Thermo Xcalibur sequence (`vendor: xcalibur`, `.csv`)

Import: Sequence Setup, File > Import Sequence; only `.csv` imports. Line 1 must be
`Bracket Type=n` (1 Overlapped, 2 None, 3 Non-Overlapped, 4 Open), and the delimiter must equal
the Windows list separator on the acquisition PC (`list_separator` in config.json; `,` in the
US locale, often `;` in Europe) (XCALI-97209 Appendix A, verified). Sample types Unknown, Blank,
QC, Std Bracket, Std Clear, Std Update exist (verified); `standard` is written as `Std Bracket`
(this package's choice, suits bracket type 4).

The header row itself is **not printed by Thermo**; it is the one open-source generators that
target Xcalibur import use (protti `create_queue`, Rapid-QC-MS issue 83), so it is unverified:
`Sample Type, File Name, Sample ID, Path, Instrument Method, Process Method, Calibration File,
Position, Inj Vol, Level, Sample Wt, Sample Vol, ISTD Amt, Dil Factor, L1 Study, L2 Client,
L3 Laboratory, L4 Company, L5 Phone, Comment, Sample Name`.

| column | written |
|---|---|
| Sample Type | Unknown / Std Bracket / Blank / QC |
| File Name | data file name (no extension; Xcalibur adds `.raw`) |
| Sample ID, Sample Name | sample name |
| Path | config `data_path` or empty (the sequence default) |
| Instrument Method | ms_method (`.meth`, written as given) |
| Process Method, Calibration File, Level, L1-L5, Comment | empty |
| Position | position as given (e.g. `RA1`, `1:A1`; notation depends on the autosampler driver, unverified) |
| Inj Vol | uL |
| Sample Wt, Sample Vol, ISTD Amt | `0` (unverified defaults) |
| Dil Factor | `1` (unverified default) |

lc_method has no column: the LC is part of the Xcalibur instrument method.

## Native binary files

MassLynx `.spl`, MassHunter `.wkl` and Xcalibur `.sld` are binary or undocumented and are not
written. The text import routes above are the documented ones.
