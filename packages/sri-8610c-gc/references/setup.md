# Setting up on the bench PC (Windows)

1. PeakSimple must be running and connected to the GC whenever this device is used.
2. In the Python environment that runs `mhp`: `pip install pythonnet`.
3. Copy `config.example.json` to `config.json`:
   - `connector_dll`: PeaksimpleConnector.dll from the PeakSimple install folder.
   - `control_dir`: folder holding the control files (.con) agents may run. Nothing outside it can be loaded.
   - `results_dir`: the folder the control file saves into (its `<DATA FILE PATH>`).
   - `channel`: PeakSimple channel that starts the run (1).
4. In the control file's post-run actions, tick "save results" so every run writes a result file
   into `results_dir`; add calibration if concentrations are wanted.
5. `mhp serve pkg:<this folder> --http <port>` and read `connected`.

The connector calls (`Connect`, `LoadControlFile`, `SetRunning(channel, True)`, `IsRunning(channel)`)
are the ones the open-source catalight package uses for an SRI GC (catalight.readthedocs.io,
equipment guide "SRI Gas Chromatograph"); catalight also documents where to get
PeaksimpleConnector.dll from SRI. Things learned from it:

- PeakSimple must already be running. If either PeakSimple or the device server stops, restart
  BOTH before reconnecting; the connector cannot re-attach.
- A control file (.CON) is plain text. The lines that matter here:
  `<DATA FILE PATH>=` (set it to `results_dir`), `<CHANNEL n POSTRUN SAVE DATA>=1` (writes an
  .ASC chromatogram per channel), `<CHANNEL n POSTRUN SAVE RESULTS>=1`, `<CHANNEL n POSTRUN AUTOINCREMENT>=1`,
  and `<CHANNEL 1 TIME>=` (run length in ms, which the driver reads when run_time_s is not given).
- This driver never rewrites the control file; set those lines once in PeakSimple and save.

Not yet run against the hardware. The .ASC reader does a simple threshold integration (retention,
height, area); calibrated concentrations come from PeakSimple's result file or the agent's own
calibration table.
