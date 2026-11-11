# SCPI commands used by the rigol-oscilloscope package

Source: Rigol DS1000Z Series Digital Oscilloscope Programming Guide, document PGA18 (Rigol
Technologies; chapter 2 "Command system": `:ACQuire`, `:CHANnel<n>`, `:MEASure`, `:TIMebase`,
`:TRIGger`, `:RUN/:STOP/:SINGle/:AUToscale`), cross-checked against the command names in the
MIT-licensed `ds1054z` Python package. Commands end with LF; queries answer one line; writes
answer nothing.

| Command | Used for | Meaning |
|---|---|---|
| `*IDN?` | probe | `RIGOL TECHNOLOGIES,DS1054Z,<serial>,<firmware>` |
| `:RUN`, `:STOP`, `:SING` | `run`, `stop`, `single` | acquisition control |
| `:AUT` | `autoset` | autoscale; rewrites channel, timebase and trigger settings |
| `:TRIG:STAT?` | `trigger_status` | `TD`, `WAIT`, `RUN`, `AUTO` or `STOP` |
| `:CHAN<n>:DISP ON\|OFF\|1\|0` / `?` | `ch1_display` | channel on screen; query answers `0`/`1` |
| `:CHAN<n>:SCAL <v>` / `?` | `ch1_scale_v`, `ch1_scale_actual` | vertical scale per division; 1 mV to 10 V at 1X, snapped to 1-2-5 |
| `:CHAN<n>:OFFS <v>` / `?` | `ch1_offset_v`, `ch1_offset_actual` | vertical offset; ±2 V below 500 mV/div, ±100 V above |
| `:TIM:SCAL <s>` / `?` | `timebase_s`, `timebase_actual` | main timebase per division, 5 ns to 50 s |
| `:TRIG:EDG:SOUR CHAN<n>\|EXT\|AC` / `?` | `trigger_source` | edge trigger source (D0..D15 on an MSO) |
| `:TRIG:EDG:LEV <v>` / `?` | `trigger_level_v` | edge trigger level, about ±5 divisions of the source scale |
| `:MEAS:ITEM? <item>,<source>` | `vpp_ch1`, `vmax_ch1`, `vmin_ch1`, `vrms_ch1`, `freq_ch1`, `period_ch1`, `measure` | an automatic measurement; `9.9E37` when it cannot be made |
| `:ACQ:SRAT?` | `sample_rate` | current sample rate, Sa/s |
| `:SYST:ERR?` | `last_error` | oldest error, `0,"No error"` when empty |
| `:WAV:DATA?` | (not used) | waveform data as a binary block; not expressible here |

Measurement items (programming guide, `:MEASure:ITEM`): VMAX, VMIN, VPP, VTOP, VBASe, VAMP,
VAVG, VRMS, OVERshoot, PREShoot, MARea, MPARea, PERiod, FREQuency, RTIMe, FTIMe, PWIDth,
NWIDth, PDUTy, NDUTy, RDELay, FDELay, RPHase, FPHase, TVMAX, TVMIN, PSLEWrate, NSLEWrate,
VUPper, VMID, VLOWer, VARIance, PVRMS, PPULses, NPULses, PEDGes, NEDGes. The package's
`measure` enum carries the ten most used; extend it in descriptor.yaml for the others.

Unverified (not checked on an instrument):

- Whether `:TRIG:STAT?` answers `TD` exactly or `TD` with a trailing space on all firmware
  (replies are stripped either way).
- Whether `:CHAN<n>:DISP` accepts `1`/`0` as well as `ON`/`OFF` (the guide lists
  `{{1|ON}|{0|OFF}}`, so both should work; the driver sends `1`/`0`).
- `:SYST:ERR?` on the DS1000Z: the guide lists it under `:SYSTem`; the exact text of
  `No error` was not checked.
- The DHO800/900 `:MEAS:ITEM?` reply format for an invalid measurement (the DS1000Z's 9.9E37).
