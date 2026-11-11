# Setting up an SRS RGA100/200/300

## What this package does and does not do

It configures and protects the head: filament emission on/off, electron and ion energy, focus and
multiplier voltages, the status and error registers, and the `CA` calibration. It does **not**
acquire spectra, single-mass readings (`MR`) or total pressure (`TP?`): the ECU returns those as
4-byte little-endian binary currents in units of 1e-16 A, and the generic text driver reads lines.
For measurements use RGA Windows, the SRS `srsinst.rga` Python package (MIT), or write a code driver
that subclasses `openmhp.drivers.serial_ascii.SerialAsciiDriver` and reads the four bytes in `on_read`.
The noise-floor setting (`NF<n>`), the mass range (`MI`/`MF`/`SA`) and degas (`DG`) are left out as
well: `NF`/`MI`/`MF`/`SA` send no reply and would stall the serial timeout; `DG` replies only when
the degas ends, minutes later, and the stray STATUS byte would corrupt the next reply.

## What to install

- `pip install openmhp pyserial` on the computer cabled to the ECU (Linux, macOS or Windows).
- A straight-through DB-9 cable: the ECU's RS-232 connector is wired as DCE (it transmits on pin 3, receives on pin 2), so a PC port or a USB-to-RS-232 adapter connects without a null modem.
- Do not share the port with RGA Windows; any command sent during one of its scans aborts the scan.

## Serial settings

Fixed at 28800 baud, 8 data bits, no parity, 1 stop bit (the SRS manual; an older note of 2 stop bits is wrong). The ECU uses RTS/CTS hardware handshake: it asserts CTS when ready and reads RTS to throttle its own transmission. pyserial asserts RTS on open, which is enough for the short replies this package reads; `rtscts` is not enabled by the generic driver (unverified on hardware, see protocol.md). Commands end in CR; replies end in LF CR, which the driver strips.

The `timeout` in descriptor.yaml is 125 s because `CA` answers only when the calibration is finished, up to two minutes later; every other declared command answers within seconds. A bad command gets no reply and will stall a read for that long, then raise.

## Instrument settings

- Chamber below 1e-4 Torr before any filament switch-on, below about 5e-6 Torr before the electron multiplier is biased. The package cannot read pressure: the person who confirms `emission_setpoint` or `cdem_setpoint` reads the chamber gauge first (pair it with a `pfeiffer-tpg-gauge` or similar package in the same lab so an orchestrator can read it).
- `emission_setpoint` is capped at 2.0 mA and `cdem_setpoint` at 2000 V in descriptor.yaml; set them to what your head and CDEM calibration allow.
- The ECU's jumper JP100 protects the tuning parameters; nothing here touches them.

## First hardware test

1. Copy `config.example.json` to `config.json` and set `port`.
2. `mhp serve pkg:<this folder>`; read `connected`, then `identity` (expect `SRSRGA...VER...SN...`). If it times out, check the cable (straight, not null-modem) and that RGA Windows is closed.
3. Read `status_byte`, `filament_error`, `comm_error`, `cdem_installed`; all errors should be 0. Invoke `initialize` and read them again.
4. With the chamber below 1e-4 Torr, write `emission_setpoint` 1.0 (confirm). Watch the Filament LED, read `emission_current` (about 1.00) and `filament_ok` (true). Write `electron_energy_setpoint` 70 and read `electron_energy`.
5. Invoke `filament_off`, then the e-stop, and confirm the Filament and HV LEDs are off and `state` reads `estop`; reset.

## Status

Twin tested. Written from the SRS "Operating Manual and Programming Reference, RGA100/200/300" chapter 6 and cross-checked with `srsinst.rga` and `pyrga`; not yet run on hardware. The RTS/CTS behaviour without `rtscts` and the exact digit format of `FL?`/`EE?` replies are unverified.
