# Chromeleon SDK members used

Thermo's API reference ships only with the SDK development licence. The names below were read from:

- IFPEN `PocSdkChromeleon` (github.com/ifpen/PocSdkChromeleon, C#: creates a sequence, runs it, exports
  results; references `Thermo.Chromeleon.Sdk` 7.2.9).
- IFPEN `AllotropeConverters` (github.com/ifpen/AllotropeConverters, `CHROMELEON-SDK.md` and the
  Chromeleon converter: reads injections, signals and peaks by formula evaluation).
- Thermo Fisher "Chromeleon SDK specifications" PS74111 (2023): capabilities, licensing, 32-bit.

## Confirmed in that code

| Step | Member |
|---|---|
| Scope | `using (new CmSdkScope())` in `Thermo.Chromeleon.Sdk.Common`; dispose logs off |
| Logon | `CmSdk.Logon.DoLogon()` |
| Factories | `CmSdk.GetItemFactory()` -> `IItemFactory`; `CmSdk.GetInstrumentAccess()` -> `IInstrumentAccess` |
| Items by URL | `IItemFactory.TryGetItem<T>(Uri, out T)` for `IFolder`, `ISequence`, `IInjection`, `IInstrumentMethod`, `IProcessingMethod`; URLs `chrom://host/DataVault/Folder/seq.seq/N.smp` |
| Create | `IItemFactory.CreateSequence(name, IFolder)`, `CreateInjection(name, ISequence)`, inside `System.Transactions.TransactionScope` + `Complete()` |
| Injection fields | `IInjection.Name`, `.InjectionVolume.Value`, `.InstrumentMethodName.Value`, `.ProcessingMethodName.Value`, `.Comment.Value`, `.InjectTime`, `.Signals`, `.Evaluate(formula, IEvaluationContext)` |
| Methods | `IInstrumentMethod` / `IProcessingMethod` `.Name`, `.CopyTo(ISequence, CopyOptions.CurrentVersion)` |
| Instrument | `IInstrumentAccess.TryFindInstrument(Uri, out IInstrument)`, `IInstrument.TakeControl()`, `.QueueControl` |
| Queue | `QueueControl.AddItem(sequence.Url)`, `.ForceQueueStart()`, event `InjectionRunEnded` (`InjectionChangedEventArgs.InjectionUri`) |
| Results | `ISequence.Reload()`, `.Injections`; `IItemFactory.CreateEvaluationContext(signalName, peakIndex)`; formulas `peak.name`, `peak.retention_time`, `peak.area`, `peak.height` (also `peak.width`, `peak.asymmetry`, `peak.resolution("ep/usp")`, ...); result has `.IsError`, `.IsNumeric`, `.NumericValue`, `.StringValue` |
| Architecture | 32-bit only (`SdkException` WrongArchitecture otherwise); DLL in `C:\Program Files (x86)\Thermo\Chromeleon\bin` |

## Unverified (marked `# unverified` in driver.py)

- `CmSdk.Logon.DoLogon(user, password)`: only the parameterless form was seen.
- `IFolder.Items` as the child collection, and telling instrument from processing methods by type name.
- `IInjection.Position` as the vial/position property.
- `IInstrument.State` and `IInstrument.Name`.
- `CopyTo(seq, 0)`: `CopyOptions.CurrentVersion` passed as its integer value.
- pythonnet's handling of `TryGetItem<T>(Uri, out T)` and `TryFindInstrument(Uri, out IInstrument)`:
  written as returning `(ok, item)` with a `None` placeholder, which is pythonnet's convention for `out`
  parameters.
- Any abort or stop on the queue: none appears in public code, so `safety.estop` is false.
- `ISequence.Status`, `IInjection.Status`, `IDataVault`, `IInstrumentController`, `IInstrumentQueue`,
  `ISequenceQueue` (names from the task brief) were not found anywhere public and are not used.
