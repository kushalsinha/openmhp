# Setting up a Heracell VIOS / Steri-Cycle incubator on Modbus

**Template package.** Confirm every address in `descriptor.yaml` against the controller's
Modbus document before first use (see `references/registers.md`, every row is marked
unverified). Thermo's user manual documents an ASCII protocol over USB/RS-232, not Modbus, so
this package assumes either a Modbus option on the controller or a gateway in front of its
data interface. Until the map is confirmed, rehearse with the twin (`sim.py`) only.

## What to buy or install

- The incubator's data interface option (USB or RS-232 "data communication" option, Thermo
  part per your model) and, if the controller has no Modbus of its own, a serial-to-Modbus-TCP
  gateway configured to poll the ASCII protocol of manual chapter 12.
- A PC or small Linux box on the same network (or on the serial side for Modbus RTU), with
  Python 3.11+ and `pip install openmhp pymodbus`. The route is pure Python and runs on Linux,
  macOS or Windows.
- An Ethernet cable to the Modbus TCP interface, or a USB cable / RS-232 lead for RTU.

## Instrument settings that must be enabled

- At the touchscreen, Settings / Setup: data interface enabled and its baud rate (9,600 to
  57,600) matching the gateway or PC.
- On the controller or gateway: Modbus enabled, unit id (default 1), TCP port 502 or the serial
  parameters for RTU. Put the address under `host` (or `serial_port` and `baud`) in config.json;
  `unit` only if it is not 1.
- Limits: the shipped `temperature_setpoint` band (20–50 °C) is a placeholder. Set it to what
  your cultures tolerate; the instrument itself allows room temperature + 3 to 55 °C.

## First hardware test

1. Copy `config.example.json` to `config.json`, set `host` (and `unit`), then
   `mhp validate <this folder>` and `mhp serve pkg:<this folder>`.
2. Read `connected`, then `temperature`, `co2`, `humidity` and `door_closed`. Compare each with
   the touchscreen. A value that is off by a factor of 10 or 100 means the scale is wrong; a
   constant or a nonsense number means the address is wrong. Fix descriptor.yaml and reload.
3. Open the glass door for 5 s: `door_closed` must go false and come back. If it does not, the
   door bit is not where the template put it; remove the signal rather than leave it lying.
4. Write `temperature_setpoint` to the value already shown on the touchscreen (no physical
   change), then read `temperature_setpoint_actual` and check the touchscreen still shows it.
   Then write it 0.5 °C higher, confirm the display follows, and write it back.
5. Write `co2_setpoint` to the current display value, confirm, then leave every setpoint as
   you found it. Record the controller firmware version and the Modbus document number here.

## Status

Driver and twin are written from the Thermo user manual 50162755 (March 2020) and a
placeholder register map; the package has not yet been run on hardware. Status: twin tested.
