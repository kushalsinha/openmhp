# Setting up a Pfeiffer TPG 361/362/366 or TPG 261/262

## What to install

- `pip install openmhp pyserial` on the computer the controller is cabled to (Linux, macOS or Windows; the driver is pure Python).
- TPG 36x over USB: a USB-A to USB-B cable. The controller contains an FTDI chip and appears as a virtual COM port; on Windows install the FTDI VCP driver if nothing appears.
- TPG 26x: a straight 9-pin RS-232 cable (or a USB-to-RS-232 adapter) to the controller's RS232 socket.
- TPG 36x over Ethernet: this package opens a serial port only. Pfeiffer's "Ethernet Configuration Tool" can map the controller's IP to a virtual COM port on Windows; name that port here. Third-party drivers reach the mnemonic protocol directly on TCP port 8000 (not confirmed in a Pfeiffer document); a socket route would need a small driver change.

## Controller settings

- Serial format is fixed at 8 data bits, no parity, 1 stop bit, no handshake. Baud: `BAU` on the controller, factory default 9600 (36x USB allows up to 115200; RS-485 is fixed at 9600). Put the same value in `config.json` `baud`.
- Unit: set the controller to mbar (parameter `UNI` = 0). The TPG 36x ships in hPa (`UNI` = 4), which is numerically identical to mbar; Torr or Pa would make the `pressure_n` signals mislabelled. Read `unit_code` to check.
- On a TPG 366 the `SEN` and `DGS` commands must carry one value per channel (six). Edit the `serial:` block of descriptor.yaml: `sensor_1_on: "SEN,{value},0,0,0,0,0"`, `sensors_off: ["SEN,1,1,0,0,0,0"]`, `estop: ["SEN,1,1,0,0,0,0"]`, `degas_1: ["DGS,1,0,0,0,0,0"]`. Editing the package changes its fingerprint; the lab accepts the new version with `mhp_lab op='reload'`.
- Gauge switch-on protection: configure the controller's `SCx` (switch-on/switch-off control) so a hot-cathode or cold-cathode head cannot be switched on above its safe pressure, typically via the Pirani on the other channel. This package asks a person to confirm every switch-on, but the controller's interlock is what protects the head.
- Set `limits` and notes in descriptor.yaml to what your heads are: nothing in this package bounds a pressure, because the heads report whatever they see.

## Finding the port

Linux: `ls /dev/serial/by-id/` (the FTDI entry) or `dmesg | tail` after plugging in. macOS: `ls /dev/tty.usbserial*`. Windows: Device Manager, Ports (COM & LPT).

## First hardware test

1. Copy `config.example.json` to `config.json`, set `port` (and `baud` if changed on the controller).
2. `mhp serve pkg:<this folder>` and read `connected`, then `identity` (36x) or `gauge_types` (any model). The reply should list your heads, e.g. `TPR/PCR,IKR`.
3. Read `unit_code`; make it 0 (or 4 on a 36x) before trusting the pressure signals.
4. Read `status_1` and `pressure_1` and compare with the front panel. Repeat for channel 2.
5. With the chamber at a pressure safe for the head (below 1e-3 mbar for a cold cathode, below 1e-5 mbar for a hot cathode), write `sensor_2_on: true` (needs confirmation), watch `status_2` go from 4 to 0, then `sensors_off`. Finally invoke the e-stop and confirm the front panel shows both heads off.

## Status

Twin tested. The command map is written from the Pfeiffer communication protocol manuals (BG 5511 for the TPG 366, BG 5510 for the TPG 361/362, BG 5196 for the TPG 262) and has not yet been run on hardware. The Ethernet TCP port and the TPG 361's `PRX` field count are unverified (see protocol.md).
