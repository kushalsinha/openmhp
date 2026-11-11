# Setting up a Rigol DS1000Z-family oscilloscope

## What to install

- LAN: nothing beyond `pip install openmhp`; `tcp://<ip>:5555` is opened as a plain socket.
- USB: `pip install pyvisa pyvisa-py pyusb` (USBTMC; on Linux a udev rule for vendor 0x1AB1,
  on Windows NI-VISA or a libusb driver via Zadig). The resource is what pyvisa lists,
  `USB0::0x1AB1::0x04CE::DS1ZA...::INSTR`.
- Runs from Linux, macOS or Windows.

## Cable and port

- LAN: Utility > IO Setting > LAN Conf shows the IP (DHCP by default; reserve it). Rigol's raw
  SCPI socket is port 5555; VISA `TCPIP0::<ip>::inst0::INSTR` also works through pyvisa.
- USB-B on the rear (USB Device). The front USB-A is for memory sticks, not control.

## Settings on the instrument

- Nothing to enable. The front panel stays live; a person turning a knob changes what the
  `_actual` signals read, which is the intended way to work alongside this package.
- Probe ratio (1X/10X) is set per channel on the scope and scales `ch1_scale_v` and the
  measurements; this package does not read it.

## Model differences (notes only; the descriptor is the DS1000Z's)

- MSO1000Z: same commands plus digital channels D0..D15 as trigger sources.
- MSO5000, DHO800/DHO900: `:MEAS:ITEM?`, `:TIM:SCAL`, `:CHAN<n>:SCAL/OFFS/DISP`,
  `:TRIG:EDG:SOUR/LEV`, `:RUN/:STOP/:SING/:AUT` and `:TRIG:STAT?` are the same; the USB
  product id differs and the DHO answers `:ACQ:SRAT?` in the same units. Check `*IDN?` and the
  programming guide for the model before trusting the enum of `measure`'s items.

## Not provided: waveform download

`:WAV:DATA?` returns an IEEE 488.2 binary block (`#9000001200...` followed by raw bytes). The
declarative SCPI driver reads text lines and cannot carry it; a package that needs the trace
subclasses `ScpiVisaDriver` in its driver.py with an `on_invoke` that reads the block, and
declares `returns` naming the file it wrote. This package reads measurements only.

## First hardware test

1. Connect the probe-compensation output (about 1 kHz, 3 Vpp square) to CH1 with a 10X probe.
   `mhp serve pkg:<this folder>`; read `connected`, `trigger_status` and `last_error`.
   `*IDN?` must contain RIGOL, or the probe refuses the resource.
2. Invoke `autoset` (confirm it); read `timebase_actual`, `ch1_scale_actual`.
3. Read `vpp_ch1` (about 3), `freq_ch1` (about 1000) and `sample_rate`.
4. Write `ch1_scale_v` 0.2 and read `vmax_ch1`: it sits at the screen edge, which is what
   clipping looks like; write `ch1_scale_v` 1 again.
5. Invoke `single`, then `measure` with `item: VRMS, channel: CHAN1` and check the job's reply;
   invoke `run`. Read `vpp_ch1` with the probe disconnected and see 9.9E37 or a noise value.

## Status

twin tested. Written from the Rigol DS1000Z Series Digital Oscilloscope Programming Guide
(PGA18, Rigol Technologies) and the DS1000Z user guide; not yet run on hardware. Items marked
unverified in `scpi.md` were not checked against an instrument.
