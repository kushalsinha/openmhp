# Setting up (template: correct the function names first)

SharkSEM is the remote-control interface of the TESCAN microscope software on the microscope PC; it
is a TCP protocol, so this package can run on that PC (Windows) or on any Linux, macOS or Windows
machine that can reach it, provided TESCAN's client library imports there. Only the Python standard
library is otherwise needed: `pip install openmhp`.

1. Ask TESCAN (or your service engineer) for the SharkSEM manual and the SharkSEM client library
   for your software version (VEGA, MIRA and CLARA all carry it; it is also the base of TESCAN's
   Python API and Automation SDK). Enable and license remote control in the microscope software and
   note the port it listens on.
2. Put the client library on the Python path of the machine that runs `mhp` (it is not on PyPI). If
   its module or class is not `sem` / `Sem`, set `module` and `client` in `config.json` `sharksem`.
3. Open the SharkSEM manual and correct every function name in `config.example.json` `sharksem`
   (vacuum, high voltage, stage, scanning, detectors, auto working distance) and the assumptions in
   `references/sharksem.md`: the vacuum status codes, detector indices, the `ScScanXY` and
   `FetchImage` argument lists and the units (mm, volts, degrees). Then copy it to `config.json`
   with `host`, `port` and `image_dir`.
4. Set `move_stage` limits (x, y, z, rotation, tilt) and `high_voltage` limits in `descriptor.yaml`
   to your chamber, holders and column; the shipped numbers are placeholders. Ship that as a package
   edit.

## First hardware test

1. Chamber vented, door closed, a stub with the reference sample on the stage:
   `mhp serve pkg:<this folder> --http <port>`; read `connected`, `vacuum_status` (vented),
   `robot_access_ready` (true), `stage_position`.
2. `load_sample`; watch `vacuum_status` go pumping then ready and `vacuum_ready` true.
3. Write `high_voltage` 10; `set_beam {enable: true}`; `beam_on` true after the run-up.
4. `move_stage` to (0, 0) then (5, -3.5); compare `stage_position` with the microscope software.
5. `acquire_image` at 2000x, 1024 x 768, speed 5, `auto_focus: true`; open the TIFF and compare the
   view field in the result with the software's. Then `unload_sample` and confirm the vent, and
   `safety/estop` from a beam-on state and confirm the high voltage goes off.

## Status

Template. No public SharkSEM documentation or permissively licensed client was found, so the driver is
written against the shape of a SharkSEM session (connect, vacuum, HV, stage, scan, fetch, detectors)
with every function name unverified and configurable; see references/sharksem.md. Instrument ranges
(0.2-30 kV, stage travel) are placeholders. Not run on hardware.
