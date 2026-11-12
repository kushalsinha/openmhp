# Setting up on the Bluehill Universal PC (Windows only)

Bluehill Universal runs on Windows 10 or 11 (64-bit only; version 4.28 or later for Windows 11)
and its API is a Windows Communication Foundation service on that PC, so this package runs there
through pythonnet. Windows-only.

1. Confirm the Bluehill Universal API is enabled on the installation (Instron says it is included
   with the standard purchase; the API help is under Start > Instron > Help > Bluehill Help) and
   read its reference: the service endpoint, the client assembly and the members for connecting,
   opening a method, setting specimen inputs, rate and limits, starting and stopping a test, and
   reading frame mode, crosshead status, force and displacement.
2. `pip install openmhp pythonnet`.
3. Correct every member name in `config.example.json` `api` from the API help (every shipped
   name is a placeholder), set `endpoint`, `outputs_dir`, `methods_dir`, `load_cell_N`, and copy
   it to `config.json`.
4. In each Bluehill method an agent may run: Export tab, file 1 = results table (CSV, at finish,
   file name from the sample name, suffix `_Results.csv`), file 2 = raw data (`_RawData.csv`);
   set the `columns` in `config.json` to the method's result names (the shipped names use
   Universal's Force/Displacement wording and are unverified).
5. Lower `rate_mm_min` and `limits` bounds in `descriptor.yaml` to the frame, load cell and
   fixtures, and ship that as a package edit.

## First hardware test

1. `mhp serve pkg:<this folder> --http <port>`; read `connected`, `frame_ready`,
   `crosshead_state`, `load` and `extension`; move the crosshead from Bluehill's jog control and
   watch `extension` follow.
2. Invoke `stop_crosshead` while jogging and confirm the crosshead halts.
3. With a scrap specimen in the grips, run `run_test` (`approved: true`) with the method's own
   rate and generous limits; confirm the test starts (press Start on the panel if the frame's
   operator protection asks), `load` rises, and the job ends when the specimen breaks.
4. Compare `peak_load_N` and `modulus_MPa` with Bluehill's results table.
5. Start another test and `safety/estop`; confirm the crosshead stops and the frame shows DISABLED.

## Status

Template. The Bluehill Universal API is documented by Instron only as a WCF interface with the
use cases listed in `references/bluehill_api.md`; no member name is public, every member here is
unverified, and the export column names are inferred. Not yet run on hardware.
