---
mhp: "2026-09-12"
id: srs-lockin-01
class: lock_in_amplifier
make: Stanford Research Systems
model: SR830 DSP lock-in amplifier (SR810; SR860/SR865A with notes)
location: ""
tags: [lock-in, phase-sensitive, modulation, physics, scpi, gpib]
description: Stanford Research Systems SR830 DSP lock-in amplifier (also the SR810; the SR860 and SR865A use a newer command set, see references) over GPIB or RS-232 with the SRS ASCII command set. Reads X, Y, R and theta, sets the reference frequency, sine output amplitude, sensitivity, time constant and phase, and drives the four auxiliary DC outputs. Pick it for phase-sensitive detection of a modulated signal, such as photocurrent behind a chopper, AC transport measurements, resistance bridges, and for sourcing small DC voltages from its aux outputs.
driver: driver.py:Device
sim: sim.py:Sim
---

# SRS SR830 lock-in amplifier

A dual-phase DSP lock-in. The reference is internal (its own sine output drives the experiment)
or external (TTL or sine on the REF IN). The sensitivity and time constant are chosen from the
instrument's fixed tables by index; the tables are in `references/srs-commands.md`. The sine
output and the four aux outputs are the only things this instrument sources, and none of them
switches off: the e-stop drives them to their minimum instead.

## Operating procedure

1. Read `connected`. Write `output_interface` 1 for GPIB or 0 for RS-232 first: the SR830
   sends its replies to the interface selected by `OUTX`, and a query before that may answer on
   the other port.
2. Write `frequency` and `sine_amplitude` for an internal reference (`reference_source` 1), or
   `reference_source` 0 and check `frequency` reads the external reference.
3. Write `sensitivity_index` and `time_constant_index` from the tables, or invoke `auto_gain`
   once the signal is present. Invoke `auto_phase` to zero `theta` if you want the signal in X.
4. Read `x`, `y`, `r`, `theta`, or invoke `snapshot` to get X, Y, R and theta from the same
   instant in one reply.
5. Wait several time constants after any change before trusting a reading; the overload
   indicators are not read by this package, so watch `r` against the sensitivity full scale.

## What to watch

- A reading equal to the sensitivity full scale means overload, not signal; invoke `auto_gain`
  or raise the index.
- The sine output is 0.004 V minimum: there is no off. The e-stop sets it to 0.004 V and the aux
  outputs to 0 V, and says so in the safety notes; a person disconnects the BNC when a sample
  must see nothing.
- Aux outputs are ±10.5 V DC into a high impedance; whatever they drive (a gate, a coil driver)
  is the lab's business, and the lab tightens their limits in the descriptor.
- Writes do not answer; the generic route waits the `timeout` for each one.

## Resources

- `references/setup.md`: GPIB or RS-232, pyvisa, the OUTX gotcha, first hardware test.
- `references/srs-commands.md`: the SR830 commands used, the sensitivity and time constant tables, and SR860 differences.
