# Setting up

The package is pure Python with pyserial and runs on Linux, macOS or Windows; the simulated twin
needs nothing. **Status: template.** The command set is a placeholder (see `protocol.md`); do not
connect a real mill until the `serial:` block has been rewritten from Retsch's interface
description.

1. Ask Retsch service for the interface description of your PM 100 / PM 200 / PM 400 and, if the
   manual says the data socket is inactive, for the firmware update that enables it.
2. Cable the mill's serial socket to the PC (at most 2.5 m, per the PM 400 manual) with the cable
   Retsch specifies; on the PC the port appears as `/dev/ttyUSB0`, `/dev/tty.usbserial-*` or `COM3`.
3. `pip install openmhp pyserial`.
4. Rewrite `serial:` in `descriptor.yaml` (baud, eol, every command, booleans, estop) from the
   interface description, and `sim.py` to answer the same grammar.
5. Copy `config.example.json` to `config.json` and set `port`.
6. Set `speed_setpoint`, `run_time` and the `run` parameter limits to what the lab's jars and
   media allow (small jars and a loaded sun wheel have lower safe speeds; the Retsch manual's
   balancing table applies).
7. `mhp serve pkg:<this folder> --http <port>` and read `connected`.

## First hardware test

1. With the lid open: read `lid_closed` (false), `robot_access_ready` (true), `running` (false)
   and `speed` (0). Close the lid: `lid_closed` true, `robot_access_ready` false.
2. Write `speed_setpoint` 200 and read `speed_setpoint_actual` back.
3. With balanced, clamped jars: invoke `run` with `{speed: 200, duration_s: 60}` and confirm it.
   `running` reads true, `speed` climbs to 200, `time_remaining` counts down and the mill stops
   itself after a minute.
4. Invoke `run` again for 300 s, then `stop` after 30 s: the drive brakes to standstill within a
   few seconds and `running` reads false.
5. Start a short grind and trigger `safety/estop`: the mill stops and `state` reads `estop`;
   `safety/reset` only after a person has looked at the mill.

## Status

Template. Written from the public Retsch operating manuals (PM 100/PM 200 operating instructions,
PM 400 manual GB 98.535.9999), which describe the serial sockets but no command set; every command
in `descriptor.yaml` is an unverified placeholder. Not run on hardware.
