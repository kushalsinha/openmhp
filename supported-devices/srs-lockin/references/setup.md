# Setting up an SRS SR830 lock-in amplifier

## What to install

- `pip install pyvisa pyvisa-py` on the serving PC (Linux, macOS or Windows); for GPIB also a
  GPIB adapter and its backend (NI-VISA, or linux-gpib with `gpib-ctypes`). For RS-232 only,
  `pip install pyserial`.

## Cable and port

- GPIB: factory address 8 (SETUP > GPIB on the front panel). Resource `GPIB0::8::INSTR`.
- RS-232: the rear DB-25 port through a null-modem cable and a USB-serial adapter. The front
  panel SETUP menu sets the baud rate (choose 9600) and parity (none). The generic route opens
  the port at 9600 8N1; the resource is `/dev/ttyUSB0`, `/dev/tty.usbserial-XXXX` or `COM3`.
- SR860/SR865A: LAN (VISA `TCPIP0::<ip>::inst0::INSTR` or `tcp://<ip>:5025`), USB or GPIB; the
  command set differs in places, see `srs-commands.md`, and this package's descriptor targets
  the SR830.

## Settings on the instrument

- Interface selected and, on the SR830, the `OUTX` command sent once per session: the package
  exposes it as the `output_interface` setting (0 RS-232, 1 GPIB) and the operating procedure
  writes it first. Until then a query may be answered on the other interface and time out here.
- Nothing else; the SR830 has no remote/local lock that needs enabling.

## Write the config

Copy `config.example.json` to `config.json` beside the package and set `resource`, or let
`mhp node setup` ask for it.

## Known costs of the declarative route

Writes do not answer, so each one waits `scpi.timeout` (1 s). The overload and unlock status
bits (`LIAS?`) are not read by this package; watch `r` against the sensitivity full scale.

## First hardware test

1. `mhp serve pkg:<this folder>`, read `connected`, write `output_interface` (1 for GPIB,
   0 for RS-232), then read `frequency` and `sensitivity_index`. `*IDN?` must contain SR830, or
   the probe refuses the resource.
2. With the sine output looped into input A by a BNC, write `frequency` 1000,
   `sine_amplitude` 0.1, `reference_source` 1, `time_constant_index` 8.
3. Invoke `auto_gain`, then `auto_phase`; read `r` (about 0.1 V) and `theta` (about 0).
4. Invoke `snapshot` and check the four comma-separated numbers agree with `x`, `y`, `r`,
   `theta`.
5. Write `aux_out_1` 1.0, read `aux_out_1_actual`, then call `safety/estop`: `aux_out_1_actual`
   must read 0 and `sine_amplitude` 0.004. Then `safety/reset`.

Then lower `sine_amplitude` max and the aux output limits in `descriptor.yaml` to what the
experiment tolerates, and `mhp_lab op='reload'`.

## Status

twin tested. Written from the SR830 DSP Lock-In Amplifier manual (Stanford Research Systems,
revision 2.5, chapter 5 "Remote programming") and the command names in pymeasure's `SR830`
class; not yet run on hardware. Items marked unverified in `srs-commands.md` were not checked
against an instrument.
