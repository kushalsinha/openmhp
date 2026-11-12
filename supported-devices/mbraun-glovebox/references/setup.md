# Setting up an MBRAUN glovebox on Modbus TCP

**Template package.** Confirm every address in `descriptor.yaml` against MBRAUN's interface
document for your box before first use; every row of `references/registers.md` is marked
unverified. Until then, rehearse with the twin only.

## What to buy or install

- The PLC Ethernet / fieldbus interface option from MBRAUN (fitted at the factory or by service)
  and its signal list for your box's PLC program version.
- A PC or small Linux box on the same network with Python 3.11+ and
  `pip install openmhp pymodbus`. Pure Python; runs on Linux, macOS or Windows.
- A network cable from the PLC's RJ45 port to the lab network (or a direct cable with fixed
  addresses).

## Instrument settings that must be enabled

- On the touch panel, system / network: a fixed IP address (or a DHCP reservation); note it
  under `host` in config.json. Port 502 and unit id 1 unless MBRAUN's document says otherwise.
- Remote control must be enabled on the PLC (MBRAUN's option does this); the panel keeps
  priority and its own interlocks regardless.
- Limits: the +-12 mbar pressure band and 1-10 purges are placeholders inside MBRAUN's usual
  ranges; set them to what your box and samples need.
- `start_purge`, `start_regeneration` and `stop_regeneration` need a person's confirmation;
  keep it that way.

## First hardware test

1. Copy `config.example.json` to `config.json`, set `host`, then `mhp validate <this folder>`
   and `mhp serve pkg:<this folder>`.
2. Read `connected`, `o2_ppm`, `h2o_ppm` and `box_pressure`; compare with the touch panel. A
   nonsense float (1e-40, 3e38) means the word order or the address is wrong: try
   `word_order: little`, then the next address pair. Fix descriptor.yaml and reload.
3. Open and close the outer antechamber door: `outer_door_closed` must follow; the same for the
   inner door and `inner_door_closed`, and `robot_access_ready` must be true only with the inner
   door open. If a bit does not move, the address is elsewhere: remove the signal rather than
   leave a lie.
4. With both doors closed and the antechamber empty: invoke `antechamber_cycle {purges: 1}`;
   `antechamber_state` must read evacuating, then refilling, then idle, and
   `antechamber_pressure` must fall to about 1 mbar and return. Invoke `stop_antechamber_cycle`
   on a second run to confirm the abort refills.
5. Write `box_pressure_setpoint` 0.5 mbar above the current value and confirm the panel follows;
   write it back. Record the PLC program version and the interface document number here.

## Status

template: driver and twin are written from MBRAUN's operating manuals and data sheets with a
placeholder register map; no public Modbus document was found and the package has not been run
on a glovebox.
