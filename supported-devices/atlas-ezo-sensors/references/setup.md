# Setting up an Atlas Scientific EZO circuit

Runs on Linux, macOS or Windows: pure Python, `pip install openmhp pyserial`.

1. Hardware. Seat the EZO circuit on a carrier (Atlas USB carrier, Tentacle/Whitebox isolated carrier, or a
   plain 3.3/5 V USB-serial adapter: TX to RX, RX to TX, GND, VCC). Use an isolated carrier when the probe
   shares liquid with pumps, heaters or other electrodes.
2. UART mode. The circuit must be in UART mode: green LED at rest. A blue LED means I2C; switch it by
   shorting TX to PGND at power-up (datasheet "change to UART mode") or through its I2C `Baud` command.
3. Serial: 9600 baud, 8 data bits, no parity, 1 stop bit (the EZO default; pyserial's defaults match).
   Commands and replies end in CR.
4. Find the port (`COM7`, `/dev/ttyUSB0`, `/dev/tty.usbserial-*`). Copy `config.example.json` to
   `config.json`, set `port` and `circuit`.
5. Serve: `mhp serve pkg:<this folder> --http <port>`. The first action on a new circuit must be
   `configure_for_polling`; without it every reply is followed by `*OK` on a second line and reads come
   back one reply late.

## First hardware test

1. Invoke `configure_for_polling`. Read `circuit_info`: expect `?i,<circuit>,<firmware>` matching `circuit`.
2. Read `status_text` (`?Status,P,5.0xx`) and `calibrated`.
3. Put the probe in a known standard (pH 7 buffer, 1413 uS/cm, air for DO, ice water for RTD) and read the
   matching signal; compare with the standard.
4. Write `temperature_compensation` 25.0 (not on RTD) and read `temperature_compensation_actual`.
5. If the circuit is uncalibrated, run the calibration sequence for its type from `ezo-commands.md`, each
   step confirmed, and read `calibrated` afterwards. Record the firmware string and the date here.

## Status

twin tested: written from the Atlas Scientific EZO-DO datasheet (V 5.8, revised 3/25) and EZO-RTD
datasheet (V 3.7, revised 10/24); the pH, ORP and EC datasheets could not be read when this package was
written (their PDFs exceeded the fetch limit), so the pH, ORP and EC calibration commands and the default
compensation temperature of those circuits are unverified and marked so in `ezo-commands.md`. Not yet
run on hardware.
