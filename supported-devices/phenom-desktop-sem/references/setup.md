# Setting up

PPI (Phenom Programming Interface) is a licensed option: Thermo Fisher supplies the PyPhenom package,
its reference document and a licence password bound to the instrument ID. Thermo's PPI page lists
Windows as the supported OS for the PC that runs the scripts; that PC sits on the Phenom's network.
Nothing in this package needs Windows itself (pure Python, `pip install openmhp`), but PyPhenom
ships for Windows, so plan on the PPI PC.

1. Obtain PPI from Thermo Fisher (or the Phenom reseller) for your instrument: the PyPhenom
   package (install it into the Python that runs `mhp`), the PPI reference, and the licence password.
2. Connect the PC to the Phenom's network; note the instrument's address and its instrument ID
   (MVE... serial). Test with Thermo's own example script first.
3. Copy `config.example.json` to `config.json`: `address`, `instrument_id`, `image_dir`. Store the
   licence password with `mhp node setup` (it goes into the OS keyring under PhenomPPI /
   <instrument_id>), or set `ppi_password` in config.json on a PC nobody else reads.
4. Open the PPI reference and check the member names in `config.example.json` `ppi` against it:
   `Unload`, `SemAcquireImage`, `SemAutoFocus` and `Position` appear in Thermo's own material;
   every other name is a placeholder (see references/ppi.md). Correct the `ScanParams` field names
   in `driver.py` (`size`, `nFrames`, `dwellTime`, `detector`) and the detector enum if they differ.
5. Set `move_stage` limits and `high_voltage` limits in `descriptor.yaml` to your model (XL: 100 x
   100 mm stage, 4.8-20.5 kV advanced range; Pharos and ProX differ) and ship that as a package edit.

## First hardware test

1. With no holder loaded: `mhp serve pkg:<this folder> --http <port>`; read `connected`,
   `instrument_mode`, `operational_mode` (expect Unloaded) and `robot_access_ready` (true).
2. Place a holder with a stub of the Phenom's reference sample; `load_sample`; expect LiveSem within
   a minute and `vacuum_ready` true.
3. `move_stage` to (0, 0), then (10, 0); compare `stage_position` with the Phenom's own display.
4. `acquire_image` at 5000x, 1920 x 1200, `auto_focus: true`; open the TIFF and compare the
   magnification in the result with the instrument's.
5. `unload_sample`; expect `robot_access_ready` true. Then `safety/estop` from a loaded, live state
   and confirm the instrument goes to Standby.

## Status

Written from the Phenom XL G3 datasheet (DS0328-EN-07-2025: ranges, loading time, image sizes, stage),
Thermo's PPI product page (Windows, network connection), Thermo's "The power of scripting with a desktop
SEM" webinar (Unload, SemAcquireImage, SemAutoFocus) and a Thermo-partner technical note (23-SEM04) whose
screenshot shows the PyPhenom connection call and Position in metres. The PPI reference itself was not
readable; every other member name is unverified and configurable. Not yet run on hardware. Status: template, because most PPI member names are placeholders until the PPI reference is read.
