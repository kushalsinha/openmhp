# Zetasizer SDKs: what was found, and what this package assumes

Searched 2026-11-11: Malvern Panalytical's GitHub organisation (no public repositories), GitHub code
search for "Zetasizer" (data-file parsers only, no instrument control), the ZS Xplorer Software
Update Notifications v3.0, v4.0 and v4.2 (PSS0048 series; no mention of an SDK or API beyond the
.NET runtime prerequisites), the Zetasizer family software v8.02 notice (no SDK; warns that
third-party interfaces may break), and the Zetasizer Core page (a "robotic handling API" announced
for the newer ZS Discover software, not ZS Xplorer). Integrations seen in the wild (e.g. seal.run)
work from exported files.

Conclusion: a "ZS Xplorer SDK" (.NET) and a "Zetasizer Nano SDK" (COM) are referred to by users but
have no public reference. Every member below is therefore an assumption, configurable in
config.json `sdk`, and must be corrected from the vendor's SDK document before the first hardware test.

| config key | placeholder | role | verified |
|---|---|---|---|
| assembly | Malvern.ZsXplorer.Sdk | the .NET assembly loaded with pythonnet | no |
| app | Malvern.ZsXplorer.Sdk.ZsXplorerApplication | application / instrument object | no |
| connect | Connect() | open the instrument connection | no |
| status | InstrumentStatus (property) | status signal | no |
| cell_temperature | CellTemperature (property, Cel) | cell_temperature signal | no |
| set_temperature | SetTemperature(double) | temperature_setpoint | no |
| set_equilibration | SetEquilibrationTime(double s) | equilibration_s | no |
| load_sop | LoadSop(path) | load a .zsop | no |
| start | StartMeasurement(sampleName) | start size or zeta measurement per the loaded SOP | no |
| is_running | IsRunning (property) | polling | no |
| abort | AbortMeasurement() | cancel, e-stop | no |
| result | LastResult (record with ZAverage, PolydispersityIndex, IntensityPeaks[Mean, Area, Width], Temperature, Attenuator, ZetaPotential, Conductivity, Mobility, QualityReport) | the returns | no (the result parameter names are ZS Xplorer's display names) |
| export | ExportResult(path) | the record file | no |

Instrument facts used (verified): Zetasizer Ultra temperature control 0-120 Cel (dry purge below the
dew point; water-based samples to 100), from the Malvern Panalytical Ultra product page; ZS Xplorer is
Windows 10/11 with .NET Framework 4.8 and .NET 5 prerequisites (software update notifications);
result parameters Z-average, PDI, intensity peaks, attenuator, zeta potential, conductivity,
mobility and quality report are ZS Xplorer's standard result fields.
