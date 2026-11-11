# Setting up on the host PC (Windows, Linux or macOS)

1. In the Python environment that runs `mhp`: `pip install pyserial`. No PalmSens SDK is needed; the
   instrument speaks MethodSCRIPT over its USB virtual COM port.
2. On Windows the EmStat4 driver is installed with PSTrace; the EmStat Pico development board shows up
   as a USB serial port. On Linux the device is `/dev/ttyACM*` and the user needs the `dialout` group.
3. Close PSTrace (and any MethodSCRIPT editor): only one program may hold the port.
4. Copy `config.example.json` to `config.json`: `port` (`mhp node setup` lists the serial ports), `baud`
   (230400 for an EmStat Pico or Sensit, 921600 for an EmStat4 or Nexus), `data_dir` for the CSV traces,
   `max_run_s` as the longest technique an agent may start.
5. The potential bounds in `descriptor.yaml` (+/-1.2 V) and `current_range_max_A` limits are placeholders;
   set them to what the lab's cell may take. Remember that the instrument's own limits are wider.

## First hardware test

1. `mhp node setup` on this package; its probe sends `t` and should print the firmware string
   (`espico...` or `es4_lr...`).
2. Connect a dummy cell (a 10 kohm resistor WE-RE/CE is enough) and read `connected`, `device_type`.
3. Invoke `ocp` for 5 s: `e_final_V` should be near 0 V on a resistor.
4. Invoke `ca` at 0.1 V for 5 s: `i_final_A` should be about 10 uA on 10 kohm. Open the CSV and check the
   time column counts in `interval_s` steps.
5. Invoke `cv` 0 -> 0.5 -> -0.5 -> 0 V at 100 mV/s and cancel it after a second: the job ends `cancelled`,
   the log shows `Z`, and the cell LED (where the instrument has one) goes off.

## Status

Twin tested. The driver is written from PalmSens' open MethodSCRIPT examples and the MethodSCRIPT manual,
not yet run on an instrument. The OCP range lines, the pgstat modes per technique and the unknown-command
error code are copied from the examples or marked unverified in `methodscript.md`.
