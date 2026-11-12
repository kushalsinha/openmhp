# Setting up an Innova 44/44R (or 40/42/43) incubator shaker

## Which shakers this covers

Eppendorf / New Brunswick Innova 40, 42, 43 and 44 (and their R refrigerated variants) print the same
two-letter remote-programming command set in their manuals; this package is written for the 44/44R and
notes where the 42 differs (three-field reports, no lamp commands). Later Eppendorf shakers (Innova S44i)
use Ethernet and VisioNize, not this protocol. **Kuhner** ISF1-X / Climo-Shaker units talk CAN bus with
optional USB/Ethernet gateways and a vendor-supplied protocol that is not published; **Infors HT**
Multitron / Minitron units have an RS-232 or Ethernet interface whose protocol Infors sends on request.
Neither can be driven by this package; ask the vendor for the protocol and write a sibling package.

## What to install

- `pip install openmhp pyserial` on the computer cabled to the shaker (Linux, macOS or Windows; pure Python).
- A straight DB-9 RS-232 cable (or USB-to-RS-232 adapter) to the RS-232 socket on the right side of the control panel, below the power switch. The pinout is not printed in the manual; if nothing answers with a straight cable, try a null-modem cable.

## Shaker settings (RS232 / COMM screen on the front panel)

- Mode: **Slave** so the package can write setpoints (Monitor answers reports only; Off closes the port; Talk sends a report line every minute unprompted, which would confuse the driver).
- Baud: 9600, 19200 (factory) or 38400; 8 data bits, no parity, 1 stop bit, no flow control. Put the value in `config.json` `baud`.
- The shaker sends `OK` once at power-up; the driver ignores stray lines.
- Limits in descriptor.yaml are placeholders: set `target_speed.limits.max` to your platform's rating (clamp platforms with 2 L flasks are usually limited to 200 rpm) and `target_temperature.limits` to what your unit and organisms allow. Editing the package changes its fingerprint; the lab accepts the new version with `mhp_lab op='reload'`.
- Innova 42: its `RV`/`RS` reports have three fields (speed, temperature, CO2); delete the `humidity` signal and its parse rule.

## Finding the port

Linux: `ls /dev/serial/by-id/` after plugging in the adapter. macOS: `ls /dev/tty.usbserial*`. Windows: Device Manager, Ports (COM & LPT).

## First hardware test

1. Copy `config.example.json` to `config.json`; set `port` and, if changed, `baud`.
2. `mhp serve pkg:<this folder>`; read `connected`, then `firmware` (two revision letters) and `speed`, `temperature`; compare with the display.
3. With the platform clamped and loaded as for a run, write `target_speed` 100 and watch `speed` rise to 100 within a few seconds; write `target_speed` 0 and watch it fall.
4. Write `target_temperature` to the current setpoint plus 0.5 and read `temperature_setpoint` to confirm the shaker accepted the one-decimal format (`CT 37.5`). If the setpoint did not change, try a value with a decimal (`37.0` rather than `37`).
5. Invoke the e-stop while shaking: the platform must stop and the temperature setpoint go to 20.0; `state` reads `estop`; reset and restore the setpoints.

## Status

Twin tested. Written from the Innova 44/44R operating manual (M1282-0050, Revision M, chapter 12 "Remote Programming", and the Eppendorf edition M1282-0050-00/112017, chapter 15), cross-read with the Innova 42 (M1335-0050 Rev D), 43 (M1320-0050 Rev E) and 40 (M1299-0051) manuals; not yet run on hardware. Whether `CT` accepts an integer without a decimal and what the shaker answers to an unknown command are unverified (protocol.md).
