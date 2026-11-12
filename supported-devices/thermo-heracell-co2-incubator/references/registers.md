# Register reference: Heracell VIOS 160i / 250i (TEMPLATE, unverified)

**Status of this map: every address below is a placeholder. None was read from a Thermo
Modbus document.** Confirm every address, register kind, data type and scale against the
controller's Modbus document (or the configuration of the gateway you put in front of the
incubator) before the first hardware use, and rewrite the `modbus:` block of descriptor.yaml
to match.

## What Thermo actually documents

Source read: *Thermo Scientific HERACELL VIOS 160i / HERACELL VIOS 250i User Manual*,
document 50162755, March 2020, chapter 12 "Data Communication" and chapter 11
"Specifications" (the 2021 CR-model manual 50163129 Rev. B has the same chapter). It describes:

- A USB port (virtual COM port, 9,600–57,600 baud) and an RS-232 option carrying an **ASCII
  request/reply protocol, not Modbus**: query `?:aaaa:bb::cc<CR>`, reply `!:aaaa:bb:data:cc<CR>`,
  where `aaaa` is a four-digit parameter address, `bb` the payload length in hex and `cc` a
  CRC8-CCITT (polynomial 0x07) checksum of everything before it. Lower-case only. Error replies
  carry `?0` (frame/checksum), `?1` (unknown parameter), `?2` (memory), `?3` (value out of limits).
- The parameter addresses, which are what the signals of this package stand for:

| ASCII address | Meaning (my words) | Format |
|---|---|---|
| 0001 | mainboard firmware version | 8 chars |
| 0010 / 0011 / 0012 | date and time, date, time | text |
| 2000 | device status and the error status of the temperature, CO2, O2, rH and reference-temperature loops | 33 hex chars |
| 2010 | temperature setpoint, actual and reference-sensor values | `+xxx.xx;+xxx.xx;+xxx.xx` |
| 2020 | CO2 setpoint and actual | `+xxx.xx;+xxx.xx` |
| 2030 | O2 setpoint and actual | `+xxx.xx;+xxx.xx` |
| 204a | water level (100 % or 0 %) | `+xxx.xx` |
| 204b | low-humidity indicator (1 active) | hex byte |
| 2100 / 2105 | Steri-run and auto-start status, remaining time, last start | text |
| 2140 / 2141 | gas cylinder changeover status, CO2 and O2 | hex byte |
| 2300 / 2301 | error log, current and older entries | 22 records |
| 2400–2410 | data logger | records |

The manual does not list a door-contact parameter: the door switch suspends gas supply and
heating and raises an alarm after 30 s, and its state would have to come out of the status
word at 2000, whose bit layout I did not have. There is no automation or robot interface in the
manual. The 4-20 mA option outputs temperature, CO2, O2 and rH as analogue currents.

Ranges used for the limits (chapter 11): temperature control range RT + 3 … 55 °C (package
placeholder 20–50); CO2 0–20 %; O2 control range I 1–21 % (range II 5–90 % with the other
sensor). Setting CO2 to 0 % deactivates the CO2 loop (chapter 6).

Because the declarative serial driver cannot compute the CRC8, the honest hardware routes are
(a) a Modbus TCP/RTU map on the controller or on a gateway that speaks the ASCII protocol to
the incubator, which is what this package is written for, or (b) a `SerialAsciiDriver` subclass
in driver.py that adds the checksum: a later revision of this package may ship (b).

## Placeholder Modbus map used by descriptor.yaml

All rows **unverified**. Values are assumed to be signed 16-bit integers in hundredths (the
ASCII protocol reports two decimals), big-endian, unit id 1, TCP port 502.

| Signal / setting | Kind | Address | Type, scale | Meaning | Verified |
|---|---|---|---|---|---|
| temperature | input | 0 | int16 × 0.01 °C | chamber temperature actual | unverified |
| co2 | input | 1 | int16 × 0.01 % | CO2 actual | unverified |
| o2 | input | 2 | int16 × 0.01 % | O2 actual (O2 units only) | unverified |
| humidity | input | 3 | int16 × 0.01 % | relative humidity actual (rH-sensor units only) | unverified |
| temperature_setpoint(_actual) | holding | 100 | int16 × 0.01 °C | temperature setpoint, read and write | unverified |
| co2_setpoint(_actual) | holding | 101 | int16 × 0.01 % | CO2 setpoint, read and write; 0 = loop off | unverified |
| o2_setpoint(_actual) | holding | 102 | int16 × 0.01 % | O2 setpoint, read and write | unverified |
| door_closed | discrete | 0 | bit | door contact, 1 = closed | unverified |
| alarm_active | discrete | 1 | bit | any controller alarm | unverified |

No coil is mapped: the manual documents no standby, heater-off or alarm-acknowledge command,
which is why `safety.estop` is false. If the controller's Modbus document has one, add it to
`modbus.estop` and set `safety.estop: true`.
