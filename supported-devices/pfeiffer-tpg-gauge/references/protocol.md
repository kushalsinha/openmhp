# Pfeiffer TPG mnemonic protocol, as used by this package

Sources read: Pfeiffer Vacuum "TPG 366 Communication Protocol", BG 5511 BEN (2017/2018, firmware V010100); "TPG 361/362 Communication Protocol", BG 5510 BEN/D (2018-08, firmware V010400); "TPG 262 Operating Instructions", BG 5196 BEN/B (2013-12), chapter 5 "RS232C interface", which states the TPG 261 and 262 share the same protocol; "TPG 261 Operating Instructions", BG 805 195 BE/B (2004). Cross-checked against the open-source drivers in InstrumentKit (`pfeiffer/tpg36x.py`), PyExpLabSys (`drivers/pfeiffer.py`) and socs (`pfeiffer_tpg366`). No manual text is reproduced; the table is in our words.

## Framing and handshake

| Step | Bytes | Notes |
|---|---|---|
| Host sends a command | `<mnemonic>[,param,...]<CR><LF>` | LF optional (do not send it on RS-485). `<ETX>` clears the input buffer. 8N1, no hardware handshake. |
| Controller acknowledges | `<ACK><CR><LF>` (0x06) or `<NAK><CR><LF>` (0x15) | The host must wait for this before anything else. The generic serial driver's `enq:` option does this. |
| Host asks for the data | `<ENQ>` (0x05), no CR/LF | |
| Controller answers | `<data><CR><LF>` | A bare ENQ with no valid request pending returns the error word. |

A command with parameters is a set (ACK only; a following ENQ returns the new value); the same mnemonic without parameters is a query. The controller streams measurements once a second at power-up until it receives any character. Baud is selectable with `BAU` (0 = 9600 default, 1 = 19200, 2 = 38400; 36x USB adds 3 = 57600, 4 = 115200; RS-485 is fixed at 9600).

## Commands this package uses

| Mnemonic | Parameters (set) | Data after ENQ | Meaning |
|---|---|---|---|
| `PRn` (n = 1..2, up to 6 on a 366) | none | `a,sx.xxxxEsxx` | Status a and pressure of channel n in the configured unit. Status: 0 ok, 1 underrange, 2 overrange, 3 sensor error, 4 sensor off, 5 no sensor, 6 identification error. With no sensor the value is a dummy `2.0000E-02`. |
| `PRX` | none | `a,value,b,value[,...]` | Status/value pairs for all channels (2 on 362/26x, 6 on 366). A 361's reply length: unverified. |
| `UNI` | `0` mbar/bar, `1` Torr, `2` Pa, `3` micron, `4` hPa, `5` V (26x: 0..2 only) | one digit | Pressure unit for all values. 36x default 4 (hPa), 26x default 0 (mbar). |
| `TID` | none | per-channel tokens | Gauge head identification. 36x: `TPR/PCR`, `IKR`, `PKR`, `PBR`, `IMR`, `CMR/APR`, `noSENSOR`, `noIDENT`. 26x: `TPR`, `IKR9`, `IKR11`, `PKR`, `PBR`, `IMR`, `CMR`, `noSEn`, `noid`. |
| `SEN` | one value per channel: 0 no change, 1 off, 2 on (366: exactly six values) | per channel: 0 cannot be switched, 1 off, 2 on | Switch gauge heads on or off. Only IKR, PKR, IMR, PBR heads can be switched. |
| `DGS` | one value per channel: 0 off, 1 on (3 min) | per-channel degas state | Degas of a hot-cathode head. |
| `ERR` | none | `0000` none, `1000` controller error, `0100` no hardware, `0010` bad parameter, `0001` syntax error | Error word; cleared by reading. |
| `AYT` | none | `type,article,serial,firmware,hardware` | Identification. 36x only; a 26x NAKs it. |

Not used but relevant: `COM,a` (continuous output every 100 ms / 1 s / 1 min; any character stops it), `SCx` (switch-on and switch-off control of channel x, the controller-side gauge interlock), `PUC` (underrange control), `RES,1` (reset errors), `BAU`, `NAD` (RS-485 address 1..24, selected with `<ESC>nn`), `ETH` (36x IP settings).

## Number format

`sx.xxxxEsxx`: sign, one digit, four decimals, `E`, signed two-digit exponent, e.g. `+1.2345E-03`, in the unit selected with `UNI`. Logarithmic heads (Pirani, cold cathode, Bayard-Alpert) report the third and fourth decimals as 0. The 36x `FMT` parameter is documented as a display/output number format; whether it changes the serial format is unverified, so the driver parses the first finite number rather than a fixed layout.

## How the signals are parsed

`pressure_n` is field 2 and `status_n` field 1 of the `PRn` reply (parse rules in descriptor.yaml). `SEN` writes are formatted by driver.py: a boolean `true` becomes 2, `false` becomes 1, so `sensor_1_on: false` sends `SEN,1,0`.

## Unverified

- The TCP port for the 36x Ethernet route (8000 in third-party drivers; no Pfeiffer document read states it).
- Whether the controller refuses `SEN,...,2` on a hot-cathode head at high pressure or accepts it and lets the head's own protection act.
- The exact `PRX` reply of a one-channel TPG 361, and what a TPG 261 answers for channel 2.
- That the controller never echoes characters (implied by the manuals, not stated).
