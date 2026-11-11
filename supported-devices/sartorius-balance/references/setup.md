# Setting up a Sartorius SBI balance

Runs on Linux, macOS or Windows: pure Python, `pip install openmhp pyserial`.

1. Cable. The balance's RS-232 socket (9-pin, DCE wiring as in the Sartorius note) to a PC serial port
   or USB-serial adapter with a Sartorius data cable, or the balance's USB port on models that offer
   "USB as virtual COM" set to SBI.
2. Balance menu: interface operating mode **SBI**; "auto print" off; printing "manual without stability"
   (the factory settings print on request only).
3. Framing. The Sartorius factory setting on RS-232 is **9600 baud, 7 data bits, odd parity, 1 stop bit,
   hardware handshake**. The declarative serial driver opens the port with 8 data bits and no parity
   (pyserial defaults) and no handshake. Set the balance's interface to 8 data bits, no parity, no
   handshake (the menu offers 7/8 bits, odd/even/none parity, software/hardware/none handshake), or the
   first read returns garbage. Say which you chose in the Status line below.
4. Find the port: `COM6` (Device Manager), `/dev/ttyUSB0` (Linux), `/dev/tty.usbserial-*` (macOS). Copy
   `config.example.json` to `config.json` and set `port`.
5. Serve: `mhp serve pkg:<this folder> --http <port>`.

## First hardware test

1. Read `model` and `serial_number`; the serial number must match the type plate. If both come back
   empty, the balance is not in SBI mode or the framing is wrong (step 3).
2. With the pan empty invoke `zero`, then read `mass_frame`: expect a frame ending in `g` and `mass` 0.
3. Put a check weight on the pan, wait two seconds, read `mass` and compare with the certificate.
4. Put an empty vial on, invoke `tare`, add a few drops of water and read `mass_frame` at once (no unit
   while unstable) and again after a second (unit present).
5. Invoke `lock_keys`, confirm the TARE key is ignored at the balance, invoke `unlock_keys`. Record the
   model, the `software_version` string and the date here when done.

## Status

twin tested: written from the Sartorius "Entris II - Description of the Interface" technical note
(October 2020) and not yet run on hardware. The tare command letter (`T` zero/tare on Entris II; ESC T
tare on older Cubis/Secura per the Sartorius SBI interface description 98647-000-53, cited by a secondary
open-source driver README) and the frame's handling of an unstable reading are the two things to confirm first.
