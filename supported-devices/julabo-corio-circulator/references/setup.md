# Setting up a JULABO CORIO / MAGIO / DYNEO circulator

Runs on Linux, macOS or Windows: pure Python, `pip install openmhp pyserial`.

1. Cable. USB-B on the unit to the PC (install the JULABO USB driver from julabo.com; on Windows the
   unit appears as "STMicroelectronics Virtual COM Port"), or a serial cable on the RS-232 socket of
   units that have one.
2. Find the port: `COM4` (Device Manager), `/dev/ttyACM0` or `/dev/ttyUSB0` (Linux), `/dev/tty.usbmodem*`
   (macOS). Copy `config.example.json` to `config.json` and set `port`.
3. Baud and framing. The USB virtual COM port ignores the baud setting; leave 9600. On RS-232 the
   JULABO factory default on older units is **4800 baud, 7 data bits, even parity, 1 stop bit, hardware
   handshake (RTS/CTS)**; set `baud` to 4800 in `config.json`. The descriptor's `serial:` block declares
   `bytesize: 7` and `parity: E`, which the driver passes to pyserial; the driver does not drive RTS/CTS,
   so on a unit that insists on hardware handshake set its interface menu to no handshake (possible on
   CORIO/MAGIO/DYNEO with remote control off). Say which you did in the Status line below.
4. Remote mode. CORIO CD: press and hold both arrow keys until the display shows `rOn`. CORIO CP, MAGIO,
   DYNEO: menu, Connect unit, Remote control, USB or RS232 (an "R" appears in the status bar). Without it
   the unit answers reads but ignores every `out_` command.
5. Serve: `mhp serve pkg:<this folder> --http <port>`.

## First hardware test

1. Fill the bath with water to the mark; set the unit's high-temperature protection to 60 degC for the test.
2. Read `firmware_version`, `status_text`, `bath_temperature`, `temperature_setpoint_actual`. `status_text`
   should read `02 REMOTE STOP`; if it reads `00 MANUAL STOP` the unit is not in remote mode.
3. Write `target_temperature` 30, invoke `start_circulation`, confirm `circulating` is true and
   `status_text` is `03 REMOTE START`, and watch `bath_temperature` rise.
4. Write `target_temperature` 25 while running; confirm `temperature_setpoint_actual` follows.
5. Invoke `estop`; confirm the pump stops and `circulating` reads false. Then narrow the limits of
   `target_temperature` in `descriptor.yaml` to your bath fluid and record the firmware string here.

## Status

twin tested: written from the JULABO CORIO CD original operating manual (1.950.0800.us.V10, 03/2022,
section 11.1 Interface commands) and not yet run on hardware. `in_pv_02` (external Pt100) and the
4800/7E1 RS-232 default are taken from a secondary open-source (Apache-2.0) driver README, which cites the
CORIO CP, MAGIO and DYNEO manuals; both are unverified here. The `03 REMOTE START` status string is
inferred from the three documented ones and unverified.
