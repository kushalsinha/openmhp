---
mhp: "2026-09-12"
id: new-era-syringe-pump-01
class: pump
make: New Era Pump Systems
model: NE-1000 / NE-4000 (NE-1000 series)
location: ""
tags: [syringe-pump, infusion, withdrawal, biology, serial]
description: New Era NE-1000 or NE-4000 programmable syringe pump driven over RS-232 with the pump network command set in Basic mode (DIA, RAT, VOL, DIR, RUN, STP, DIS). Sets syringe diameter, rate and target volume, infuses or withdraws a volume and waits for the pump to stop, reports dispensed volumes. Use for metered dosing or sampling from a single syringe up to 60 mL at up to tens of mL/min; one package instance per pump address.
driver: driver.py:Device
sim: sim.py:Sim
---

# New Era NE-1000 / NE-4000 syringe pump

A stepper-driven syringe pump with an RS-232 "To Computer" socket. Commands are plain upper-case words
with an optional two-digit address (`00RAT 1.5 MM`); the pump answers every command with a packet that
starts with its address and a status letter (`I` infusing, `W` withdrawing, `S` stopped, `P` paused,
`A?` alarm). Put the port and the pump's network address under `port` and `address` in `config.json`
(see `references/setup.md`); the driver prefixes the address to every command it sends.

## Operating procedure

1. Read `pump_status` to confirm the link (`00S` idle). If it reads `A?R` the pump was just powered up;
   any command acknowledges the reset alarm and the next one works.
2. Write `diameter_mm` for the syringe in the clamp (the manual's table, section 12.7, lists common
   syringes; a BD 10 mL plastic syringe is 14.5 mm). Setting the diameter resets the volume units.
3. Invoke `infuse` with `volume_ml` and `rate_ml_min`. The action sets the units to mL, the rate, the
   volume and the direction, starts the pump and polls `DIS` until the status is no longer `I`, then returns
   every reply. `withdraw` is the same the other way. Both are cancellable: a cancel stops the pump.
4. Read `infused_volume` and `withdrawn_volume` (the pump's own totals, in the units of `volume_units`)
   to confirm what moved; invoke `clear_dispensed` before a new series.
5. `stop` sends `STP` at any time; `estop` sends the same.

## What to watch

- The pump refuses rates it cannot reach for the diameter with `?OOR`; the action then fails before `RUN`
  and nothing has moved. Rate and volume take at most four significant digits (`12.34`, not `12.345`).
- A stalled motor (syringe empty, blocked line) answers `A?S`; clear it by stopping and checking the line.
- Safe mode (CRC-framed packets, communication timeout) is not used; the pump must be in Basic mode
  (`SAF 0`, the default), which the `basic_mode` action sets.
- The syringe clamp is mechanical; the pump cannot tell whether a syringe is fitted or how full it is.

## Resources

- `references/setup.md`: cable, port, address, Basic mode, first hardware test.
- `references/ne-1000-protocol.md`: the RS-232 commands and reply packets this package uses, from the NE-1000 manual.
