# Setting up an Alicat MC/MCR (or PC/PCD) controller

## What to install

- `pip install openmhp pyserial` on the computer cabled to the device (Linux, macOS or Windows; pure Python).
- Cable: Alicat's USB cable (appears as a virtual COM port), its DB-9 RS-232 cable, or an RS-485 adapter for a multi-drop bus. The 8-pin mini-DIN on the device carries power and serial; use Alicat's cables rather than a home-made one.

## Device settings (on the display, Setup > Comm, or through Alicat's FlowVision software)

- Unit ID: one letter, factory `A`. Put it in `config.json` `unit_id`. On a bus each device must have its own letter; this package serves one device per `config.json`, so copy the package folder per unit.
- Baud: factory 19200, 8 data bits, no parity, 1 stop bit, no flow control. Put a changed value in `config.json` `baud`.
- Mode: polling (the factory state). A device left streaming floods the port without its unit id; on a terminal send `@@=A` (CR) to put it back into polling as unit A.
- Engineering units: this package declares `L/min` for flows and `[psi]` (PSIA) for pressure. Read `frame` or send `A??D*` on a terminal: it lists each column with its unit (SCCM, SLPM, PSIA, ...). If your device reports SCCM, change `unit` to `mL/min` on `volumetric_flow`, `mass_flow`, `setpoint_actual` and `setpoint` in descriptor.yaml. Editing the package changes its fingerprint; the lab accepts the new version with `mhp_lab op='reload'`.
- Setpoint limit: `setpoint.limits.max` ships as 10 (a placeholder). Set it to your device's full scale or lower, to what the line downstream can take.
- Pressure controllers (PC/PCD) answer a two-column frame (pressure, setpoint): change the `parse` field numbers in descriptor.yaml (`pressure: 1`, `setpoint_actual: 2`) and remove the temperature and flow signals, and declare the setpoint in the pressure unit.

## Finding the port

Linux: `ls /dev/serial/by-id/` after plugging in. macOS: `ls /dev/tty.usbserial*`. Windows: Device Manager, Ports (COM & LPT).

## First hardware test

1. Copy `config.example.json` to `config.json`; set `port`, `unit_id`, and `baud` if it was changed.
2. `mhp serve pkg:<this folder>`; read `connected`, then `frame`. Expect a line starting with your unit letter and ending in the gas name. A blank reply means the wrong id, baud or a device in streaming mode.
3. Read `firmware` and `pressure`; compare the pressure with the display.
4. With the outlet connected to where the gas may go, write `setpoint` to a small value (e.g. 0.5), watch `mass_flow` rise to it on the display and through the package, then invoke `stop` and confirm the flow falls to zero.
5. Invoke the e-stop while flowing: the display setpoint must drop to 0 and `state` read `estop`; reset. If your valve is normally open, add `AHC` to `serial.estop` and retest.

## Status

Twin tested. Written from Alicat's Serial Communications Primer (Rev 2, 2023) and the MC/MCR operating manual (DOC-MANUAL-MPL), checked against wire captures published with the MIT-licensed `alicatlib` project; not yet run on hardware here. The reply terminator (CR only) and the exact spelling of the `?` error reply vary by firmware and are noted as unverified in protocol.md.
