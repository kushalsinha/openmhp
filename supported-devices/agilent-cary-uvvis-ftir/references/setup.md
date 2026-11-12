# Setting up

The vendor route is Windows-only: Cary WinUV and MicroLab run on the Windows PC attached to the
instruments, and that PC (or a share of two of its folders) is what this package talks to. The
package itself is pure Python and can be served from that PC or from any machine that can write
to the two folders; the simulated twin runs anywhere.

Needed on the instrument PC:

- Cary WinUV (5.x; the Scan application, and the ADL Shell if a helper script is used) for the
  Cary 60 or 3500, and/or MicroLab (PC or Expert) for the Cary 630. No extra licence or option is
  needed to export CSV by hand; an unattended helper needs ADL, which ships with Cary WinUV.
- Two folders, for example `C:\OpenMHP\cary\requests` and `C:\OpenMHP\cary\results`, writable by
  the account that serves the package (share them if the package runs elsewhere).
- Something that turns a request into an export. Two honest options:
  1. A person: opens `requests\mhp_<job>.json`, runs the scan in Scan (Cary WinUV) or in the
     MicroLab method, and saves the spectrum with File > Save Data As, file type `ASCII (csv)`,
     named `mhp_<job>.csv`, into the results folder (in MicroLab: export the result as CSV with the
     same name).
  2. A helper script written by the lab, in Cary WinUV's ADL (Applications Development Language),
     that watches the folder and performs the same steps. The ADL statements this package can put
     into an `.adl` sketch (`write_adl: true`) are unverified; adapt them against the ADL Help in
     Cary WinUV and test them before trusting the folder unattended.

Steps:

1. `pip install openmhp` on the serving machine (no vendor library is needed).
2. Copy `config.example.json` to `config.json`: `import_dir`, `results_dir`, the `software`
   versions for the record, `result_wait_s` (900 s is generous for a baseline plus a sample
   scan plus a slow helper) and `poll_s`.
3. `mhp serve pkg:<this folder> --http <port>` and read `connected`.

## First hardware test

1. Read `connected`: both folders must be reachable. Read `queue_depth`: it should be 0; delete
   stale `mhp_*.json` files if not.
2. Put a clean cuvette of water in the Cary 60 (or a clean ATR crystal on the Cary 630).
3. Invoke `scan` with the first example (`mode: uvvis, 240..340 nm, step 1, baseline: true`) and
   confirm it. Watch `requests\` for `mhp_<job>.json` to appear.
4. Run the scan in Cary WinUV as the request says and save it as `ASCII (csv)` named
   `mhp_<job>.csv` in `results\`. The job should finish within seconds of the file appearing and
   report `points` (101 for this window), `x_unit: nm` and a `max_abs` near zero.
5. Repeat with the FTIR example on the Cary 630. If the parser reports the wrong unit or zero
   points, open the CSV: the header line this package expects is described in
   `references/file_formats.md`; adjust the export options (or report the real header) before
   running unattended.

## Status

Driver written from the Cary WinUV software manual, the Agilent community notes on CSV export and
the Cary 630 documentation; not yet run against the instruments. Status: twin tested.
