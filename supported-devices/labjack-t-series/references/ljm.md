# LJM calls and registers used by this package

Sources read (November 2026): github.com/labjack/labjack-ljm-python (MIT) examples `Examples/Basic/eReadNames.py`,
`Examples/More/Stream/stream_basic.py`, `Examples/More/List_All/list_all.py`, `Examples/More/DIO/single_dio_write.py`,
`Examples/More/AIN/single_ain_with_config.py`; the LJM User's Guide and the T-series datasheet (labjack.com) for
register meanings, from memory where noted.

| Call | Used for | Status |
|---|---|---|
| `ljm.openS("ANY", "ANY", identifier)` | open by serial, IP or ANY | verified |
| `ljm.getHandleInfo(handle)` -> (deviceType, connectionType, serialNumber, ipAddress, port, maxBytesPerMB) | identity | verified |
| `ljm.constants.dtT4 / dtT7 / dtT8` (4, 7, 8), `ctTCP`, `ctUSB`, `dtANY`, `ctANY` | device type names | verified in examples (numeric values from the LJM header, as remembered) |
| `ljm.numberToIP(n)` | IP string | verified |
| `ljm.eReadName(h, name)`, `ljm.eReadNames(h, n, names)` | signals, slow sampling | verified |
| `ljm.eWriteName(h, name, value)`, `ljm.eWriteNames(h, n, names, values)` | settings, e-stop | verified |
| `ljm.namesToAddresses(n, names)[0]` | stream scan list | verified |
| `ljm.eStreamStart(h, scansPerRead, numAddresses, aScanList, scanRate)` -> actual rate | fast sampling | verified |
| `ljm.eStreamRead(h)` -> (aData, deviceScanBacklog, ljmScanBacklog) | stream blocks, interleaved by channel | verified |
| `ljm.eStreamStop(h)` | end of stream | verified |
| `ljm.listAll(dtANY, ctANY)` -> (numFound, aDeviceTypes, aConnectionTypes, aSerialNumbers, aIPAddresses) | `discover("devices")` | verified (the example calls `listAllS("ANY", "ANY")`; `listAll` appears commented with the same tuple) |
| `ljm.close(h)` | close | verified |

Registers: `AIN0`..`AIN3` (V), `DAC0`, `DAC1` (0-5 V), `FIO0`..`FIO3` (write 0/1 makes the line an output),
`DIO_STATE` (bitmask of all DIO; from the LJM register map, as remembered), `AIN0_RANGE` (T7: 10, 1, 0.1, 0.01;
T8: 11 and its own table per `single_ain_with_config.py`; T4: no range register for AIN0-3), `SERIAL_NUMBER`,
`PRODUCT_ID`, `FIRMWARE_VERSION`.

Unverified:

- The LJM error code and text for an unknown register name (the twin answers `LJM_ERROR 1239 (LJME_INVALID_NAME)`).
- Whether `AIN0_RANGE` on a T8 accepts the T7 values (the datasheet lists +/-11, +/-9.6 ... V); the driver sends
  the value as given and reports the device's refusal.
- The exact `DIO_STATE` bit layout for the upper lines (only bits 0-3, FIO0-FIO3, are relied on).
