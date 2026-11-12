---
mhp: "2026-09-12"
id: atlas-ezo-sensors-01
class: sensor
make: Atlas Scientific
model: EZO-pH / EZO-ORP / EZO-DO / EZO-EC / EZO-RTD (UART mode)
location: ""
tags: [ph, orp, dissolved-oxygen, conductivity, temperature, biology, serial]
description: One Atlas Scientific EZO circuit (pH, ORP, dissolved oxygen, conductivity or RTD temperature) in UART mode on a USB-serial carrier, read with the EZO ASCII commands (R, Cal,?, T, i, Status). Reads the probe value, reports whether the circuit is calibrated, sets temperature compensation and runs the calibration commands under confirmation. Use for a single probe in a culture, bath or reactor; one package instance per circuit.
driver: driver.py:Device
sim: sim.py:Sim
---

# Atlas Scientific EZO circuit (UART)

An EZO circuit is a small board between one probe and a serial port, speaking a short ASCII command
set: `R` takes a reading, `Cal,...` calibrates, `T,<temp>` compensates for temperature, `i` says which
circuit it is. All five circuit types share the grammar; what `R` returns depends on the circuit. This
package addresses one circuit on one port (`port` and `circuit` in `config.json`, see
`references/setup.md`); the circuit must be in UART mode (green LED), not I2C (blue LED).

Five reading signals are declared, one per circuit type, all sent as `R`. Only the signal that matches
the installed circuit means anything: on an EZO-pH, `ph` is the reading and `conductivity` returns the
same number labelled wrongly. Read `circuit_info` once and use the matching signal; `circuit` in
`config.json` records the same fact for the person installing it but the driver does not switch on it.

## Operating procedure

1. Invoke `configure_for_polling` once on a new circuit: it turns off continuous output and the `*OK`
   response codes, both of which otherwise leave a second line after every reply and desynchronise reads.
2. Read `circuit_info` (`?i,pH,1.98`) and `calibrated`. An uncalibrated circuit still reads, badly.
3. Write `temperature_compensation` with the sample temperature (pH, DO, EC; the RTD circuit is the
   usual source of it). It is lost at power-off.
4. Read the matching signal (`ph`, `orp`, `dissolved_oxygen`, `conductivity` or `temperature`). A reading takes
   up to a second; the driver waits for the line.
5. To calibrate, follow `references/ezo-commands.md`: the order matters (pH mid point first, EC dry first),
   each step is `approval: confirm`, and the probe must sit in the standard when the command is sent.

## What to watch

- A reply of `*ER` means the circuit did not understand; `-1023.000` from the RTD means no probe.
- `Cal,clear` wipes the calibration; it is confirm-gated like the rest.
- Nothing here moves or heats: `safety.estop` is false and a silent controller only loses its lease.
- `Factory` and `Sleep` are not exposed: a factory reset clears calibration and a sleeping circuit ignores
  everything until woken, and neither belongs in an unattended loop.

## Resources

- `references/setup.md`: carrier board, UART mode, port, first hardware test.
- `references/ezo-commands.md`: the EZO commands this package uses, per circuit, with sources.
