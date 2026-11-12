# Setting up a Eurotherm 2400-series furnace controller on Modbus

## What to buy or install

- The controller's comms option: a 2416/2404/2408 with the EIA-485 (2-wire or 4-wire) or
  EIA-232 communications module fitted (Carbolite Gero and MTI sell the furnace with it as the
  "comms option"); or a Modbus TCP gateway in front of it.
- A USB-to-EIA-485 adapter (isolated preferred) or the furnace's RS-232 cable; a PC with Python
  3.11+ and `pip install openmhp pymodbus`. Pure Python; Linux, macOS or Windows.
- Wiring per HA026230 chapter 2: on a 2416, HD = A(+), HE = B(-), HF = common for EIA-485; 120 ohm
  termination at the far end of a long bus.

## Instrument settings that must be enabled

- In the controller's comms list (access level 3): protocol Modbus (`mod`), baud 9600 or 19200,
  parity none, address 1; note the baud and address under `baud` and `unit` in config.json.
- Programmer models only: the 2416 must be a programmer version (2416/CP or /P4) for program
  status, segments and the program blocks to exist; a plain 2416/CC answers them with illegal
  data address, and then only `target_setpoint` applies.
- Resolution: if the controller displays one decimal place, set `scale: 0.1` on the temperature
  registers and on `target_setpoint` in descriptor.yaml.
- Limits: the shipped 1200 degC maximum and 30 degC/min ramp are placeholders. Set them to the
  tube's rating (quartz 1100 degC, alumina 1500-1700) and the element and crucible limits.
- `run_program`, `reset_program` and `target_setpoint` need a person's confirmation; keep it.

## First hardware test

1. Copy `config.example.json` to `config.json`, set `serial_port` (or `host` for a gateway),
   then `mhp validate <this folder>` and `mhp serve pkg:<this folder>`.
2. Read `connected` and `temperature`; compare with the controller display. Ten times too high
   means one decimal place: set `scale: 0.1`. Illegal data address means the controller is not a
   programmer model or the comms module is not Modbus.
3. Read `program_status_code`, `program_number`, `segment` and `manual_mode` with the furnace idle
   (expect 1 or 16, the last program, 0 or 1, false).
4. With the furnace empty and a person present: write `target_setpoint` 50 (confirmed) with the
   programmer in Reset, watch `temperature_setpoint` follow and `output_power` rise; then write it
   back to room temperature.
5. Invoke `run_program {program: 1}` on a short stored program (confirmed); `program_running`
   goes true and `segment` advances; `hold_program`, then `run_program` resumes, then
   `reset_program`. Last, write a two-segment typed program to 80 degC into slot 1 and run it;
   check the segments on the controller's program list match. Record the controller software
   version (from the Info list) and the date here when done.

## Status

twin tested: driver and twin are written from Eurotherm's Series 2000 Communications Handbook
HA026230 Issue 3 and have not yet been run on a furnace. Unverified: writing address 22 to select
the program before Run (the 2416 may need its PrG parameter instead), and the End segment's end
type and end power codes.
