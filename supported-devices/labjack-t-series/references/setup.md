# Setting up on the host PC (Windows, Linux or macOS)

1. Install the LJM library from labjack.com (the installer for your OS; it also installs Kipling and the
   USB driver). Then in the Python environment that runs `mhp`: `pip install labjack-ljm` (the Python wrapper
   around the installed shared library).
2. Connect the T-series by USB, or by Ethernet with an address reachable from this host (T7-Pro and T8 also
   do WiFi). Close Kipling when using USB.
3. Copy `config.example.json` to `config.json`: `identifier` is `ANY`, a serial number or an IP address
   (`mhp node setup` lists what `listAll` finds); `data_dir` is where the CSV records go.
4. Set the output limits in `descriptor.yaml` to what the wired circuit may receive and, where an output
   switches something that matters, `approval: confirm`.

## First hardware test

1. `mhp node setup` on this package; its probe reads SERIAL_NUMBER and PRODUCT_ID.
2. Read `connected`, `device_type`, `serial_number`, then `ain0`..`ain3` with nothing wired (near 0 V, or
   floating values on a T7).
3. Jumper DAC0 to AIN1; write `dac0` 2.5 and read `ain1` (about 2.5 V).
4. Invoke `sample` with channels [AIN1], 10 Hz, 2 s: 20 rows in the CSV at 2.5 V. Repeat at 500 Hz, 1 s
   (the stream path): about 500 rows, `rate_hz` as the device reports it.
5. Write `fio0` true and read `dio_state` bit 0; e-stop; read `dio_state` again (bit 0 low) and `ain1` (0 V).

## Status

Twin tested. Written from LabJack's open labjack-ljm-python examples (MIT) and the LJM register names, not
yet run on a device. The T8 range table and the exact LJM error code for an unknown register are unverified;
see `ljm.md`.
