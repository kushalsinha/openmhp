# python-seabreeze calls used by this package

Source: python-seabreeze (github.com/ap--/python-seabreeze, MIT), `src/seabreeze/spectrometers.py` and
`src/seabreeze/cseabreeze/c_seabreeze_wrapper.pyx` as of the master branch read in November 2026, plus the
API reference at python-seabreeze.readthedocs.io.

| Call | Used for | Notes |
|---|---|---|
| `seabreeze.spectrometers.list_devices()` | `discover("spectrometers")`, `probe` | returns `SeaBreezeDevice` objects with `.serial_number` and `.model` |
| `Spectrometer.from_first_available()` | open when `serial_number` is null | |
| `Spectrometer.from_serial_number(serial)` | open a specific unit | |
| `spec.integration_time_micros(us)` | setting `integration_time_us` | an `int` in microseconds |
| `spec.integration_time_micros_limits` | the driver's second check on `integration_time_us` | property, `(min, max)` tuple |
| `spec.wavelengths()` | `wavelength_nm` in results | numpy array, one value per pixel |
| `spec.intensities(correct_dark_counts=, correct_nonlinearity=)` | one scan | numpy array; averaging over `scans_to_average` is done by the driver |
| `spec.serial_number`, `spec.model`, `spec.pixels`, `spec.max_intensity` | identity signals and the `saturated` test | properties |
| `spec.close()` | shutdown | |
| `spec.f.thermo_electric` | TEC on cooled models | feature identifier `thermo_electric`; class `SeaBreezeThermoElectricFeature` |
| `thermo_electric.enable_tec(bool)` | `tec_setpoint_c` null -> off | verified in the wrapper source |
| `thermo_electric.set_temperature_setpoint_degrees_celsius(t)` | `tec_setpoint_c` | verified in the wrapper source |
| `thermo_electric.read_temperature_degrees_celsius()` | `detector_temperature` | verified in the wrapper source |

Unverified:

- Whether `spec.f.thermo_electric` is `None` (as the driver assumes via `getattr(..., None)`) or raises on a
  model without a cooler. The driver treats both as "no TEC".
- The per-model integration-time ranges quoted in `descriptor.yaml` notes (USB2000+ 1 ms-65 s, USB4000 10 us-65 s,
  QE Pro 8 ms-1600 s) are from the vendor data sheets as remembered, not re-read; the driver trusts
  `integration_time_micros_limits` from the instrument instead.

Not used: `spec.spectrum()` (returns wavelengths and intensities together), the `eeprom`, `nonlinearity_coefficients`
and `shutter` features. A lamp or shutter feature, if the lab's model has one, would be the honest way to take a
dark without a person; it is not wired here.
