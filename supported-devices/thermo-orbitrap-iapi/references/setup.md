# Setting up on the instrument PC (Windows-only)

The IAPI is a .NET Framework interface served by Tune on the instrument PC; this route is Windows-only.
The twin runs anywhere.

1. Obtain the IAPI licence from Thermo Fisher (per instrument; see `docs/Orbitrap_IAPI_Online_licensing_guidance_material.pdf`
   in github.com/thermofisherlsms/iapi) and the assemblies `Thermo.TNG.Factory.dll`, `API-2.0.dll`,
   `Fusion.API-1.0.dll` (Tune 4.2 and earlier) or `Fusion.API-2.0.dll` (Tune 4.3). Put them in one folder.
2. In the Python environment that runs `mhp` (64-bit Python on the instrument PC): `pip install pythonnet`.
3. Tune must be running and the instrument On. The IAPI service answers only while Tune is up.
4. Copy `config.example.json` to `config.json`: `assembly_dir` (the folder from step 1), `data_dir` for the
   CSV centroid lists; `instrument_index` stays 1.
5. The m/z, resolution and AGC bounds in `descriptor.yaml` are placeholders from the Tribrid data sheets;
   narrow them to the lab's methods.

## First hardware test

1. `mhp node setup` on this package: its probe loads the assemblies, connects, and prints the instrument
   name and state.
2. Read `connected`, `instrument_state`, `last_scan_number`; with Tune acquiring, `last_scan_number` rises.
3. Invoke `request_custom_scan` with the example parameters on the calibration mix; the job should finish in
   a few seconds with `points` in the hundreds and `base_peak_mz` on a calmix ion.
4. Open `peaks_csv` and compare with the same scan in Tune. Check the scan header printed by the result's
   polarity and injection time against what was asked; if they differ, the `MaxIT` and `Polarity` keys
   (unverified) need the names Tune's `PossibleParameters` lists (see `iapi.md`).
5. Invoke `request_custom_scan` and cancel the job at once; the instrument's queue should show no pending scan.

## Status

Twin tested. Written from Thermo's public iapi repository (GettingStarted.md, tribrid examples) and not yet
run against an instrument. The custom scan keys `MaxIT`, `Polarity`, `MassAnalyzer`'s value, the header key
`TIC`, `IAcquisition.State.SystemMode`, `InstrumentName` and `Connected` are unverified; see `iapi.md`.
