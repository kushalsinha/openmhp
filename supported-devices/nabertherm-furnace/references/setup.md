# Setting up a Nabertherm furnace on Modbus TCP

## What to buy or install

- The Nabertherm communication module (Ethernet, Modbus TCP) for the series 400/500 controller;
  on newer controllers it is built in, on older ones it is a retrofit option from Nabertherm.
  Controller firmware 1.51 or later (B400/C440/P470), module firmware 1.8 or later; program
  transfer needs a P-controller with module 1.14 and operating unit 1.79.
- A PC or small Linux box on the same network with Python 3.11+ and `pip install openmhp pymodbus`.
  Pure Python: runs on Linux, macOS or Windows.
- A network cable from the controller's RJ45 port to the lab network (DHCP with a reservation,
  or a fixed address).

## Instrument settings that must be enabled

- Controller: Settings / Ethernet: a fixed IP or a DHCP reservation; note the address under
  `host` in config.json. Port 502; unit id 1.
- Temperature unit Celsius (register 151 = 0); the package scales every temperature as tenths of
  a degree Celsius.
- Limits: the shipped maxima (1300 degC on the setpoint and the segment targets, 50 degC/min
  ramps) are placeholders. Read `max_temperature` and set descriptor.yaml to your furnace's
  Tmax and to the ramp your elements and crucibles tolerate. The controller only refuses
  values above its own maximum.
- `run_program`, `stop_program`, `segment_jump`, `external_setpoint` and
  `start_external_setpoint` need a person's confirmation; keep it that way for a furnace.

## First hardware test

1. Copy `config.example.json` to `config.json`, set `host`, then `mhp validate <this folder>`
   and `mhp serve pkg:<this folder>`.
2. Read `connected`, `controller_type_code`, `serial_number` and `temperature`; compare with the
   controller display. A wrong type code or a nonsense temperature means the address base is off
   by one (some gateways add 1): fix `reg` values in descriptor.yaml and reload.
3. Read `status_code`, `program_number` and `max_temperature` with the furnace idle; expect 0 or
   4, the last program, and the furnace Tmax.
4. With an empty furnace and a person present: invoke `run_program {program: N}` for a short,
   low-temperature stored program (a person confirms). `program_running` goes true,
   `temperature_setpoint` and `segment` follow the program; `stop_program` ends it.
5. On a P-controller only: invoke `run_program` with two typed segments to 100 degC; watch
   `program_transferred` go true and the controller show program 51. Record the controller and
   module firmware versions and the date here when done.

## Status

twin tested: driver and twin are written from Nabertherm's communication-module manual
M03.0021 (2024-11) and have not yet been run on a furnace. The unit of the remaining-time
registers is assumed to be minutes (unverified).
