---
mhp: "2026-09-12"
id: ni-daqmx-01
class: daq
make: National Instruments
model: USB-6001/6008/6009, USB-621x, 63xx (NI-DAQmx)
location: ""
tags: [daq, analog-input, analog-output, digital-io, national-instruments, nidaqmx]
description: A National Instruments multifunction DAQ (USB-6001, USB-6008/6009, USB-621x, PCIe or USB-63xx) through the NI-DAQmx runtime and the nidaqmx Python package, on Windows or Linux. Pick it to read voltages on ai0-ai3, record them hardware-timed at up to 1 kHz into a CSV, set ao0/ao1, or switch port0 line0-3. It is the box behind a sensor, a valve driver or a setpoint input; what the terminals are wired to is the lab's. Not for counters, triggering, waveform generation or macOS hosts.
driver: driver.py:NIDaqmx
sim: sim.py:SimNIDaqmx
---

# NI-DAQmx multifunction DAQ

NI-DAQmx names the device (`Dev1` in NI MAX) and its channels (`Dev1/ai0`, `Dev1/ao0`, `Dev1/port0/line0`).
Each read or write here is one short nidaqmx Task, as NI's own examples do, so NI MAX's test panels must be
closed while this package runs. The NI-DAQmx runtime exists for Windows and Linux only.

## Operating procedure

1. Read `connected`, `device` and `product_type`.
2. Read `ai0`..`ai3` for a spot value (software-timed, default range).
3. Invoke `sample` with the channels, rate and duration for a hardware-timed record; the result names the
   CSV and gives the mean per channel. Cancel the job to stop early and keep what was recorded.
4. Write `ao0`/`ao1` and `port0_line0`..`port0_line3` (true = high); `port0_state` shows the lines as
   last written.
5. Emergency stop writes both AOs to 0 V and port0 line0-3 low.

## What to watch

- The AO limits here are a placeholder (+/-10 V); a USB-6008/6009 only does 0-5 V and NI-DAQmx refuses more.
  Narrow the limits and set `approval: confirm` on an output that switches something that matters.
- `port0_state` is what this package last wrote, not a reading of the pins.
- The sample clock rate the device actually used is in the result; cheap devices round it.
- The twin is a USB-6009 whose ai1 is jumpered to ao0, so a write to `ao0` reads back on `ai1`.

## Resources

- `references/setup.md`: NI-DAQmx runtime (Windows or Linux), nidaqmx, the device name, the first hardware test.
- `references/nidaqmx.md`: the nidaqmx calls used, with sources and the unverified items.
- `config.example.json`: device name and data folder.
