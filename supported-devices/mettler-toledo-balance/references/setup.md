# Setting up a Mettler Toledo MT-SICS balance

Runs on Linux, macOS or Windows: pure Python, `pip install openmhp pyserial`.

1. Cable. RS-232 socket on the balance to a PC serial port or USB-serial adapter (a straight cable on
   most models; Mettler sells the right one per balance), or the balance's USB device port with the
   Mettler Toledo USB driver (a virtual COM port).
2. Balance settings: in the interface (peripheral) menu set the port to `Host`, 9600 baud, 8 data bits,
   no parity, 1 stop bit, no handshake. Those are the MT-SICS factory settings (`COM` reply `0630` in
   the manual). The declarative driver opens the port 8N1, which matches.
3. Find the port: `COM5` (Device Manager), `/dev/ttyUSB0` (Linux), `/dev/tty.usbserial-*` (macOS). Copy
   `config.example.json` to `config.json` and set `port`.
4. Set `tare_preset`'s max in `descriptor.yaml` to the capacity `balance_data` reports.
5. Serve: `mhp serve pkg:<this folder> --http <port>`.

## First hardware test

1. Read `serial_number` and `balance_data`; the serial number must match the type plate.
2. With the pan empty invoke `zero` and read `mass_stable` (expect 0.0000 g).
3. Put a check weight on the pan and read `mass_stable`; compare with the weight's certificate.
4. Put an empty vial on, invoke `tare`, add a few drops of water and read `mass_stable` and
   `mass_immediate` while the reading settles (expect S D then S S in the balance's own log).
5. Invoke `display_text` with "MHP TEST" and then `show_weight`; both should be visible at the balance.
   Record the balance model, the I3 software version and the date here when done.

## Status

twin tested: written from the METTLER TOLEDO MT-SICS Reference Manual for Excellence balances
(XP/XS/XA, document 11780711, revision D) and not yet run on hardware. Replies are spelled with a
space after the command id in this package's sim (`S S 12.3456 g`); the manual's examples print them
without (`SS100.00g`) but describe the frame as id, blank, status, blank, value, unit. Both parse.
