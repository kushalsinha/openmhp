# Setting up a LyoStar freeze dryer on Modbus

**Template package.** Confirm every address in `descriptor.yaml` against the controller's own
tag or register document before first use; every row of `references/registers.md` is marked
unverified, including the two e-stop coils. Until then, rehearse with the twin only. Never
write a coil to a dryer with product in it before step 5 below has been passed on an empty
chamber.

## What to buy or install

- From SP Scientific service (or Martin Christ for an Epsilon): the OPC tag list or Modbus
  register map of your control system, with the phase enumeration and the coil semantics for
  run, hold, stop and defrost. If only OPC is offered, an OPC-to-Modbus gateway, or write the
  package on the openmhp OPC UA adapter instead.
- A PC or small Linux box on the control network with Python 3.11+ and
  `pip install openmhp pymodbus`. Pure Python; Linux, macOS or Windows.
- An Ethernet cable to the PLC or SCADA PC's Modbus port.

## Instrument settings that must be enabled

- Modbus TCP server enabled on the PLC or SCADA (SP service does this), unit id noted
  (`unit` in config.json only if not 1), port 502 or as configured (`port`).
- Remote control permitted in the SCADA (LyoS has a local/remote selection; the coils are
  ignored in local).
- Limits: the shipped shelf band (-60 to 60 °C) and pressure band (0.01–1 mbar) are the
  instrument's; set them to your product's cycle (shelf never above the collapse temperature
  during primary drying).
- Keep `shelf_setpoint`, `stop_recipe` and `defrost_condenser` on `approval: confirm`.

## First hardware test

1. Copy `config.example.json` to `config.json`, set `host`, then `mhp validate <this folder>`
   and `mhp serve pkg:<this folder>`.
2. With the dryer idle and empty, read `connected`, `shelf_temperature`,
   `condenser_temperature`, `chamber_pressure`, `pirani_pressure` and `phase_code`; compare
   with the SCADA screen. Wrong scale or nonsense floats mean the address, type or word order
   is wrong; fix descriptor.yaml and reload.
3. Open and close the door: `door_closed` must follow. Start a defrost from the SCADA and
   check `idle` goes false and `phase_code` reads the defrost code; stop it.
4. Write `shelf_setpoint` to its current value (a person confirms), then 1 °C higher, confirm
   the SCADA follows, and write it back. Same for `chamber_pressure_setpoint` with the pump
   off.
5. Empty chamber, door closed: invoke `start_recipe` with a short test recipe; confirm the
   SCADA shows it running and `recipe_running` true; invoke `hold`, confirm; invoke
   `stop_recipe` (confirm) and check the cycle ends. Finally `mhp estop` and confirm both
   coils clear on the SCADA. Record the SCADA version and document revision here.

## Status

Driver and twin are written from SP and Martin Christ product literature and a placeholder
register map; the package has not yet been run on hardware. Status: twin tested.
