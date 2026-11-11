# Setting up a BINDER KBF / KMF chamber on Modbus TCP

**Template package.** Confirm every address in `descriptor.yaml` against the controller's
Modbus document (BINDER *Interface Technical Specifications* 7001-0242) before first use; every
row of `references/registers.md` is marked unverified. Until then, rehearse with the twin only.

## What to buy or install

- The MB2 controller's Ethernet port is standard; ask BINDER service for document 7001-0242
  (the Modbus register list) for your controller firmware.
- A PC or small Linux box on the same network with Python 3.11+ and
  `pip install openmhp pymodbus`. Pure Python; runs on Linux, macOS or Windows.
- A network cable from the chamber's RJ45 port to the lab network (or a direct cable to the
  PC with fixed addresses).

## Instrument settings that must be enabled

- On the MB2 touchscreen, Settings / Ethernet: a fixed IP address (or DHCP with a
  reservation); note it under `host` in config.json.
- Modbus unit id (default 1) under `unit` only if it was changed; TCP port 502 unless the
  document says otherwise (`port` in config.json).
- Limits: the shipped bands (0–70 °C, 10–80 % rH) are the instrument's; set them to the study
  conditions ± the protocol tolerance so an agent cannot ask for anything else.
- Both setpoints need a person's confirmation (`approval: confirm`): keep it that way for a
  chamber holding a stability study.

## First hardware test

1. Copy `config.example.json` to `config.json`, set `host`, then `mhp validate <this folder>`
   and `mhp serve pkg:<this folder>`.
2. Read `connected`, then `temperature` and `humidity`; compare with the touchscreen. A
   nonsense float (1e-40, 3e38) means the word order or the address is wrong: try
   `word_order: little`, then the next address pair. Fix descriptor.yaml and reload.
3. Read `temperature_setpoint_actual` and `humidity_setpoint_actual`; they must equal the
   setpoints shown on the touchscreen.
4. Open the door for 5 s: `door_closed` must go false and come back; if not, the bit is
   elsewhere, so remove the signal rather than leave a lie. Same for `light_on` and
   `alarm_active` (trigger a test alarm from the controller if your SOP allows).
5. On an empty chamber only: write `temperature_setpoint` to its current value (a person
   confirms), confirm the display is unchanged, then 0.5 °C higher, confirm the display
   follows, then back. Record the firmware version and document revision here.

## Status

Driver and twin are written from BINDER's published document numbers, data sheets and
fragments of the interface specification, with a placeholder register map; the package has
not yet been run on hardware. Status: twin tested.
