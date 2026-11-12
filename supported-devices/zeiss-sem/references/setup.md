# Setting up on the SmartSEM PC (Windows only; template: correct the names first)

SmartSEM runs on the microscope's Windows PC and its Remote API is a COM automation object installed
with it, so this package runs on that PC through pywin32. Windows-only: the twin runs anywhere, the
real driver only there.

1. Obtain the SmartSEM Remote API licence and reference from ZEISS (the installer's Remote API
   component; ZEISS's knowledge base describes installing the Remote API Client and a "SmartSEM API
   Test" desktop application that exercises the same object). SmartSEM must be running with the
   microscope initialised whenever this package is used.
2. In the Python that runs `mhp`: `pip install openmhp pywin32`.
3. Open the API reference (or the API Test application) and correct every name in
   `config.example.json` `smartsem`: the COM ProgID, the initialise/close members, the Get/Set/
   Execute/Grab/MoveStage members, the vacuum, run-up and stage status parameters and their words,
   the EHT, stage, magnification, scan-rate and detector parameters, and the commands. The argument
   order assumed for `Grab` and `MoveStage` is in references/smartsem_api.md. Then copy it to
   `config.json` with `image_dir`.
4. Set `move_stage` limits (x, y, z, rotation, tilt) and `high_voltage` limits in `descriptor.yaml`
   to your chamber, holders and column; the shipped numbers are placeholders. Ship that as a package
   edit.

## First hardware test

1. Chamber at atmosphere, door closed, a stub with the reference sample on the stage:
   `mhp serve pkg:<this folder> --http <port>`; read `connected`, `vacuum_status`,
   `robot_access_ready` (true), `stage_position`; compare with SmartSEM's panels.
2. `load_sample`; watch `vacuum_status` go Pumping then Ready and `vacuum_ready` true.
3. Write `high_voltage` 10; `set_beam {enable: true}`; `beam_on` true after the run-up and the EHT
   panel in SmartSEM agreeing.
4. `move_stage` to (0, 0) then (5, -3.5); compare `stage_position` with SmartSEM's stage panel.
5. `acquire_image` at 2000x, 1024 x 768, speed 5, `auto_focus: true`; open the TIFF and compare the
   magnification in the result with SmartSEM's. Then `unload_sample` and confirm the vent, and
   `safety/estop` from an EHT-on state and confirm the EHT goes off.

## Status

Template. The SmartSEM Remote API reference is not public and no permissively licensed open-source
client was found, so the driver is written against the shape such a COM remote API must have, with
every ProgID, member, parameter and command name unverified and configurable (references/
smartsem_api.md). Instrument ranges are placeholders. Not run on hardware.
