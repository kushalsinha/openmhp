# SmartSEM Remote API members used (ZEISS): template

Sources: ZEISS Microscopy Knowledge Base, "Installing Remote API Client (for SEM systems)" and
"Install SmartSEM Remote API Client on SEM (RRemote)" (the Remote API is a SmartSEM installer
component; a "SmartSEM API Test" desktop application exercises it; ZEN talks to SmartSEM through it);
ZEISS Research Microscopy Solutions, "ZEISS Remote API: customizing tool functionality using the
remote application programming interface" (2014; made-to-order API solutions, no member names). The
API reference itself is licensed and was not readable; no permissively licensed open-source client
was found. Everything below is the assumed shape.

| Member / name (config key) | Assumed meaning | Used by |
|---|---|---|
| COM ProgID `CZ.EMApiCtrl.1` (`progid`), created with pywin32 `Dispatch` | the remote API object | connected |
| `InitialiseRemoting()` (`initialise`), `ClosingControl()` (`close`) | start / end the session; 0 on success | connected, close |
| `Get(parameter)` (`get`), `Set(parameter, value)` (`set`), `Execute(command)` (`execute`) | read / write a named parameter, run a named command | everything below |
| `DP_VAC_STATUS` (`vac_status`) with words `Ready` (`vac_ready_word`) and `At atmosphere` (`vac_atm_word`) | vacuum state | vacuum_status, vacuum_ready, robot_access_ready |
| `CMD_PUMP`, `CMD_VENT` | pump / vent the chamber | load_sample, unload_sample |
| `DP_RUNUPSTATE` (`runup_state`) with word `On` (`runup_on_word`) | EHT run-up state | beam_on |
| `AP_ACTUALKV` (`actual_kv`), `AP_MANUALKV` (`manual_kv`) | EHT read / target in kV | high_voltage |
| `CMD_EHT_ON`, `CMD_EHT_OFF` | EHT on / off | set_beam, e-stop |
| `AP_STAGE_AT_X/Y/Z/R/T` (`stage_x` ...) in mm and degrees; `DP_STAGE_IS` (`stage_is`) with word `Busy` | stage position and motion state | stage_position, stage_busy |
| `MoveStage(x, y, z, t, r, m)` (`move_stage`) | absolute five-axis move (argument order assumed) | move_stage |
| `CMD_STAGE_STOP` | stop the stage | cancel, e-stop |
| `AP_MAG` (`mag`) | magnification | acquire_image |
| `DP_SCAN_RATE` (`scan_rate`) | scan speed index | acquire_image |
| `DP_DETECTOR_CHANNEL` (`detector`) with values `SE2`, `InLens`, `BSD` | detector for the grab | acquire_image |
| `CMD_AUTO_FOCUS` | auto focus | auto_focus |
| `Grab(x, y, width, height, reduction, filename)` (`grab`) | grab the frame into a TIFF (argument order assumed) | acquire_image |
| `CMD_FREEZE_ALL` | freeze the scan | cancel, e-stop |

## Unverified

Everything in the table: the ProgID, every member name and argument order, every parameter and
command name, the status words, whether stage positions are in mm, whether the EHT parameters are in
kV, the detector names, and whether `Grab` writes a TIFF of the requested size (the driver reads the
file back as an 8-bit single-strip TIFF to average frames, which assumes that). The EHT range
(0.02-30 kV) and the stage travel limits in the descriptor are placeholders for the lab to replace.
A wrong name fails the call with a DeviceFault naming the member, never with a silent default.
