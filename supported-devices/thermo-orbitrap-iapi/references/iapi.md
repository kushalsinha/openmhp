# Thermo IAPI members used by this package

Sources read (November 2026): github.com/thermofisherlsms/iapi (MIT) `GettingStarted.md`,
`examples/tribrid/MinifiedExample/Program.cs`, `examples/tribrid/AdvancedConsoleApplication/Program.cs`,
`examples/tribrid/scan-handler/InstrumentHandler.cs` and `lib/ThermoApi.cs`, `examples/tribrid/fusion-example-client/IAPIFusionCustomScan.cs`.
The IAPI reference itself (`docs/tribrid/Help/IAPI Documentation.chm`) was not read.

Assemblies: `Thermo.TNG.Factory.dll`, `API-2.0.dll`, `Fusion.API-1.0.dll` (Tune 4.2 and earlier; `Fusion.API-2.0.dll` for 4.3),
`Spectrum-1.0.dll` is listed too but not referenced here. Namespaces: `Thermo.TNG.Factory`, `Thermo.Interfaces.FusionAccess_V1`,
`Thermo.Interfaces.FusionAccess_V1.MsScanContainer`, `Thermo.Interfaces.InstrumentAccess_V1.MsScanContainer`,
`Thermo.Interfaces.InstrumentAccess_V1.Control.Scans`.

| Member | Used for | Status |
|---|---|---|
| `Factory<IFusionInstrumentAccessContainer>.Create()` | connect | verified (GettingStarted, examples) |
| `container.StartOnlineAccess()`, `container.ServiceConnected` | connect, wait | verified |
| `container.Get(1)` -> `IFusionInstrumentAccess` | instrument handle | verified |
| `access.Control` -> `IFusionControl` | control | verified |
| `control.Acquisition` -> `IAcquisition` | state | verified (AdvancedConsoleApplication, InstrumentHandler) |
| `acq.State.SystemState` (`InstrumentState` enum: Running seen) | `instrument_state` | verified (InstrumentHandler) |
| `acq.State.SystemMode` | `acquisition_state` | **unverified** |
| `acq.StateChanged`, `AcquisitionStreamOpening/Closing` events | not used | seen in InstrumentHandler |
| `control.GetScans(false)` -> `IScans` | custom scans | verified (`GetScans(true)` and `(false)` both appear) |
| `scans.CreateCustomScan()` -> `ICustomScan` | custom scan | verified |
| `cs.Values[key] = value` (strings) | parameters | verified; keys seen: `ScanType`, `FirstMass`, `LastMass`, `MassAnalyzer`, `OrbitrapResolution`, `AGCTarget` |
| `cs.Values["MaxIT"]`, `cs.Values["Polarity"]` | injection time, polarity | **unverified** key names and value encoding; `scans.PossibleParameters` (each with `.Name`, `.Selection`) lists the real ones |
| `cs.Values["MassAnalyzer"] = "OrbitrapMS"` | analyzer | key verified, **value unverified** |
| `cs.RunningNumber`, `cs.SingleProcessingDelay` | request id, delay | verified (ThermoApi.cs) |
| `scans.SetCustomScan(cs)` (returns `bool?`) | place the scan | verified |
| `scans.CancelCustomScan()` | cancel, e-stop | verified |
| `scans.Dispose()` | close | verified |
| `access.GetMsScanContainer(0)` -> `IFusionMsScanContainer` | scan stream | verified |
| `msc.MsScanArrived` event, `MsScanEventArgs.GetScan()` -> `IMsScan` | scan arrival | verified (the brief's `ScansArrived` is not the name used in the examples) |
| `scan.Header["Scan"]`, `["ScanNumber"]`, `["ScanMode"]` | scan number | verified |
| `scan.Header["TIC"]` | `tic` | **unverified** key |
| `scan.Trailer["Access ID"]` | matching a custom scan to its request | seen in AdvancedConsoleApplication; that it equals `RunningNumber` is **unverified** |
| `scan.Centroids` with `.Mz`, `.Intensity` | peaks | verified |
| `access.InstrumentName`, `access.Connected` | identity, `connected` | **unverified** |

Not used: acquisitions (`CreateAcquisitionLimitedByDuration`, `StartAcquisition`, `CancelAcquisition`),
modes (`CreateOnMode`, `SetMode`), repetition scans, inclusion lists.
