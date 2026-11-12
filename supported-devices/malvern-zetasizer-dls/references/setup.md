# Setting up on the instrument PC (Windows only)

ZS Xplorer runs on Windows 10/11 (.NET Framework 4.8 and .NET 5 prerequisites), and its SDK is a .NET
assembly, so this package runs on the instrument PC through pythonnet. Windows-only.

1. Obtain the ZS Xplorer SDK from Malvern Panalytical (it is not public; ask your account manager
   for the SDK and its reference document). For a Zetasizer Nano under the classic software, ask for
   the Zetasizer Nano SDK instead; the shape is the same.
2. `pip install openmhp pythonnet`.
3. Open the SDK reference and correct the member names in `config.example.json` (`sdk`: assembly,
   application class, connect, status, temperature, SOP load, start, running, abort, result, export);
   every shipped name is a placeholder. Then copy it to `config.json` with `sop_dir` and `export_dir`.
4. Save each SOP (.zsop) agents may run into `sop_dir` from ZS Xplorer.
5. Lower `temperature_setpoint` limits in `descriptor.yaml` to what your cells and samples tolerate
   and ship that as a package edit.

## First hardware test

1. `mhp serve pkg:<this folder> --http <port>`; read `connected`, `status` and `cell_temperature`.
2. Write `temperature_setpoint` 25 and watch `cell_temperature` move.
3. Load the 60 nm latex size standard in a DTS0012 cuvette and run `measure_size` with its SOP;
   compare `z_average_nm` and `pdi` with ZS Xplorer's own record.
4. Load the zeta transfer standard in a DTS1070 cell and run `measure_zeta`; compare `zeta_mv`.
5. Start a measurement and cancel the job; confirm ZS Xplorer shows it aborted.

## Status

No public SDK documentation was found (see references/sdk.md); the driver is written against the
shape such an SDK must have and every member name is unverified. Temperature range from the
Zetasizer Ultra product page (0-120 Cel; bounded here to 0-90). Not yet run on hardware: twin tested.
