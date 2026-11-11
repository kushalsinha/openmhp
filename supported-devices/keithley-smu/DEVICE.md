---
mhp: "2026-09-12"
id: keithley-smu-01
class: source_meter
make: Keithley (Tektronix)
model: 2400 series SourceMeter (2400, 2401, 2410, 2420)
location: ""
tags: [source-meter, iv-curve, scpi, electronics, physics, gpib]
description: Keithley 2400-series SourceMeter (2400, 2401, 2410, 2420) over SCPI on GPIB or RS-232. Sources a voltage or a current with a compliance limit and measures the other quantity on the same terminals. Pick it for I-V curves, device characterisation, four-wire resistance and biasing a sample under test at up to 20 V and 100 mA as shipped (the instrument itself reaches 200 V and 1 A, 1100 V on the 2410). Not a power supply for loads and not for anything above the compliance a person has set for the DUT.
driver: driver.py:Device
sim: sim.py:Sim
---

# Keithley 2400 SourceMeter

A single-channel source-measure unit: it sources volts and measures amps, or sources amps and
measures volts, with a compliance limit that caps the other quantity. The front or rear
terminals are wired to the device under test (DUT) by a person; this package never knows what
is connected, so the shipped limits (±20 V, ±0.1 A) are a placeholder the lab tightens to what
the DUT survives before anyone enables the output.

## Operating procedure

1. Read `connected`, then `output_on` (expect false) and `last_error` (expect `0,"No error"`).
2. Invoke `source_voltage` with the voltage and the compliance current the DUT tolerates
   (or `source_current` with a compliance voltage). This configures the source without
   enabling it.
3. Write `output_on` true. The first enable of a session deserves a person at the bench; the
   descriptor keeps it automatic because the compliance limit protects the DUT, but say what you
   are about to energise before you do it.
4. Invoke `measure` for one reading (the reply is the full line: voltage, current, resistance,
   time, status); `voltage` and `current` then answer that reading. Change `voltage_setpoint`
   between readings for a sweep; every write is bounded by the descriptor's limits.
5. Write `output_on` false when done. `reset` returns the instrument to its power-on defaults
   with the output off.

## What to watch

- Compliance: when the measured quantity hits the compliance value the source is clamped and
  the status word in a `measure` reply carries the compliance bit. A reading at exactly the
  compliance value is a clamped source, not a measurement of the DUT.
- Only `measure` (`:READ?`) triggers a reading, and it is interlocked on `output_on`; the
  `voltage` and `current` signals (`:FETC?`) hand back the last reading and never touch the
  output. The 2400's `:MEAS?` queries are not used because their `:CONFigure` step can turn
  the source on, and a read must never energise the DUT.
- After an e-stop, `safety/reset` reads every signal; on an instrument that has taken no
  reading since power-on `:FETC?` may answer an error and block the reset until a person
  enables the output and takes one reading from the front panel (unverified; see
  `references/scpi.md`).
- `9.91E+37` in a reply is the 2400's "not a number" (for example resistance when it is not
  being measured), not a real value.
- Emergency stop sends `:OUTP OFF` then `:ABOR`; the output is off within the command time and
  the DUT is left floating at the terminals.

## Resources

- `references/setup.md`: VISA/GPIB or RS-232 wiring, pyvisa, first hardware test.
- `references/scpi.md`: the SCPI commands this package uses and where they come from.
