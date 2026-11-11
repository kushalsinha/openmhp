# Setting up a Lake Shore 335 / 336 / 350

## What to install

- `pip install pyvisa pyvisa-py` on the serving PC (Linux, macOS or Windows). For the Ethernet
  route nothing else is needed: `tcp://<ip>:7777` is opened as a plain socket by the driver.
- GPIB needs an adapter and its backend (NI-VISA, or linux-gpib with `gpib-ctypes`).

## Cable and port

- Ethernet (336 and 350 only): the controller lists its IP under Interface > Ethernet; the
  command port is 7777. Resource: `tcp://192.168.1.30:7777`. A fixed address or a DHCP
  reservation keeps `config.json` valid.
- GPIB (335, 336, 350): factory address 12, terminator CR LF. Resource `GPIB0::12::INSTR`.
- USB (335, 336, 350): the port is a USB virtual COM port that runs at **57600 baud, 7 data
  bits, odd parity, 1 stop bit**. The generic SCPI route opens a serial device at 9600 8N1 and
  cannot change that, so the USB port does not work with this package as shipped. Use Ethernet
  or GPIB, or (the 335 has no Ethernet) a small driver.py subclass that opens the port at
  57600 7O1: that is the one thing this package does not yet do.

## Settings on the instrument

- Interface > the one you use, enabled; the baud/parity for USB are fixed by the instrument.
- Inputs A and B configured for their sensors (type, curve) by a person; the package only
  reads the kelvin value and does not change input configuration.
- Output 1 in closed-loop PID mode (`OUTMODE 1,1,<input>`), tuned by a person; the package
  reads `output_mode_1` and does not change it. The heater resistance and max current settings
  (`HTRSET`) are the lab's and are not touched.

## Write the config

Copy `config.example.json` to `config.json` beside the package and set `resource`, or let
`mhp node setup` ask for it.

## Known costs of the declarative route

Lake Shore commands do not answer, so each write waits `scpi.timeout` (1 s) for nothing. A
sequence of setpoints takes a second per write; a lab with a reliable link can lower it.

## First hardware test

1. With the heaters off (`RANGE 1,0` on the front panel), `mhp serve pkg:<this folder>` and
   read `connected`, `temperature_a` and `temperature_b`. `*IDN?` must contain LSCI or the probe
   refuses the resource.
2. Read `heater_range_1` (0), `heater_output_1` (0) and `output_mode_1`.
3. Write `setpoint_1` to the current temperature plus 1 K; read `setpoint_1_actual`.
4. Write `heater_range_1` 1 and watch `heater_output_1` rise and `temperature_a` follow over a
   few minutes; then write `heater_range_1` 0.
5. Write `heater_range_1` 1 again and call `safety/estop`: `heater_range_1` must read 0 and the
   front panel shows the heater off. Then `safety/reset`.

Then set `setpoint_1`, `setpoint_2`, both heater-range maxima and the `go_to_temperature`
limits in `descriptor.yaml` to what your cryostat, sample mount and heater are rated for, and
`mhp_lab op='reload'`.

## Status

twin tested. Written from the Lake Shore Model 335 and Model 336 user manuals (chapter 6,
"Remote operation", command summary) and the Lake Shore `lakeshore` Python package's command
names; not yet run on hardware. Items marked unverified in `lakeshore-commands.md` were not
checked against an instrument.
