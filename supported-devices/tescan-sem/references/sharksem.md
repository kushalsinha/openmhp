# SharkSEM functions used (TESCAN remote control): template

Sources: TESCAN product pages for VEGA (remote control over TCP/IP as a standard feature; "automate
... with Python API") and the TESCAN VEGA3 user manual's "Remote Control" chapter heading, which
confirm that the interface exists and is TCP based; a TESCAN conference abstract (EIPBN 2023) names the
SharkSEM Automation Toolbox SDK. The SharkSEM manual itself is distributed to customers and was not
readable, and no permissively licensed open-source client was found. Public example scripts show a
`sem` module with a `Sem` class, `Connect(host, port)` to the microscope PC on a port in the 8300
range and function names of the form `VacGetStatus`, `ScSetSpeed`, `ScScanXY`, `ScStopScan`,
`SetViewField`, `DtSelect`, `DtEnable`; those scripts carry no licence, so this package takes from
them only the naming scheme and marks every function unverified.

| Function (config key) | Assumed meaning and arguments | Used by |
|---|---|---|
| `sem.Sem()`, `Connect(host, port)` (`client`, `connect`) | open the TCP session; a negative return is failure | connected |
| `Disconnect()` | close it | close |
| `VacGetStatus()` (`vac_status`) | vacuum state; assumed integer code 0 ready, 1 pumping, 2 venting, 3 vented, 4 error, or a word | vacuum_status, vacuum_ready, robot_access_ready |
| `VacPump()`, `VacVent()` | pump / vent the chamber | load_sample, unload_sample |
| `HVBeamOn()`, `HVBeamOff()`, `HVGetBeam()` | high voltage on / off / state | set_beam, beam_on, e-stop |
| `HVGetVoltage()`, `HVSetVoltage(volts)` | accelerating voltage in volts | high_voltage |
| `StgGetPosition()` -> (x, y, z, rotation, tilt) in mm and degrees; `StgMoveTo(x, y, z, rotation, tilt)`; `StgIsBusy()`; `StgStop()` | five-axis stage | stage_position, move_stage, e-stop |
| `SetViewField(mm)`, `GetViewField()` | view field width in mm; magnification = reference width / view field | acquire_image |
| `DtSelect(channel, detector)`, `DtEnable(channel, enable, bpp)` | route a detector (0 SE, 1 BSE assumed) into an acquisition channel | acquire_image |
| `AutoWD(channel)` | automatic working distance (focus) | auto_focus |
| `ScSetSpeed(index)` | scan speed 1-10 (dwell) | acquire_image |
| `ScScanXY(frame, width, height, x0, y0, x1, y1, single)` | scan one frame of the given size | acquire_image |
| `ScStopScan()` | stop scanning | cancel, e-stop |
| `FetchImage(channel, nbytes)` | the 8-bit frame as bytes | acquire_image |

## Unverified

Everything in the table: module and class names, every function name, the argument lists and their
order, the vacuum status codes and words, detector indices, whether the view field is in mm or um,
whether high voltage is in volts, and the port. The reference width used to convert magnification
(`reference_width_mm`, 120 by default) is a placeholder. The high-voltage range (0.2-30 kV) and the
stage travel limits in the descriptor are placeholders for the lab to replace. A wrong name fails the
call with a DeviceFault naming the function, never with a silent default.
