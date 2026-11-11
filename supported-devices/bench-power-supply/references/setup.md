# Setting up a Rigol DP800-series bench power supply

## What to install

- LAN: nothing beyond `pip install openmhp`; `tcp://<ip>:5555` is opened as a plain socket.
- USB: `pip install pyvisa pyvisa-py pyusb` (USBTMC; on Linux a udev rule for vendor 0x1AB1,
  on Windows NI-VISA or a libusb driver via Zadig). The resource is what pyvisa lists,
  `USB0::0x1AB1::0x0E11::DP8C...::INSTR`.
- Runs from Linux, macOS or Windows.

## Cable and port

- LAN (DP832/DP831/DP821/DP811 with the LAN option, standard on most): Utility > I/O > LAN
  shows the IP; Rigol's raw SCPI socket is port 5555 (not 5025). VISA `TCPIP0::<ip>::inst0::INSTR`
  also works through pyvisa.
- USB-B on the rear.
- RS-232 (option): 9600 8N1 by default; the generic route opens the port at 9600 8N1, resource
  `/dev/ttyUSB0` or `COM5`.

## Settings on the instrument

- Nothing to enable for LAN or USB. The front panel stays live; a person pressing a channel's
  On/Off key changes what `output_chN` reads.
- The package turns OVP and OCP on for a channel when it enables that channel; the trip values
  are the `ovp_chN` / `ocp_chN` settings.

## Other vendors (notes only; the descriptor is the DP800's)

- Siglent SPD3303X/X-E: port 5025, commands `CH1:VOLT 5`, `CH1:CURR 1`, `MEAS:VOLT? CH1`,
  `MEAS:CURR? CH1`, `MEAS:POWE? CH1`, `OUTP CH1,ON`; no `:OUTP? CH1` (state is in
  `SYST:STAT?` bits) and no OVP/OCP values. A copy of this package with those strings in the
  `scpi:` block and the output signals removed would serve one.
- Aim-TTi PL-P / MX series: `V1 5.0`, `I1 1.0`, `V1O?` (answers `5.000V`), `I1O?`, `OP1 1`,
  `OP1?`, `OVP1 6`, `OCP1 1.2`; ports 9221 (LAN) or USB CDC serial. The replies carry units,
  which the number parser handles.

## Known costs of the declarative route

Writes do not answer, so each one waits `scpi.timeout` (1 s). `configure_ch1` therefore takes
about four seconds.

## First hardware test

1. With nothing wired to the terminals, `mhp serve pkg:<this folder>`; read `connected`,
   `output_ch1` (false) and `last_error` (`0,"No error"`). `*IDN?` must contain RIGOL, or the
   probe refuses the resource.
2. Invoke `configure_ch1` with `voltage: 3.3, current_limit: 0.5, ovp: 3.6, ocp: 0.6`.
3. Invoke `enable_ch1` (confirm it), read `voltage_ch1` (3.3) and `current_ch1` (0 with
   open terminals), then `disable_ch1`.
4. Enable CH1 again and call `safety/estop`; `output_ch1` must read false and the front-panel
   CH1 indicator goes off. `safety/reset`.
5. Wire a resistor (for example 10 ohm, 2 W, with the setpoint at 3.3 V) and repeat step 3:
   `current_ch1` reads about 0.33 and `power_ch1` about 1.1.

Then lower the `voltage_setpoint_chN`, `current_limit_chN`, OVP/OCP and `configure_ch1` limits
in `descriptor.yaml` to the DUT, and `mhp_lab op='reload'`.

## Status

twin tested. Written from the Rigol DP800 Series Programming Guide (PG-DP800, 2013/2016) and
the DP800 user guide's specifications; Siglent and Aim-TTi notes from their programming manuals
(SPD3303X Programming Guide; PL-P series instruction manual). Not yet run on hardware. Items
marked unverified in `scpi.md` were not checked against an instrument.
