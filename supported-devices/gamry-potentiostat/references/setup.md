# Setting up on the Framework PC (Windows-only)

The Gamry Framework and its Electrochemistry Toolkit are Windows software and GamryCOM is a COM
server, so this driver runs only on the Windows PC the instrument is plugged into (USB or Ethernet
through the Framework). The simulated twin runs anywhere.

1. Install the Gamry Framework with the **Electrochemistry Toolkit** licence (it is a purchased option;
   without it the Framework refuses the COM objects with a "Device Not Authorized" code). Power the
   Interface 1010 or Reference 620 and confirm Framework > Options > Instrument Manager lists it;
   note its name (`IFC1010-12345`, `REF620-00123`).
2. In the Python environment that runs `mhp`: `pip install openmhp pywin32`. Use the same bitness
   as GamryCOM registers (a 32-bit Python is the safe choice; the Toolkit's own Python modules are
   32-bit).
3. Copy `config.example.json` to `config.json`: `device` (the section name, or empty for the first
   found), `data_dir`, and the caps `max_run_s` and `max_eis_points`. `cook_columns` only if the
   Toolkit reference manual gives a different column order for your Framework version.
4. Open the Toolkit reference manual (PDF in the Framework install) and check the `Init` argument
   lists in `driver.py` marked `# unverified` (`references/gamrycom.md`); adjust before step 5.
5. Close any Framework experiment on the instrument (the Toolkit refuses an instrument in use), then
   `mhp serve pkg:<this folder> --http <port>` and read `connected` and `device`.

## First hardware test

1. Connect Gamry's dummy cell (the calibration cell) to the leads. Read `connected`, `device`,
   `cell_on` (false).
2. Invoke `ocp` for 10 s: a stable potential near 0 V and a CSV in `data_dir` with `i_A` empty.
3. Invoke `ca` with the first example (0.5 V, 10 s): the trace should show the dummy cell's current
   (a few hundred microamperes); compare one point with a Framework chronoamperometry on the same
   cell. If the columns look swapped, set `cook_columns` in `config.json`.
4. Invoke `cv` with the first example and `eis` with the first example; the EIS spectrum should be
   the dummy cell's semicircle. Then cancel a running `eis` and confirm `cell_on` reads false.
5. Write `output_enabled` true (confirm), read `cell_on` true, trigger `safety/estop`: `cell_on` reads
   false, `state` reads `estop`.

## Status

Driver written from Gamry's Electrochemistry Toolkit brochure (Rev 1.0, 2018), the application note
"Steps for Creating an Application Using GamryCOM" (2015) and a published Python example for a
Reference 600; the Dtaq/Signal `Init` argument lists, the Cook column order and the ReadZ members are
marked unverified in `references/gamrycom.md`. Not yet run on hardware. Status: twin tested.
Windows-only route.
