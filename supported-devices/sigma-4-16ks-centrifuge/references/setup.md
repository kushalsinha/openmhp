# Setting up a Sigma 4-16KS (or other Spincontrol) centrifuge

## Which centrifuges this covers

Every Sigma centrifuge with Spincontrol electronics and the serial interface option (4-16KS, 3-18KS,
2-16KL, 8KS, and the robot variants 4-5KRL, 4-16KR) speaks the same word-oriented protocol; Sigma
prints it as the "Serial Control Interface Specification, Spincontrol" appendix of the 4-5KRL manual.
On the 4-16KS the serial connection is listed as "depending on centrifuge type, partly standard": check
for a 9-pin socket on the back, or order the option.

Other makes considered and not covered: Hettich Rotina/Rotanta/Universal/Mikro use the framed
"Centrifuge-BUS" protocol (STX/ETX frames, XOR checksum, 7E1), which the generic text driver cannot
express; Eppendorf 5910 R/Ri, 5810 R and 5430 have no public command set (the older models' RS-232 is a
service-fitted option with no published commands); Beckman and Thermo publish none either.

## What to install

- `pip install openmhp pyserial` on the computer cabled to the centrifuge (Linux, macOS or Windows; pure Python).
- A straight 1:1 DB-9 cable (the centrifuge's socket is wired like a PC's: pin 2 TxD, pin 3 RxD, pin 5 GND) or a USB-to-RS-232 adapter. Not a null-modem cable.

## Centrifuge settings

- Serial format is fixed: 9600 baud, 8 data bits, no parity, 1 stop bit, no handshake. Nothing to set on the unit.
- Leave echo off (the default). This package reads the plain replies; `echoon` would prefix every reply with the command.
- Limits in descriptor.yaml are placeholders: set `target_speed.limits.max` and `start.params.speed.limits.max` to the rating of the slowest rotor and bucket you use (the centrifuge refuses more than the fitted rotor allows, but a refusal with echo off is silent). Set the temperature range to your model (non-refrigerated units take no `settemp`: remove the setting and the parameter). Editing the package changes its fingerprint; the lab accepts the new version with `mhp_lab op='reload'`.
- The lid: `door` releases the lock at standstill. A robot cell needs a fixture to close it (or a robot model with a motorised hatch and the `close` command).

## Finding the port

Linux: `ls /dev/serial/by-id/` after plugging in the adapter. macOS: `ls /dev/tty.usbserial*`. Windows: Device Manager, Ports (COM & LPT).

## First hardware test

1. Copy `config.example.json` to `config.json` and set `port`.
2. `mhp serve pkg:<this folder>`; read `connected`, then `status_code` (expect 1 with the lid closed and the rotor still, 2 with it open) and `speed`, `temperature`.
3. Read `status_flags` and `speed_setpoint` to see the raw replies. If a reply looks like `SIGMA>1000`, the prompt is being read with the value; the parse rules skip it, but note it for the maintainer.
4. With a balanced, closed rotor, invoke `start` with `speed` 500, `time_s` 60. Watch `speed` rise and `time_remaining` fall; invoke `stop` and wait for `standstill`.
5. Invoke `open_lid` (confirm) and check `robot_access_ready` reads true with the lid open. Close the lid, start a short spin, invoke the e-stop: the rotor must brake hard and `state` read `estop`; reset.

## Status

Twin tested. Written from Sigma's "Serial Control Interface Specification, Spincontrol, V2.8" (23 August 2023), as reproduced in the 4-5KRL operating manual (part no. 0703302, Rev 1.9, October 2023), and the 4-16KS operating manual (part no. 0701702, Rev 1.26) for the interface option; not yet run on hardware. Whether `time` reports seconds, and where the `SIGMA>` prompt appears relative to a reply, are unverified (protocol.md).
