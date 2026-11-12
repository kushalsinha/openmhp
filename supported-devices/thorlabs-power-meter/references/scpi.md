# SCPI commands used by the thorlabs-power-meter package

Source: Thorlabs PM100D Operation Manual, document 17654-D02 (section "Computer interface",
SCPI command reference) and the "PM100D / PM100A / PM100USB SCPI commands" summary that ships
with the Thorlabs Optical Power Monitor software; cross-checked against the command names in
the MIT-licensed ThorlabsPM100 Python package. Commands are SCPI over USBTMC, LF-terminated;
queries answer one line, writes answer nothing, errors go to the queue.

| Command | Used for | Meaning |
|---|---|---|
| `*IDN?` | probe | `Thorlabs,PM100D,<serial>,<firmware>` |
| `*RST`, `*CLS` | `reset` | defaults; clear status and error queue |
| `:MEAS:POW?` | `power`, `measure` | configure for power, trigger, fetch; watts |
| `:MEAS:TEMP?` | `temperature` | head temperature in degC where the head has a thermistor; errors otherwise |
| `:SENS:CORR:WAV <nm>` / `?` | `wavelength` | wavelength for the responsivity correction |
| `:SENS:AVER <n>` / `?` | `averaging` | averaging count (`SENSe:AVERage[:COUNt]`); about 3 ms per sample |
| `:SENS:POW:RANG:AUTO ON\|OFF` / `?` | `auto_range` | automatic power range |
| `:SENS:POW:RANG?` | `power_range` | upper limit of the active range, watts |
| `:SENS:CORR:COLL:ZERO:INIT` | `zero` | start a dark-current zero (photodiode heads) |
| `:INP:PDIO:FILT:LPAS:STAT ON\|OFF` / `?` | `low_bandwidth` | photodiode input low-pass filter |
| `:SYST:SENS:IDN?` | `sensor_head` | head name, serial, calibration message, type, subtype, flags |
| `:SYST:ERR?` | `last_error` | oldest error, `0,"No error"` when empty |

Model notes: PM100A is the analog-meter version with the same command set; PM100USB has no
display; PM400 adds `:SENS:POW:RANG:AUTO` and the same measurement commands plus
touch-screen features not used here.

Unverified (not checked on an instrument):

- Whether `:SENS:POW:RANG:AUTO` and `:INP:PDIO:FILT:LPAS:STAT` accept `1`/`0` as well as
  `ON`/`OFF` (the driver sends `1`/`0` for booleans; SCPI boolean parameters normally accept
  both).
- The averaging upper bound of 3000 (the manual's value for the PM100D; the PM400 may differ).
- The PM400 USB product id.
- `:MEAS:TEMP?` as the temperature query (the manual lists it for heads with a thermistor;
  the PM400 also has `:SENS:TEMP?`-style queries not used here).
