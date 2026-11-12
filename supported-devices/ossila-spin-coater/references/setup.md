# Setting up an Ossila Spin Coater over USB serial

**Template package.** The command set in `descriptor.yaml` is a placeholder; ask Ossila whether your
unit's firmware offers serial control over USB and for its command document, rewrite the `serial:`
block and `references/serial.md`, and rehearse with the twin until then.

Runs on Linux, macOS or Windows: pure Python, `pip install openmhp pyserial`.

1. Cable. The unit's USB port to the PC (a glovebox USB feedthrough if the unit is inside); it
   enumerates as a virtual COM port when the firmware offers serial control.
2. Unit settings: nothing to enable on the display as far as the manual says; the display keeps
   priority and its lid interlock acts regardless.
3. Find the port: `COM4` (Device Manager), `/dev/ttyACM0` or `/dev/ttyUSB0` (Linux),
   `/dev/tty.usbmodem*` (macOS). Copy `config.example.json` to `config.json` and set `port`.
4. Limits: the L2001A3 figures (6,000 rpm, 1,000 s, 10 programs) are shipped; for an L2001B1 raise
   `speed_rpm` to 10,000, `duration_s` to 3,600 and `program`/`slot` to 15. The 2,000 rpm/s
   acceleration cap is a placeholder: set it to what your substrates survive.
5. Serve: `mhp serve pkg:<this folder> --http <port>`.

## First hardware test

1. Read `connected`, then `lid_closed` with the lid open and closed; compare with the display. An
   error or timeout on every command means the placeholders are not the unit's protocol: stop
   here until it is known.
2. Read `program` and `step` with the unit idle (expect the displayed program and 0).
3. With a dummy substrate and the lid closed: invoke `run_recipe` with the first example (1,000
   rpm 10 s, 4,000 rpm 30 s, 0 rpm); `running` goes true, `speed_rpm` follows, `step` advances,
   `time_remaining` counts down as the display does.
4. Invoke `stop` mid-run and confirm the chuck decelerates; open the lid during another run and
   confirm `lid_closed` false and `running` false (the unit's own interlock).
5. Read `robot_access_ready` with the lid open and the chuck still (true) and with the lid closed
   (false). Record the firmware version shown on the display and the date here when done.

## Status

template: driver and twin are written from the Ossila Spin Coater user manual's specification of
the unit, programs and interlock, with a placeholder serial command set; Ossila publishes none for
the spin coater and the package has not been run on one.
