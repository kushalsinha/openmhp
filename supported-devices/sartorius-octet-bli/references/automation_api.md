# Octet automation interface (AutomationAPI.h, API 1.1)

Sources: ForteBio, "Octet System Data Acquisition User Guide", Release 11.0, Appendix A "Using
Octet384 and HTX Systems with an Automation Interface" (Octet RED384 = RH16, HTX = RH96); Sartorius,
"Octet BLI Discovery and Octet Analysis Studio Software (version 10)" datasheet (automation interface
over RS-232 or TCP/IP socket for RH16 and RH96). ASCII, one command per line ending in CR LF,
single-letter switches in any order, quoted values when they contain spaces; the reply starts with a
status token.

| Command | Meaning | Reply | Used by |
|---|---|---|---|
| `Version` | application, platform and API versions | e.g. `6.1.0.30 Pegasys 1.0` | connect, probe |
| `Status` | instrument state | `OK` ready; `Running (nn%)`; `Waiting`; `Busy` (resetting or presenting); `LoadSensors`; `Stopped`; `Error: <reason>` | status, robot_access_ready, run polling |
| `GetMethodInfo -m<method.fmf> [-p<plate file>]` | inspect a method | `OK -p<wells>,<wells> -t<sensor trays 0..5> -s<sensor type> -e<experiment type> -r<reracking>` or `Error: load method` / `Error: bad method` | run_experiment (sensors = -t) |
| `Run -m<method.fmf> [-p<plate file>] [-1 <sample barcode>] [-2 <reagent barcode>] [-l <sensor lot>] [-s silent] [-u use last sensor tray] [-f <data root>] [-e <experiment name>] [-v]` | start a method | `OK`, `Error: not ready`, `Error: bad method`, `Error: bad barcode` | run_experiment |
| `GetRunInfo` | where the experiment is | `OK -n"<experiment name>" -p"<UNC path>"` | run_experiment (file) |
| `Stop` | stop the run, eject sensors if needed (asynchronous) | `OK` | cancel, e-stop |
| `Present` | open the door and move the stage out for a robot (RH16/RH96) | `OK`, then Status Busy until done | plate_out |
| `Close` | close door and stage, home the read head | `OK` | plate_in |
| `Resume` | continue after Waiting / LoadSensors (new sensor tray in place) | `OK` | not used (multi-tray runs fail here) |
| `SetValue -t<DegC>` | plate heater setpoint (API 1.1) | `OK` | temperature_setpoint |
| `Reset` | stop anything running and reset the instrument | `OK` | not used |
| `Cleanup` | close MDI windows | `OK` | not used |

Temperature: R8 15-40 Cel in 1 Cel steps (Sartorius R8 page; DAQ guide spec table); RH16/RH96
ambient + 4 to 40 Cel, 1 Cel steps; default 25 Cel at startup. No command reads the temperature back.

## Unverified

- Which switch carries the sensor tray identifier: this package sends it as `-l` (sensor lot).
- The R8: Release 11.0 says the automation interface is for Octet384 systems only; the datasheet
  names RH16 and RH96. R8 support is not documented.
- The default TCP port (the Octet PC's option dialog sets it; no default is published).
- A .NET/COM "Octet Automation" library used by scheduler vendors was named but no public reference
  exists; this package does not use it.
