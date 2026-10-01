---
mhp: "2026-09-12"
id: ika-c-mag-hs7-01
class: hotplate
make: IKA
model: C-MAG HS 7
location: ""
tags: [heating, stirring, chemistry, serial]
description: IKA C-MAG HS 7 magnetic stirrer hotplate controlled over its USB/RS-232 port with the IKA NAMUR command set. Heats to 500 degC plate temperature and stirs to 1500 rpm. Use for heating and stirring capped vessels up to about 5 L; not for open solvents near the plate and not for temperature control inside the vessel unless an external probe is fitted.
driver: driver.py:Device
sim: sim.py:Sim
---

# IKA C-MAG HS 7

A ceramic-plate stirrer hotplate. The plate surface can reach 500 °C; the `plate_temperature`
signal is the plate probe, not the liquid. Set `location` in the frontmatter to where yours sits.
Connect the USB cable, note the port (`/dev/ttyUSB0`, `/dev/tty.usbserial-*` or `COM3`) and put it
under `serial.port` in descriptor.yaml. The instrument must be in remote mode: it enters it on
the first command and shows "PC" on the display.

## Operating procedure

1. Read `plate_temperature` and `stir_rpm_actual` to confirm the link (both answer immediately).
2. Write `stir_rpm` first so the bar is moving as heat arrives, then invoke `start_stirring`.
3. Write `target_temperature`, then invoke `start_heating`. Ramp is roughly 2 °C/s at the plate.
4. Watch `plate_temperature`. When finished, invoke `stop_heating`, then `stop_stirring`.
5. `shutdown` stops both and needs a person's confirmation because the plate stays hot for minutes.

## What to watch

- The stir bar decouples above about 800 rpm with 50 mL flasks; lower the speed if `stir_rpm_actual` is unstable.
- Above 300 °C most glassware seals fail; the descriptor caps `target_temperature` at 300 unless you raise it deliberately.
- If the display shows "Er", read the manual excerpt in `references/namur.md` for the code.

## Resources

- `references/namur.md`: the NAMUR commands this package uses, from the IKA manual.
