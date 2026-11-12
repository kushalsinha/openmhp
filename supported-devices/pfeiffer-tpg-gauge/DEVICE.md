---
mhp: "2026-09-12"
id: pfeiffer-tpg-gauge-01
class: vacuum_gauge
make: Pfeiffer Vacuum
model: TPG 361 / 362 / 366 (TPG 261 / 262 compatible)
location: ""
tags: [vacuum, pressure, gauge, pirani, cold-cathode, serial]
description: Pfeiffer Vacuum TPG 361/362/366 (and TPG 261/262) total pressure gauge controller over its USB virtual COM or RS-232 port, mnemonic protocol with ENQ/ACK handshake. Reads the pressure and status of up to two gauge channels in mbar, identifies the gauge heads and switches a gauge on or off. Pick it to read chamber or foreline pressure from Pirani, cold-cathode, Bayard-Alpert or capacitance gauges; it does not pump, vent or control anything but the gauges themselves.
driver: driver.py:Device
sim: sim.py:Sim
---

# Pfeiffer TPG gauge controller

A one-, two- or six-channel vacuum gauge controller. Each `pressure_n` signal is what channel
n's gauge head reports in the unit the controller is set to; this package declares mbar, so set
the controller to mbar (`UNI` 0; the TPG 36x default is hPa, which is numerically the same).
Every reply carries a status code first (`status_n`): 0 means the pressure is a measurement,
anything else means it is not (under- or overrange, sensor error, sensor off, no sensor).
Talks over USB (FTDI virtual COM port), RS-232 (TPG 26x) or, on the 36x, Ethernet through
Pfeiffer's virtual COM port tool; this package opens a serial port only.

## Operating procedure

1. Read `gauge_types` once to see which heads are fitted (`TPR/PCR`, `IKR`, `PKR`, `PBR`, `CMR/APR`, `noSENSOR`).
2. Read `status_1` and `pressure_1` together; trust `pressure_1` only when `status_1` is 0.
3. A cold-cathode (IKR/PKR) or hot-cathode (PBR, IMR) head is switched with `sensor_1_on` /
   `sensor_2_on`. Switching a hot-cathode head on above about 1e-3 mbar damages its filament,
   so the write needs a person's confirmation, and the controller's own switch-on interlock
   (parameter `SCx`, set on the front panel) stays the primary protection.
4. `read_all` returns the raw `PRX` line with every channel's status and value in one reply.
5. `sensors_off` switches channels 1 and 2 off; the e-stop does the same.

## What to watch

- A Pirani (TPR) reads about 1e-4 mbar at its floor and cannot go lower; status 1 (underrange) is normal there.
- Status 4 (sensor off) with a cold-cathode head means somebody switched it off; it will not read until switched on.
- Status 5 (no sensor) or 6 (identification error) is a cable or head problem, not a vacuum problem.
- The controller streams measurements once a second at power-up until it receives its first command; the first reply may therefore be a stray line.

## Resources

- `references/setup.md`: cable, port, baud and unit settings, first hardware test.
- `references/protocol.md`: the mnemonics, status codes and handshake this package uses, with the Pfeiffer documents they come from.
