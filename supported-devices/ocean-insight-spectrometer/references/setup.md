# Setting up on the host PC (Windows, Linux or macOS)

1. In the Python environment that runs `mhp`: `pip install seabreeze` (python-seabreeze, MIT, by
   Andreas Poehlmann; it bundles the cseabreeze C backend; `pip install seabreeze[pyseabreeze]` adds the
   pure-Python USB backend). python-seabreeze needs numpy.
2. Run `seabreeze_os_setup` once (installs the udev rules on Linux and the libusb driver on Windows).
   On Windows the OceanView/OmniDriver driver and the libusb driver compete for the device: the vendor
   driver must be replaced by the libusb one for seabreeze (the `seabreeze_os_setup` output says how).
3. Close OceanView; only one program can hold the spectrometer.
4. Plug the spectrometer in by USB. Copy `config.example.json` to `config.json`: `serial_number` null takes
   the first spectrometer found; `data_dir` is where the CSV spectra go.
5. The integration-time limits in `descriptor.yaml` (1 ms to 10 s) are a placeholder; the driver also refuses
   anything outside the range the instrument itself reports. Narrow them to what your measurement needs.

## First hardware test

1. `mhp node setup` on this package (it lists the spectrometers seabreeze sees) or
   `mhp serve pkg:<this folder> --http <port>`.
2. Read `connected`, `model`, `serial_number` and `integration_time`.
3. With the lamp off or the fibre capped, invoke `acquire_dark`; the result's `intensity` should be a flat
   few hundred to few thousand counts and `saturated` false.
4. With the lamp on and a reference in the beam, write `integration_time_us` and invoke `acquire` until
   `saturated` is false and the peak is at roughly half of the detector's range.
5. On a QE Pro write `tec_setpoint_c` -10 and watch `detector_temperature` fall over a minute or two.

## Status

Twin tested. The driver is written from the python-seabreeze API reference and source, not yet run on a
spectrometer. The TEC feature access (`spec.f.thermo_electric` returning None on models without a cooler)
is unverified; see `seabreeze_api.md`.
