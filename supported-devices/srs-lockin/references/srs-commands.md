# SR830 commands used by the srs-lockin package

Source: "MODEL SR830 DSP Lock-In Amplifier" operating manual and programming reference,
Stanford Research Systems, revision 2.5 (10/2011), chapter 5 "Remote programming" (command
list and the sensitivity/time constant tables), cross-checked against pymeasure's MIT-licensed
`SR830` driver for command names and reply formats. Commands are ASCII, terminated by LF (or
CR); queries end in `?` and answer one line; commands answer nothing.

| Command | Used for | Meaning |
|---|---|---|
| `*IDN?` | probe | `Stanford_Research_Systems,SR830,s/n...,ver...` |
| `*CLS` | `clear_status` | clear status registers |
| `OUTX <i>` | `output_interface` | replies go to RS-232 (0) or GPIB (1); send before any query |
| `OUTP? <i>` | `x`, `y`, `r`, `theta` | 1 X, 2 Y, 3 R, 4 theta (degrees) |
| `SNAP? <i>,<j>[,...]` | `snapshot` | 2 to 6 values sampled together, comma-separated; 1 X, 2 Y, 3 R, 4 theta, 5-8 aux in 1-4, 9 ref frequency |
| `FREQ <f>` / `FREQ?` | `frequency` | internal reference frequency, 0.001 to 102000 Hz |
| `SLVL <v>` / `SLVL?` | `sine_amplitude`, estop | sine output amplitude, 0.004 to 5.000 V rms in 0.002 V steps |
| `SENS <n>` / `SENS?` | `sensitivity_index` | sensitivity index 0 to 26 (table below) |
| `OFLT <n>` / `OFLT?` | `time_constant_index` | time constant index 0 to 19 (table below) |
| `PHAS <d>` / `PHAS?` | `phase` | reference phase shift, -360.00 to 729.99 degrees |
| `FMOD <i>` / `FMOD?` | `reference_source` | 0 external, 1 internal |
| `AUXV <n>,<v>` / `AUXV? <n>` | `aux_out_1..4`, `set_aux_outputs`, estop | aux output n (1-4), -10.500 to 10.500 V |
| `OAUX? <n>` | `aux_in_1..4` | aux input n (1-4) in volts |
| `AGAN` | `auto_gain` | auto gain (sensitivity) |
| `APHS` | `auto_phase` | auto phase |

Sensitivity index (SENS), voltage inputs: 0 2 nV, 1 5 nV, 2 10 nV, 3 20 nV, 4 50 nV, 5 100 nV,
6 200 nV, 7 500 nV, 8 1 uV, 9 2 uV, 10 5 uV, 11 10 uV, 12 20 uV, 13 50 uV, 14 100 uV, 15 200 uV,
16 500 uV, 17 1 mV, 18 2 mV, 19 5 mV, 20 10 mV, 21 20 mV, 22 50 mV, 23 100 mV, 24 200 mV,
25 500 mV, 26 1 V. For current inputs read nV as fA and V as uA.

Time constant index (OFLT): 0 10 us, 1 30 us, 2 100 us, 3 300 us, 4 1 ms, 5 3 ms, 6 10 ms,
7 30 ms, 8 100 ms, 9 300 ms, 10 1 s, 11 3 s, 12 10 s, 13 30 s, 14 100 s, 15 300 s, 16 1 ks,
17 3 ks, 18 10 ks, 19 30 ks.

SR810: same command set, single-phase (no Y; `OUTP? 2` is not meaningful).

SR860 / SR865A differences (from the SR860 manual, not implemented here): `OUTP? 0..3` is
X, Y, R, theta (zero-based); sensitivity is `SCAL <n>` with a different table (0 is 1 V, 27 is
1 nV, inverted); time constant `OFLT` has 22 entries; aux outputs are `AUXV <n>,<v>` with n 0-3;
no `OUTX`. A package for them needs its own descriptor.

Unverified (not checked on an instrument):

- Reply terminator: the SR830 manual describes CR LF on RS-232; the package reads to LF and
  strips, which parses either way. Sending LF alone as the command terminator is what
  pymeasure does; the manual also accepts CR.
- RS-232 stop bits: the manual lists the SR830's RS-232 as 8 data bits, no parity; whether the
  generic route's 1 stop bit matters was not tested.
- `AUXV?` reply precision (the twin answers three decimals).
