---
mhp: "2026-09-12"
id: thorlabs-power-meter-01
class: sensor
make: Thorlabs
model: PM100D optical power meter console (PM100A, PM100USB, PM400)
location: ""
tags: [optical-power, photodiode, laser, photonics, physics, scpi, usbtmc]
description: Thorlabs PM100D-family optical power meter console (PM100D, PM100A, PM100USB, PM400) with a photodiode or thermal sensor head, over SCPI on USBTMC. Reads optical power in watts at the wavelength you set, with the head's own calibration. Pick it to measure laser or LED power at a point in a beam path, to log power stability, or to read a beam before and after an element; it measures and never energises anything. The wavelength range and maximum power are the head's, not the console's; set the descriptor limits to the head in use.
driver: driver.py:Device
sim: sim.py:Sim
---

# Thorlabs PM100D optical power meter

A console plus a sensor head (S120C, S121C, S130C photodiodes; S302C, S401C thermal heads). The
console applies the head's calibration curve at the wavelength you tell it, so `wavelength` is
the one setting that changes the reading: a 532 nm beam measured at a 1064 nm setting is wrong
by the ratio of responsivities. Nothing here moves or sources energy, so the package declares
no e-stop and a release watchdog.

## Operating procedure

1. Read `connected`, then `sensor_head` to confirm which head is plugged in (the reply carries
   its name, serial and calibration message) and `last_error` (expect `0,"No error"`).
2. Write `wavelength` to the source wavelength in nm. The descriptor's 200 to 2000 nm limits
   are a placeholder; the head refuses a wavelength outside its own range (then read
   `last_error`).
3. Write `auto_range` true for a first look; for logging a stable beam leave the range fixed on
   the front panel and set `auto_range` false so the reading does not step.
4. Invoke `zero` with the beam blocked to subtract dark current (photodiode heads), then unblock.
5. Read `power` (watts), or write `averaging` higher for a quieter reading, or invoke `measure`
   for a wavelength-and-power pair in one job record.

## What to watch

- A reading at the top of the range with `auto_range` false is saturation, not power; a
  photodiode head also saturates optically above its damage threshold regardless of range.
- `temperature` is answered only by heads with a thermistor (some thermal heads); on others
  the query errors and the read is refused rather than answering a number.
- Thermal heads respond over seconds: wait before trusting `power` after a change.
- The console's own USB connection is the only thing an agent can lose; there is nothing to
  stop. `:STOP` style commands do not exist here.

## Resources

- `references/setup.md`: USBTMC on Linux/macOS/Windows, pyvisa-py and pyusb, first hardware test.
- `references/scpi.md`: the SCPI commands used and where they come from.
