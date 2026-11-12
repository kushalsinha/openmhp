# Setting up a Quantos / XPR powder dosing balance on MT-SICS

**Template package for the dosing commands.** The balance commands are verified against Mettler's
XPR/XSR MT-SICS manual; the three dosing commands (QDS, QDR, QDH) are placeholders. Ask Mettler
Toledo for the dosing command set for your balance and head, write it into `descriptor.yaml` and
`references/mt-sics.md`, and rehearse with the twin until then.

Runs on Linux, macOS or Windows: pure Python, `pip install openmhp pyserial`.

1. Cable. The balance's RS-232 socket to a PC serial port or USB-serial adapter, or the balance's
   USB device port with the Mettler Toledo USB driver (a virtual COM port). The dosing head is
   carried by the balance and has no port of its own.
2. Balance settings: in the interface (peripheral) menu set the port to `Host` or `MT-SICS`,
   9600 baud, 8 data bits, no parity, 1 stop bit, no handshake (the factory settings). On an XPR
   also set the tolerance profile so that mg targets with two decimals are accepted.
3. Find the port: `COM5` (Device Manager), `/dev/ttyUSB0` (Linux), `/dev/tty.usbserial-*` (macOS).
   Copy `config.example.json` to `config.json` and set `port`.
4. Limits: `target_mg` and `target_mass` max 5000 mg is a placeholder for a standard head; set it
   to the head's capacity. Set `tare_preset`-style limits as your SOP needs.
5. Serve: `mhp serve pkg:<this folder> --http <port>`.

## First hardware test

1. Read `serial_number` and `balance_data`; the serial must match the type plate.
2. With an empty pan invoke `zero` and read `mass_stable` (expect 0.0000 g).
3. Write `target_mass` 25 and `tolerance_plus` 2; the SmartTrac on the display must show the
   target. `A10 L` means the unit or decimals are refused: see `references/mt-sics.md`.
4. Send `I0` by hand (any terminal) and look for dosing commands in the list; write the ones
   Mettler named into descriptor.yaml, then read `head_present` with and without the head.
5. With a tared vial and a known powder: invoke `dose {target_mg: 25, tolerance_pct: 2}` and
   compare `dispensed_mg` with `mass_stable`. Record the balance model, the I3 software version,
   the head type and the date here when done.

## Status

template: the balance commands are from the XPR/XSR MT-SICS reference manual; the dosing commands
are unverified placeholders because Mettler publishes none; not yet run on hardware.
