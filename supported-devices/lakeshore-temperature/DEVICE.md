---
mhp: "2026-09-12"
id: lakeshore-temperature-01
class: temperature_controller
make: Lake Shore Cryotronics
model: 335 / 336 / 350 cryogenic temperature controller
location: ""
tags: [cryogenic, temperature, pid, heater, physics, lakeshore]
description: Lake Shore 335, 336 or 350 cryogenic temperature controller over Ethernet (336/350) or GPIB, with the Lake Shore ASCII command set. Reads the sensors on inputs A and B in kelvin and drives the heater on control loop 1 (and 2) with a setpoint, a heater range and a ramp rate. Pick it to hold or ramp the temperature of a cryostat, a cold finger or a sample stage between about 4 K and 400 K; the shipped setpoint limits are a placeholder the lab sets to its own cryostat and heater.
driver: driver.py:Device
sim: sim.py:Sim
---

# Lake Shore 335 / 336 / 350 temperature controller

A PID controller for cryostats. Sensors on inputs A and B (C and D on the 336/350) are read in
kelvin; output 1 drives the main heater, output 2 a second heater or an analog output. The
heater range (off, low, medium, high) sets the maximum heater power and is the one setting that
can overheat a sample mount or boil off cryogen fast, which is why the shipped `heater_range_1`
limits are a placeholder for the lab to tighten.

## Operating procedure

1. Read `connected`, then `temperature_a` and `temperature_b` (kelvin). A reading of 0 means
   the input is not configured or the sensor is open; check the front panel.
2. Read `heater_range_1` and `heater_output_1` to see whether the loop is already heating.
3. Write `setpoint_1` (kelvin). With `ramp_rate_1` written first, the setpoint walks to the new
   value at that rate in K/min, which is what a sample mount and a vacuum window prefer.
4. Write `heater_range_1` 1 (low) for small steps; 2 or 3 only when the cryostat and heater are
   rated for it. Or invoke `go_to_temperature`, which sets the setpoint and the range together.
5. Poll `temperature_a` until it is within your tolerance of `setpoint_1_actual` and
   `heater_output_1` has settled. When done, write `heater_range_1` 0, or invoke `heaters_off`.

## What to watch

- `heater_output_1` pinned at 100 % with the temperature not rising means the range is too low
  for the load, or the heater is open: do not raise the range without a person looking.
- The 335's output 2 and the 336's outputs 3 and 4 can be analog voltage outputs rather than
  heaters; `heater_range_2` then means the output range, not a heater power.
- Emergency stop sends `RANGE 1,0` and `RANGE 2,0`: every heater off. The cryostat then cools
  at whatever rate its cooler gives; nothing warms it.
- Writes do not answer, and the generic route waits the `timeout` for each one; a sequence of
  setpoints is slow, not failed.

## Resources

- `references/setup.md`: Ethernet, GPIB and the USB (57600 7O1) limitation, pyvisa, first hardware test.
- `references/lakeshore-commands.md`: the Lake Shore commands this package uses and where they come from.
