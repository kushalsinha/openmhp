# Setting up on the bench PC (Windows)

1. Install Wasatch's USB driver (it comes with ENLIGHTEN), then in the Python environment that
   runs `mhp`: `pip install wasatch`.
2. Close ENLIGHTEN; only one program can hold the spectrometer.
3. Copy `config.example.json` to `config.json`. `serial_number` null takes the first spectrometer
   found. `bands_cm1` are the Raman shifts whose intensity is reported (Cu2O bands by default).
4. `mhp serve pkg:<this folder> --http <port>`, read `connected`, then `acquire` with the laser off
   (a dark spectrum) as the first hardware test.

Written against Wasatch.PY (WasatchBus, WasatchDevice, change_setting, acquire_data). Not yet run
against the hardware. Band intensity is the highest count within the half-width of the band
centre minus the median of the two flanking windows.
