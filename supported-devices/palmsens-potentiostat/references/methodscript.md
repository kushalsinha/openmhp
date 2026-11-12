# MethodSCRIPT as used by this package

Sources read: PalmSens `MethodSCRIPT_Examples` on GitHub (MIT; `Example_Python/Example_Python/palmsens/instrument.py`,
`mscript.py`, `serialport.py`; `MethodSCRIPTs/Measurement_Loops/MSLoopExample001-LSV.mscr`, `004-CV.mscr`,
`008-CA.mscr`, `011-OCP.mscr`, MethodSCRIPT version 1.8, dated 10/11/2025), and the MethodSCRIPT manual
(www.palmsens.com/msmanual) for the meaning of the commands. Nothing was copied; the tables are in our words.

## Link

| Item | Value |
|---|---|
| Transport | USB virtual COM port, 8N1, newline `\n` |
| Baud | 230400 EmStat Pico / Sensit; 921600 EmStat4 / Nexus (`serialport.py`) |
| Port description (Windows) | `EmStat4`, `ESPicoDev...`, `SensitBT...`, `USB Serial Port` (`serialport.py`) |

## Commands sent

| Sent | Meaning | Reply |
|---|---|---|
| `t\n` | firmware/version string | two lines: the first starts with `t`, the second ends with `*`; the device type is the prefix (`espico`, `es4_lr`, `es4_hr`, `senswb`, `nexus1`, `mes4hr`, `mes4lr`) |
| `e\n` + script lines + `\n` | execute a script now | the device echoes `e`, streams `M`, `P`, `*`, `+`, `-` lines, then a blank line when the script has ended |
| `\nZ\n` | abort the running script | `Z` when a script was running (then its output ends with a blank line), `Z!0006` when nothing was running |
| `!hhhh` (received) | a MethodSCRIPT error with a 4-hex-digit code; reading stops | |

Not used: `L...` (store a script), `r` (run the stored script), `v` (MethodSCRIPT version), `i` (serial number).

## Script lines built by `build_script`

| Line | From | Note |
|---|---|---|
| `var p`, `var c`, `var t` | all examples | potential, current, timer variables |
| `set_pgstat_chan 0` | all examples | single channel |
| `set_pgstat_mode 2` (ca) / `3` (cv, lsv, ocp) | examples 008 / 001, 004, 011 | the examples' choice: low-speed for CA, high-speed for sweeps and OCP. Unverified that these are the best modes for every device; they are the ones the vendor ships |
| `set_max_bandwidth 40` | examples use 60 | 40 Hz chosen here; the examples use 60 |
| `set_range_minmax da <lo> <hi>` | examples | applied-potential range |
| `set_range ba <max>`, `set_autoranging ba 1n <max>` | examples | current range and autoranging up to `current_range_max_A` |
| `set_range ab 4`, `set_autoranging ab 4 4` (ocp only) | example 011 | copied verbatim from the OCP example; the meaning of `4` for the `ab` range is unverified |
| `set_e <E>`, `cell_on` | examples | cell on at the start potential (not for ocp, which runs with the cell off) |
| `timer_start`, `timer_get t` | examples 008, 011 | elapsed-time variable in every package |
| `meas_loop_ca p c E interval run_time` | example 008 | |
| `meas_loop_cv p c E_begin E_vtx1 E_vtx2 E_step scan_rate nscans(n)` | example 004 | |
| `meas_loop_lsv p c E_begin E_end E_step scan_rate` | example 001 | |
| `meas_loop_ocp p interval run_time` | example 011 | |
| `pck_start` / `pck_add t`, `pck_add p`, `pck_add c` / `pck_end` | examples | one package per loop iteration |
| `endloop`, `on_finished:`, `cell_off` | examples | the cell goes off however the script ends |

Numbers are written as integers with an SI prefix (`500m`, `12500u`); whether the firmware also accepts
decimals was not checked, so the driver never emits one.

## Data packages

A `P` line holds variables separated by `;`. Each variable is a 2-character type, 7 hex digits of the value
offset by 2^27 (so negative values are representable), one SI prefix character (`a f p n u m ' ' k M G T P E`,
plus `i` for an integer), optionally followed by `,` metadata fields: a 2-character field starting with `1`
is the status (bit 1 timing error, 2 overload, 4 underload, 8 overload warning), a 3-character field starting
with `2` is the current range index. `     nan` in the value field means NaN. (`mscript.py`.)

Variable types read here: `ab` WE vs RE potential (V), `ba` WE current (A), `da` applied potential (V),
`eb` time (s). Lines starting with `M` (measurement loop start, 4 hex digits), `*` (loop end), `+`/`-`/`L`/`C`
(nested loop and scan markers) and the `e` echo are ignored.

## Unverified

- `!0001` as the twin's reply to an unknown command: the real error code for an unknown command was not
  looked up in the manual; the driver treats any `!hhhh` line as an error regardless of code.
- Whether the device echoes `e` before the data (the twin does; the driver ignores it either way).
- The instrument potential and current ranges quoted in `descriptor.yaml` notes (EmStat Pico, EmStat4 LR/HR)
  are placeholders from memory of the vendor sheets.
