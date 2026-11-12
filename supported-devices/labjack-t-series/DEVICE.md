---
mhp: "2026-09-12"
id: labjack-t-series-01
class: data_acquisition_device
make: LabJack
model: T4 / T7 / T8 (LJM library)
location: ""
tags: [daq, analog-input, analog-output, digital-io, labjack, ljm]
description: A LabJack T4, T7 or T8 multifunction DAQ on USB or Ethernet through the LJM library. Pick it to read voltages on AIN0-AIN3, record them for a fixed time at up to 1 kHz into a CSV, set the two 0-5 V analog outputs, or switch the FIO0-FIO3 digital outputs. It is the box behind a sensor, a valve driver or a setpoint input; what the terminals are wired to is the lab's. Not for counters, PWM, SPI/I2C or the on-board Lua scripts.
driver: driver.py:LabJackT
sim: sim.py:SimLabJackT
---

# LabJack T-series (LJM)

The LJM library opens the device by serial number, IP address or `ANY`, and everything is a named
register: `AIN0` reads a voltage, `DAC0` writes one, `FIO0` writes a logic level, `DIO_STATE` reads all
digital lines at once. Kipling (LabJack's own tool) must be closed on USB; over Ethernet several hosts may
share the device.

## Operating procedure

1. Read `connected`, `device_type` and `serial_number`.
2. Read `ain0`..`ain3` for a spot value; on a T7 write `ain_range_0` first if the signal is small.
3. Invoke `sample` with the channels, rate and duration for a record; the result names the CSV and gives
   the mean per channel. Cancel the job to stop early and keep what was recorded.
4. Write `dac0`/`dac1` (0-5 V) and `fio0`..`fio3` (true = high); `dio_state` shows the lines.
5. Emergency stop drives both DACs to 0 V and FIO0-FIO3 low.

## What to watch

- The outputs' limits here are the DAC's range; the harm is in what they drive. Narrow the limits and set
  `approval: confirm` on an output that switches something that matters.
- Above 100 Hz the hardware stream is used; the device may round the rate, and the result reports it.
- A T4 refuses `ain_range_0` (fixed +/-10 V inputs); a T8 has its own range table.
- The twin is a T7 whose AIN1 is jumpered to DAC0, so a write to `dac0` reads back on `ain1`.

## Resources

- `references/setup.md`: LJM library and labjack-ljm, USB or Ethernet, config.json, the first hardware test.
- `references/ljm.md`: the LJM calls and register names used, with sources and the unverified items.
- `config.example.json`: identifier and data folder.
