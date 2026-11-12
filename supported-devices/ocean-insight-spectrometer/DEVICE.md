---
mhp: "2026-09-12"
id: ocean-insight-spectrometer-01
class: spectrometer
make: Ocean Insight (Ocean Optics)
model: USB2000+, USB4000, Flame, QE Pro, HR series (python-seabreeze)
location: ""
tags: [spectrometer, uv-vis, absorbance, fluorescence, seabreeze, usb]
description: A fibre-coupled Ocean Insight / Ocean Optics USB spectrometer (USB2000+, USB4000, Flame, QE Pro, HR2000+/HR4000) read through python-seabreeze. Pick it to take a UV-Vis, absorbance or fluorescence spectrum with a chosen integration time and averaging, to store a dark spectrum for subtraction, and to get back the wavelength and intensity arrays plus a CSV on disk. It does not control the lamp, shutter or sample holder, and it computes no absorbance; the caller does that from a reference and a sample spectrum.
driver: driver.py:OceanSpectrometer
sim: sim.py:SimOceanSpectrometer
---

# Ocean Insight spectrometer (python-seabreeze)

The spectrometer connects to the host by USB; seabreeze's own USB backend (cseabreeze or pyseabreeze) talks
to it, so OceanView must be closed. The package reads the detector, sets the integration time and, on cooled
models such as the QE Pro, the thermo-electric cooler. The light source, fibres and sample holder are the
lab's and are not seen here.

## Operating procedure

1. Read `connected`, `model` and `serial_number`; on a cooled model read `detector_temperature` and wait for
   it to settle near `tec_setpoint_c` before quantitative work.
2. Write `integration_time_us` so a bright reference spectrum sits well below saturation (read `saturated`
   after a test `acquire`; halve the exposure if it is true). Write `scans_to_average` for the noise you need.
3. Block the light (a person, or the lamp's own shutter) and invoke `acquire_dark`. `dark_stored` turns true.
   Repeat after every change of `integration_time_us`.
4. Invoke `acquire` for each reference and sample; the result carries `wavelength_nm` and `intensity`
   arrays and the CSV path. Absorbance is -log10((sample - dark) / (reference - dark)), computed by the caller.
5. At the end of a session write `tec_setpoint_c` null on a cooled model if the lab's practice is to let the
   detector warm up; otherwise leave it on.

## What to watch

- `saturated: true` in a result means the spectrum is clipped and the intensities are not usable.
- A dark taken at one integration time is wrong for another; the package discards it on a change, so
  `dark_stored` false after a change is expected, not a fault.
- On cooled models the dark counts drift until `detector_temperature` has settled; the twin models that.
- Models without a TEC answer `detector_temperature` null and refuse a non-null `tec_setpoint_c`.
- Emergency stop turns the TEC off and cancels the acquisition; nothing else here carries energy.

## Resources

- `references/setup.md`: installing python-seabreeze and its USB driver, config.json, the first hardware test.
- `references/seabreeze_api.md`: the seabreeze calls this package makes and which are unverified.
- `config.example.json`: the spectrometer serial (or null for the first one found) and the data folder.
