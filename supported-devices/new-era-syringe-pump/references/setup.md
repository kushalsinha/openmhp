# Setting up a New Era NE-1000 / NE-4000

Runs on Linux, macOS or Windows: pure Python, `pip install openmhp pyserial`.

1. Cable. New Era's CBL-PC-PUMP (RJ-11 pump socket "To Computer" to 9-pin serial), with the CBL-USB232
   adapter for a USB port. Do not plug the PC cable into the "To Network" socket.
2. Pump setup (hold the Setup key): Address mode (the default), address 0 for a single pump, baud 19200
   (`1920`). Several pumps on one cable: give each its own address with `*ADR n` and run one package
   instance per address.
3. Framing: 8 data bits, no parity, 1 stop bit at 19200 (or 9600/2400/1200/300 as set on the pump);
   pyserial's defaults match. Commands end with CR; replies are bracketed by STX and ETX.
4. Find the port (`COM8`, `/dev/ttyUSB0`, `/dev/tty.usbserial-*`). Copy `config.example.json` to
   `config.json`; set `port`, and `address` if not 0.
5. Basic mode. If the pump was left in Safe mode (CRC packets), the `basic_mode` action sends `SAF 0`;
   a pump in Safe mode still accepts a Basic-mode `SAF 0`. Serve: `mhp serve pkg:<this folder> --http <port>`.

## First hardware test

1. Fit a 10 mL plastic syringe of water with a tube into a beaker. Read `pump_status` (expect `00S`; `00A?R`
   after power-up is cleared by the next command) and `firmware_version`.
2. Write `diameter_mm` 14.5; read `diameter_actual` and `volume_units` (expect `UL` at this diameter).
3. Invoke `infuse` with `volume_ml` 1.0 and `rate_ml_min` 2.0; the job should finish in about 30 s with the
   last reply a `DIS` packet reading `I1.000W0.000ML`. Weigh the water if you want the calibration record.
4. Invoke `withdraw` with `volume_ml` 1.0; read `withdrawn_volume`.
5. Start another `infuse` and invoke `estop` while it runs: the pusher must stop at once and `pump_status`
   read `00P` (paused). Record the firmware string and the date here when done.

## Status

twin tested: written from the NE-1000 Multi-Phaser user manual (Publication 1200-01, firmware V3.923,
04/06/16, chapter 10 RS-232 Communications) and the NE-4000 manual's identical chapter; not yet run on
hardware. The exact bytes of a status-only reply to an address-only packet (`00` CR) and the behaviour of
`VOL ML` sent before `RAT` on every firmware are the first things to confirm.
