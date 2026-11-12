# GamryCOM objects and calls used by this package

## Sources

- Gamry Instruments, *Gamry Electrochemistry Toolkit* brochure, Rev 1.0, 8/31/2018: the Toolkit is a set
  of COM interfaces; lists IGamryDeviceList, IGamryPstat, the Dtaq interfaces (IGamryDtaqIv, Ocv, Univ, Cpiv,
  Ciiv, Galv, Chrono, Ivt, Pv, Rcv, Sqwv, Eis) and IGamryReadZ, the Signal interfaces (Array, Const, Step,
  Ramp, Dstep, Mstep, Pv, Rupdn, Updn, Sqwv); a worked example `myPstat.Init("REF600-007")`, `Open`,
  `SetCell(CellOn)`, `SetCell(CellOff)`, `Close`; requires Windows and a Reference/Interface instrument;
  examples ship for LabVIEW, VBA and C++ with a reference manual (PDF) in the install.
- Gamry Instruments, application note *Steps for Creating an Application Using GamryCOM* (March 2015):
  create the device list, wait about 3 s, `EnumSections()`; create the Pstat, `Init(section)`, `Open()`;
  create a Dtaq and `Init` it with the Pstat; create a Signal and `Init` it with the Pstat and its
  parameters; `pstat.SetSignal(signal)`; `dtaq.Run()`; collect with `Cook(count)` (a 2-D array) or the
  `OnDataAvailable` / `OnDataDone` callbacks; finish with `OnDataDone` or `Stop()`; the GamryCOM error
  code table.
- A published Python example (a university research-group blog, 2015) driving a Reference 600 through
  `win32com.client.Dispatch("GamryCOM.GamryDeviceList")`, `GamryCOM.GamryPstat`, `GamryCOM.GamryDtaqCpiv`
  and `GamryCOM.GamrySignalRamp`: `pstat.Init(section)`, `Open()`, `dtaq.Init(pstat)`,
  `signal.Init(pstat, Sinit, Sfinal, ScanRate, SampleRate, CtrlMode)`, `pstat.SetSignal(signal)`,
  `pstat.SetCell(1)` (with the comment that 1 is `GamryCOM.CellOn`), `dtaq.Run(True)`,
  `count, points = dtaq.Cook(10)` in a loop, `pstat.Close()`.
- Gamry's current pages name a newer *Echem ToolkitPy* (Python 3.7 32-bit `.pyd` modules) as an
  alternative to COM; this package uses the COM route because the Toolkit brochure and the Python example
  document it. The Toolkit is a licensed option of the Framework.

## Calls used

| Step | Call | Source | Verified |
|---|---|---|---|
| list instruments | `Dispatch("GamryCOM.GamryDeviceList").EnumSections()` | app note, Python example | yes |
| open | `Dispatch("GamryCOM.GamryPstat")`, `Init(section)`, `Open()` | brochure, app note, example | yes |
| cell switch | `pstat.SetCell(1)` on, `SetCell(0)` off | brochure (CellOn/CellOff), example (1 = CellOn) | names yes; 0 = CellOff by analogy, **unverified** |
| close | `pstat.Close()` | brochure, example | yes |
| OCP | `GamryDtaqOcv.Init(pstat)`; `GamrySignalConst.Init(pstat, 0.0, duration_s, sample_s, PstatMode)` | interface names from the brochure | **argument lists unverified** |
| CA | `GamryDtaqChrono.Init(pstat, 0)` (0 = ChronoAmp); `GamrySignalConst.Init(pstat, e_V, duration_s, sample_s, PstatMode)` | brochure | **argument lists unverified** |
| CV | `GamryDtaqRcv.Init(pstat)`; `GamrySignalRupdn.Init(pstat, Vinit, Vap1, Vap2, Vfinal, ScanRate, HoldTime0, HoldTime1, HoldTime2, SampleRate, Cycles, PstatMode)` | brochure | **argument list unverified** (modelled on the Ramp signature of the example) |
| attach, run | `pstat.SetSignal(signal)`, `dtaq.Run(True)` | app note, example | yes |
| collect | `count, points = dtaq.Cook(1024)`; columns per Dtaq (Chrono: Time, Vf, Vu, Im, ...; Rcv: Time, Vf, Vu, Im, ...; Ocv: Time, Vf, ...) | example (shape), column order **unverified** (config `cook_columns`) | partly |
| stop | `dtaq.Stop()` | app note | yes |
| EIS | `GamryReadZ.Init(pstat)`, `pstat.SetVoltage(e_dc)`, `readz.Measure(f, amplitude)`, then `Zfreq()`, `Zreal()`, `Zimag()` | interface name from the brochure | **members and the polling after Measure unverified** (the Toolkit signals completion through an event; the driver polls) |
| control mode | `PstatMode` = 1 | example (CtrlMode default 1 with a comment naming GamryCOM.PstatMode) | **value unverified** |

Things the Toolkit reference manual settles and the first hardware test must confirm: each `Init`
signature, whether `Cook` returns `(count, points)` with points as columns, the column order per Dtaq,
the `ReadZ` members and whether `Measure` blocks, and whether the current range must be set
(`SetIERange`) before a technique on the Interface 1010.

## Units and ranges

Potentials in volts vs the cell's reference, currents in amperes as the Toolkit reports `Im`. The
+/-1.5 V bounds on every potential parameter are placeholders (the Interface 1010 applies up to +/-12 V,
the Reference 620 up to +/-11 V with higher compliance); the lab sets what its cell tolerates.

## Twin

The twin answers the same backend calls with a dummy cell (Rs 200 ohm, Rct 2 kohm, Cdl 20 uF, open-circuit
12 mV): CA gives a current step with a 3.6 ms transient, CV a resistive line plus the capacitive offset
proportional to the scan rate, EIS the Randles semicircle from Rs to Rs + Rct. Each EIS point takes three
periods (at least 0.2 s), all scaled by `OPENMHP_SIM_TIME_SCALE`.
