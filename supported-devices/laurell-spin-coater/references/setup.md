# Setting up a Laurell WS-650 / WS-400 spin processor over serial

**Template package.** The command set in `descriptor.yaml` is a placeholder; obtain Laurell's remote
command document (the one Spin 3000 uses) from support@laurell.com, rewrite the `serial:` block
and `references/serial.md`, and rehearse with the twin until then.

Runs on Linux, macOS or Windows: pure Python, `pip install openmhp pyserial`.

1. Cable. The 650 controller's RS-232 socket (used by Spin 3000) through a straight cable to a
   USB-serial adapter, or its USB port with Laurell's driver (a virtual COM port). Indeck units
   have the connector on the remote controller box.
2. Controller settings: nothing to enable on the keypad as far as the manual says; Spin 3000's
   connection settings (baud, port) are what the controller expects. Set the vacuum threshold
   and valve names in Spin 3000 first; this package does not change them.
3. Find the port: `COM3` (Device Manager), `/dev/ttyUSB0` (Linux), `/dev/tty.usbserial-*` (macOS).
   Copy `config.example.json` to `config.json` and set `port`.
4. Limits: 12,000 rpm and 30,000 rpm/s are the drive's maxima and placeholders for the recipe
   shape; set `speed_rpm` and `acceleration_rpm_s` limits to what your substrates survive.
5. Serve: `mhp serve pkg:<this folder> --http <port>`.

## First hardware test

1. Read `connected`, then `lid_closed` with the lid open and closed, and `vacuum_inhg` with a
   substrate on the chuck and `vacuum_on`; compare with the LCD. An `ERR` or timeout on every
   command means the placeholders are not the controller's protocol: stop here until it is known.
2. Invoke `vacuum_on`, read `vacuum_ok` true above 15 inHg; invoke `vacuum_off` and read false.
3. With a dummy wafer, the lid closed and vacuum on: invoke `run_recipe` with the first example
   (500 rpm 5 s, 3000 rpm 30 s, 0 rpm); `running` goes true, `speed_rpm` follows, `step` advances.
4. Invoke `stop` mid-run and confirm the chuck decelerates; open the lid during another run and
   confirm `lid_closed` false and `running` false (the controller's own interlock).
5. Read `robot_access_ready` with the lid open and the chuck still (true) and with the lid closed
   (false). Record the controller firmware shown under Info / About and the date here when done.

## Status

template: driver and twin are written from the WS-650 operations manual's description of the
controller, programs and interlocks, with a placeholder serial command set; Laurell's protocol
was not found in any public document and the package has not been run on a spin processor.
