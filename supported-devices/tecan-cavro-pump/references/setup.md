# Setting up a Tecan Cavro XLP 6000 / XCalibur

Runs on Linux, macOS or Windows: pure Python, `pip install openmhp pyserial`.

1. Cable. The pump's RS-232 connector to a PC serial port or USB-serial adapter (Tecan's cable or the
   pin-out in the operating manual). Power the pump from its 24 V supply.
2. Address switch: position 0 is DT address character `1`, which this package's frames use. Other
   positions give `2`..`9` and `:;<=>?`; edit the `/1` prefixes in `descriptor.yaml` if you cannot use 0.
   Power-cycle after changing the switch. Position F runs the self-test: do not leave it there.
3. Serial: 9600 baud (38400 if the pump was set with `U47`), 8 data bits, no parity, 1 stop bit; pyserial's
   defaults match. Frames end with CR; answers end with ETX CR LF.
4. Find the port (`COM9`, `/dev/ttyUSB0`, `/dev/tty.usbserial-*`). Copy `config.example.json` to
   `config.json`; set `port`, `syringe_ul` (the fitted syringe) and `steps_full_stroke` (6000 for an
   XLP 6000 in standard mode, 48000 with fine positioning on, 3000 for an XCalibur).
5. Serve: `mhp serve pkg:<this folder> --http <port>`.

## First hardware test

1. Fit the syringe with its input tube in a beaker of water and the output tube in an empty one. Read
   `firmware` and `status_reply`.
2. Invoke `initialize` (confirmed); the plunger runs to the top and the valve homes. Read `plunger_position`
   (expect 0) and `status_reply` (expect a ready byte with error 0).
3. Invoke `valve_input`, `aspirate` 500 uL (half a 1 mL syringe), read `plunger_position` (expect 3000
   on an XLP 6000); `valve_output`, `dispense` 500 uL, read `plunger_position` (expect 0). Weigh the
   dispensed water if you want the calibration record.
4. Write `speed_code` 20 and repeat step 3; the move takes visibly longer.
5. Start an `aspirate` of 1000 uL and invoke `estop` while it moves: the plunger must stop at once and
   `plunger_position` must read a value between 0 and 6000. Then `initialize` again. Record the firmware
   string and the date here when done.

## Status

twin tested: written from the Cavro XLP 6000 Modular Syringe Pump Operating Manual (Tecan, part
734237-C, October 2005, chapter 3 and appendix G, read through a third-party mirror) and not yet run
on hardware. The exact byte values of the status character, the address-switch mapping and whether
report commands accept a trailing R are marked unverified in `dt-protocol.md`.
