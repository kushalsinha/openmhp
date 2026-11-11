# Setting up on the host PC (Windows or Linux)

The NI-DAQmx runtime is published for Windows and for a few Linux distributions (RHEL, Ubuntu LTS, SUSE);
there is no macOS runtime, so this package reaches hardware only from Windows or Linux. The twin runs anywhere.

1. Install the NI-DAQmx runtime from ni.com (on Linux, NI's repository and the `ni-daqmx` package; a reboot
   or `dkms` build may be needed). Open NI MAX (Windows) or `nilsdev` (Linux) and note the device name (`Dev1`).
2. In the Python environment that runs `mhp`: `pip install nidaqmx` (NI's MIT-licensed Python package).
3. Close NI MAX test panels and any LabVIEW VI holding the device.
4. Copy `config.example.json` to `config.json`: `device` (`mhp node setup` lists the devices NI-DAQmx knows)
   and `data_dir` for the CSV records.
5. Set the AO limits in `descriptor.yaml` to the device (0-5 V on a USB-6008/6009) and to what the circuit
   may receive; set `approval: confirm` on an output that switches something that matters.

## First hardware test

1. `mhp node setup` on this package; its probe lists the device, its product type, and reads ai0 once.
2. Read `connected`, `device`, `product_type`, then `ai0`..`ai3` with nothing wired (near 0 V or floating).
3. Jumper ao0 to ai1; write `ao0` 2.5 and read `ai1` (about 2.5 V).
4. Invoke `sample` with channels [ai1], 100 Hz, 2 s: 200 rows in the CSV at 2.5 V, `rate_hz` 100.
5. Write `port0_line0` true (measure 5 V on the terminal, with the pull-up a 6008/6009 needs); e-stop; read
   `ai1` (0 V) and `port0_state` (0).

## Status

Twin tested. Written from NI's open nidaqmx-python examples and API documentation, not yet run on a device.
`task.timing.samp_clk_rate` as the read-back of the actual rate, the multi-channel `read` shape, and the
DaqError code for an out-of-range AO are unverified; see `nidaqmx.md`.
