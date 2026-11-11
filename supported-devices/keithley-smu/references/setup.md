# Setting up a Keithley 2400-series SourceMeter

## What to install

- `pip install pyvisa pyvisa-py` on the PC that will serve the device (Linux, macOS or Windows).
  For GPIB you also need a GPIB adapter and its backend: NI-VISA with an NI GPIB-USB-HS, or
  `pip install gpib-ctypes` with linux-gpib. For RS-232 only, `pip install pyserial` is enough.
- The 2400, 2401, 2410 and 2420 have GPIB and RS-232 only; there is no USB or LAN port on them
  (those are on the 2450 and later, whose command set differs: see `scpi.md`).

## Cable and port

- GPIB: factory address 24. The resource is `GPIB0::24::INSTR` (NI-VISA) or the same string
  through pyvisa-py with linux-gpib.
- RS-232: a straight-through 9-pin cable to the rear port. In the front-panel MENU >
  COMMUNICATION select RS-232 (GPIB and RS-232 are exclusive), 9600 baud, 8 bits, no parity,
  1 stop bit, flow control NONE, terminator LF. The generic route opens the port at 9600 8N1;
  the resource is the device path, `/dev/ttyUSB0`, `/dev/tty.usbserial-XXXX` or `COM4`.
- A LAN-to-GPIB gateway (Prologix, NI GPIB-ENET) can front the 2400 on `tcp://host:port` or a
  `TCPIP0::...::INSTR` resource; the gateway's own documentation says which.

## Settings on the instrument

- Communication interface and address as above. Nothing else needs enabling: SCPI is the
  default language (the DDC compatibility language must be off).
- Compliance is a per-session value and resets to 105 uA / 21 V on `*RST`: the package sets it
  in `source_voltage` / `source_current`.

## Write the config

Copy `config.example.json` to `config.json` beside the package and set `resource`, or let
`mhp node setup` ask for it: it lists what pyvisa sees and accepts a typed string.

## Known costs of the declarative route

Every SCPI write waits the `timeout` (2 s in descriptor.yaml) for a reply that never comes;
queries answer immediately. A sweep of fifty setpoints therefore takes about two minutes of
dead time. Lower `scpi.timeout` to 0.5 if the link is reliable.

## First hardware test

1. With nothing wired to the terminals, `mhp serve pkg:<this folder>` and read `connected`
   (true) and `last_error` (expect `0,"No error"`). `*IDN?` must contain KEITHLEY, or the probe
   refuses the resource.
2. Invoke `reset`, then read `output_on` (false) and `source_function_actual` (VOLT).
3. Invoke `source_voltage` with `voltage: 1.0, compliance_current: 0.001`; read
   `voltage_setpoint_actual` (1.0) and `compliance_current_actual` (0.001).
4. Write `output_on` true, read `voltage` (about 1.0) and `current` (about 0 with open
   terminals), invoke `measure` and look at the five-field reply. Write `output_on` false.
5. Call `safety/estop` once while the output is on and confirm the front-panel OUTPUT light goes
   off; then `safety/reset`.

Then wire the DUT, lower every limit in `descriptor.yaml` (`voltage_setpoint`,
`current_setpoint`, both compliances and the matching action parameters) to what it survives,
and `mhp_lab op='reload'` so the lab accepts the edited package.

## Status

twin tested. Written from the Keithley 2400 Series SourceMeter User's Manual (2400S-900-01) and
the command summaries of open-source drivers (pymeasure `Keithley2400`); not yet run on hardware.
Items marked unverified in `scpi.md` were not checked against an instrument.
