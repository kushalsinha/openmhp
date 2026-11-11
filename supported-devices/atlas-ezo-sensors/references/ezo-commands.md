# EZO UART commands used by this package

Primary sources read: Atlas Scientific "EZO-DO Embedded Dissolved Oxygen Circuit" datasheet, V 5.8,
revised 3/25 (files.atlas-scientific.com/DO_EZO_Datasheet.pdf); "EZO-RTD" datasheet, V 3.7, revised
10/24 (files.atlas-scientific.com/EZO_RTD_Datasheet.pdf). Secondary: the LabMCP `atlas-ezo-sensors`
README at github.com/K-Dense-AI/lab-instrument-mcps (Apache-2.0), which cites the pH V 6.1, ORP V 5.2
and EC V 6.7 datasheets that could not be read here.

UART (DO and RTD datasheets): 9600 baud default, 8 data bits, no parity, 1 stop bit; commands are not
case sensitive and end with CR; replies end with CR; `*OK` follows every reply while response codes are
enabled (`*OK,0` disables them and the setting is retained); `*ER` unknown command; `*RS`, `*RE`, `*SL`,
`*WA` (reset, ready, sleeping, woke) cannot be disabled. Continuous mode `C,<n>` is retained; `C,0` off.
A reading takes about 1 s (DO datasheet: 600 ms reading time, 1000 ms shown for R).

| Command | Circuits | Meaning | Reply | Used as |
|---|---|---|---|---|
| `R` | all | single reading | `<value>` (DO: `mg/L[,%sat]`; EC: `EC[,TDS,SAL,SG]`; RTD: degrees, `-1023.000` no probe) | signals `ph`, `orp`, `dissolved_oxygen`, `conductivity`, `temperature` |
| `Cal,?` | all | is the device calibrated | `?Cal,0` none; `?Cal,1`, `?Cal,2` (DO: one, two points); RTD `?Cal,0|1` | signal `calibrated` |
| `Cal` | DO | atmospheric-oxygen point | `*OK` | action `calibrate_do_atmospheric` |
| `Cal,0` | DO | zero-oxygen point | `*OK` | action `calibrate_do_zero` |
| `Cal,<t>` | RTD | single point at temperature t | `*OK` | action `calibrate_rtd` |
| `Cal,clear` | all | delete calibration | `*OK` | action `clear_calibration` |
| `Cal,mid,<pH>` / `Cal,low,<pH>` / `Cal,high,<pH>` | pH | one-, two-, three-point calibration, mid first | `*OK` | action `calibrate_ph` (unverified: pH datasheet not read; ranges mid 6-8, low 0-6.5, high 7.5-14 from the LabMCP README) |
| `Cal,<mV>` | ORP | single point | `*OK` | action `calibrate_orp` (unverified: ORP datasheet not read) |
| `Cal,dry` / `Cal,one,<uS>` / `Cal,low,<uS>` / `Cal,high,<uS>` | EC | dry first, then one or low/high | `*OK` | action `calibrate_ec` (unverified: EC datasheet not read; the action sends `Cal,dry,0` for dry, which may be refused) |
| `T,<temp>` | pH, DO, EC | temperature compensation, degrees C, not retained | `*OK` | setting `temperature_compensation` |
| `T,?` | pH, DO, EC | compensation in use | `?T,<temp>` | signal `temperature_compensation_actual` |
| `RT,<temp>` | DO (firmware 2.13+) | compensate and read | reading | not used |
| `i` | all | device information | `?i,<type>,<firmware>` | signal `circuit_info` |
| `Status` | all | restart reason and Vcc | `?Status,<P|S|B|W|U>,<volts>` | signal `status_text` |
| `L,1` / `L,0` / `L,?` | all | LED on / off / query | `*OK`; `?L,1|0` | actions `led_on`, `led_off` |
| `C,0` | all | continuous readings off | `*OK` | action `configure_for_polling` |
| `*OK,0` | all | response codes off (retained) | none | action `configure_for_polling` |
| `Sleep`, `Factory`, `Find`, `Baud,<n>`, `Plock`, `Name`, `Export`/`Import` | all | sleep, factory reset, blink, baud, protocol lock, name, calibration export | various | not exposed |
| `S,c|k|f` | RTD | temperature scale | `*OK` | not used (Celsius assumed) |
| `P,<kPa>`, `S,<ppt>` | DO | pressure and salinity compensation | `*OK` | not used |

Ranges: DO 0.00-100 mg/L, 0-350 % saturation (DO datasheet); RTD -126.000 to 1254 degC (RTD datasheet);
pH 0.001-14.000, ORP -1019.9 to 1019.9 mV, EC 0.07-500,000 uS/cm (LabMCP README, unverified here).

Unverified: everything marked above; the default compensation temperature of the pH and EC circuits (the
DO circuit's is 20 degC per its datasheet); whether the pH circuit answers `?Cal,3` for three points.
