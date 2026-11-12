---
mhp: "2026-09-12"
id: rigol-oscilloscope-01
class: oscilloscope
make: Rigol
model: DS1000Z / MSO1000Z oscilloscope (DS1054Z, DS1104Z; MSO5000 and DHO800/900 by notes)
location: ""
tags: [oscilloscope, waveform, measurement, scpi, electronics, engineering]
description: Rigol DS1000Z/MSO1000Z four-channel digital oscilloscope (DS1054Z, DS1104Z; the MSO5000 and DHO800/900 share most of the command set) over SCPI on LAN or USB. Runs, stops and single-shots acquisition, sets the timebase, channel 1 scale and offset, the edge trigger source and level, and reads the automatic measurements (Vpp, Vmax, Vmin, Vrms, frequency, period) and the sample rate. Pick it to check a signal is present and in range, to measure an amplitude or frequency, or to confirm a trigger before a longer test. Waveform download is binary and not provided here; this package reads measurements only.
driver: driver.py:Device
sim: sim.py:Sim
---

# Rigol DS1000Z oscilloscope

A bench oscilloscope that measures and never sources: the probes are wired by a person, and
nothing here energises anything, so the package declares no e-stop (`stop` halts acquisition,
which is not a safety stop) and a release watchdog. The automatic measurements are read from the
displayed waveform; a measurement the scope cannot make answers 9.9E37, which this package
passes through as a number, so check for it.

## Operating procedure

1. Read `connected`, `trigger_status` (TD, WAIT, RUN, AUTO or STOP) and `ch1_display`.
2. Write `timebase_s`, `ch1_scale_v` and `ch1_offset_v` for the expected signal, or invoke
   `autoset` (a person confirms, since it rewrites every channel and trigger setting).
3. Write `trigger_source` (CHAN1) and `trigger_level_v`; invoke `run` and read
   `trigger_status` until it shows TD (triggered) or AUTO.
4. Read `vpp_ch1`, `vrms_ch1`, `freq_ch1`, or invoke `measure` with any item and channel for a
   measurement kept in the job record. 9.9E37 means the scope could not make the measurement
   (no signal, clipped, or off screen).
5. Invoke `single` to arm a one-shot capture, or `stop` to freeze the display. The scale
   settings may be changed while stopped to inspect the frozen trace.

## What to watch

- A clipped trace gives a wrong Vpp and Vrms without an error: if `vmax_ch1` or `vmin_ch1` is
  at the screen edge (4 divisions times `ch1_scale_actual`, less the offset), raise the scale.
- Scales and timebase snap to the scope's 1-2-5 sequence; read the `_actual` signal after a
  write to see what was applied. Offset and trigger level ranges depend on the scale, and the
  scope clamps what it cannot apply.
- The waveform data command (`:WAV:DATA?`) returns a binary block that the declarative driver
  cannot express; a package that needs the raw trace subclasses the driver.

## Resources

- `references/setup.md`: LAN or USB, pyvisa, first hardware test, model differences.
- `references/scpi.md`: the DS1000Z SCPI commands used and where they come from.
