# nidaqmx calls used by this package

Sources read (November 2026): github.com/ni/nidaqmx-python (MIT) examples `examples/analog_in/voltage_acq_int_clk.py`,
`examples/analog_out/voltage_update.py`, `examples/digital_out/write_dig_lines.py`, `examples/system_properties.py`;
the nidaqmx API documentation (nidaqmx-python.readthedocs.io) for the method signatures, from memory where noted.

| Call | Used for | Status |
|---|---|---|
| `nidaqmx.system.System.local().devices`, each with `.name`, `.product_type` | `discover("devices")`, open | verified |
| `with nidaqmx.Task() as task:` | one task per operation | verified |
| `task.ai_channels.add_ai_voltage_chan("Dev1/ai0")` | AI | verified (default terminal configuration and +/-10 V range) |
| `task.read()` -> float for one channel, list of floats for several | spot reads | verified for one channel; the several-channel shape is **unverified** (the driver accepts both a scalar and a list) |
| `task.ao_channels.add_ao_voltage_chan("Dev1/ao0")`, `task.write(volts, auto_start=True)` | AO | verified (`task.write(1.1)` in the example; `auto_start` from the API docs as remembered) |
| `task.do_channels.add_do_chan("Dev1/port0/line0", line_grouping=LineGrouping.CHAN_PER_LINE)`, `task.write(bool)` | DO | verified (the example writes a list of booleans to `line0:3`; one line, one boolean here) |
| `task.timing.cfg_samp_clk_timing(rate, sample_mode=AcquisitionType.CONTINUOUS, samps_per_chan=n)` | hardware-timed sampling | verified (the example uses `AcquisitionType.FINITE`; CONTINUOUS with block reads is used here so a record can be cancelled) |
| `task.start()`, `task.read(number_of_samples_per_channel=n, timeout=s)`, `task.stop()`, `task.close()` | the record | `read` with `number_of_samples_per_channel` from the API docs; the return shape for several channels (list per channel) is **unverified** |
| `task.timing.samp_clk_rate` | the rate the device actually set | **unverified** attribute name |
| `nidaqmx.errors.DaqError` | every failure | caught as a generic exception at the backend boundary |

Device facts used in notes (NI data sheets, from memory): USB-6008/6009 AI +/-10 V single-ended, 10 kS/s
aggregate, AO 0-5 V software-timed, DO open-collector by default; USB-6001 AO +/-10 V; USB-621x and 63xx AO
+/-10 V. The runtime is Windows and Linux only.

Unverified:

- The DaqError code the twin quotes for an AO outside 0-5 V (`-200561`).
- Whether a USB-6008/6009 accepts `AcquisitionType.CONTINUOUS` with `samps_per_chan` as the buffer size for
  every rate in 1-1000 Hz (it should; the device is specified to 10 kS/s).
