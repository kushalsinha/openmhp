# Setting up on the microscope PC (Windows, Linux or macOS)

1. In the Python environment that runs `mhp`: `pip install pymmcore-plus` (BSD-3; it depends on pymmcore and
   numpy). Then `mmcore install` downloads the Micro-Manager device adapters (the vendor DLLs / shared
   libraries) for your platform; or point `MICROMANAGER_PATH` at an existing Micro-Manager 2.0 install.
2. Build or copy the hardware configuration (.cfg) with Micro-Manager's Hardware Configuration Wizard. It must
   define a camera, an XY stage, a focus (Z) stage and a config group of channel presets (named `Channel`
   unless `channel_group` says otherwise). The built-in `demo` configuration (DemoCamera, demo stages) needs
   no hardware and is the twin's shape.
3. Close the Micro-Manager GUI; the device adapters cannot be shared between two processes.
4. Copy `config.example.json` to `config.json`: `config_dir` and `config_file`, `data_dir` for the TIFFs,
   and `soft_limits_um` for x, y and z from the stage's travel and the objective's working distance.
5. Replace the placeholder bounds in `descriptor.yaml` (+/-50000 um XY, +/-10000 um Z) with the same numbers.

## First hardware test

1. `mhp node setup` on this package: its probe loads the configuration and prints the camera label,
   exposure and Z position.
2. Read `connected`, `camera`, `channels`, `xy_position`, `z_um`.
3. Write `exposure_ms` 20 and `channel` to a bright-field or transmitted preset; invoke `snap` and open the TIFF.
4. Invoke `move_xy` by 100 um from the current position and read `xy_position` back.
5. With the objective well clear of the sample, invoke `acquire_z_stack` over 10 um in 2 um steps, then
   cancel a second stack after the first plane and confirm Z returns to the start.

## Status

Twin tested. Written from the pymmcore-plus / MMCore API documentation, not yet run on a microscope.
`waitForConfig` after `setConfig` and the array/dtype handling of `getImage` are unverified; see `pymmcore.md`.
