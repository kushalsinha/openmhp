# Setting up the EUROSTAR 60 / 100 control

Runs on Linux, macOS or Windows: pure Python, `pip install openmhp pyserial`.

1. Cable. Either the IKA PC 1.1 cable from the station's RS-232 socket to the PC, or a USB cable from
   the Wireless Controller's USB port. For USB, install the IKA USB driver from ika.com first; the
   controller then appears as a virtual COM port.
2. Find the port: `COM3` (Windows Device Manager, "Ports"), `/dev/ttyUSB0` (Linux, `dmesg | tail`),
   `/dev/tty.usbserial-*` (macOS, `ls /dev/tty.*`). Copy `config.example.json` to `config.json` and
   set `port`.
3. Framing. The IKA manual specifies 9600 bit/s, 7 data bits, even parity, 1 stop bit, no flow control,
   for RS-232 and for the virtual COM port alike. The descriptor's `serial:` block declares `bytesize: 7`
   and `parity: E`, which the driver passes to pyserial. If the first read returns garbage or nothing,
   framing is the first thing to check: open the port once with a terminal at 7E1 to confirm the station
   answers, and report the result so the package can be marked hardware tested.
4. Remote mode: the station enters it on the first command and shows it on the display. Nothing has to be
   enabled in the menu. `RESET` (the `release_to_local` action) hands control back to the knob.
5. Serve: `mhp serve pkg:<this folder> --http <port>`.

## First hardware test

1. Clamp an empty beaker of water under a plain paddle shaft; nothing fragile, nothing flammable.
2. Read `device_name`, `stir_rpm_actual`, `torque`, `speed_limit`, `torque_limit`. All should answer within a
   second. Confirm `speed_limit` matches what the station's menu shows (`Speed Limit`).
3. Write `stir_rpm` 150, invoke `start_stirring`, and watch `stir_rpm_actual` climb to 150 within a few seconds.
4. Write `stir_rpm` 300 while running (a `during_job` setting) and confirm it follows.
5. Invoke `stop_stirring`, then `estop` once, and confirm the motor stops both times. Note the station's
   firmware (the display's info screen) here when done.

## Status

twin tested: written from the IKA operating instructions (document 20000003965c, 03/2018) and not yet
run on hardware. The reply format (`<value> <channel>`) and the error reply to an unknown command are
taken from the sibling `ika-c-mag-hs7` package, not from the manual, which documents commands only.
