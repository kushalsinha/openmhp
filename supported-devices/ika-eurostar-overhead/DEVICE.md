---
mhp: "2026-09-12"
id: ika-eurostar-overhead-01
class: stirrer
make: IKA
model: EUROSTAR 60 control / EUROSTAR 100 control
location: ""
tags: [stirring, overhead, chemistry, serial, namur]
description: IKA EUROSTAR 60 control or 100 control overhead stirrer driven over its USB or RS-232 port with the IKA NAMUR command set (IN_PV_4, OUT_SP_4, START_4, STOP_4). Reads actual speed and shaft torque, sets a speed, starts and stops the motor. Use for stirring viscous or large-volume vessels from a stand-mounted shaft; not a heater, and not for speeds above what the clamped vessel can take.
driver: driver.py:Device
sim: sim.py:Sim
---

# IKA EUROSTAR 60 / 100 control overhead stirrer

A stand-mounted overhead stirrer with a chuck-held shaft. The station answers NAMUR commands on
its RS-232 port or on the USB port of the Wireless Controller (a virtual COM port). Put the port
under `port` in `config.json` (see `references/setup.md`). The station enters remote mode on the
first command it receives; `RESET` hands control back to the knob.

An overhead stirrer can throw an unclamped vessel or wind a loose cable around the shaft. This
package caps `stir_rpm` at 1200 rpm (the EUROSTAR 60 allows 2000, the 100 allows 1300) because
the descriptor cannot ask a person to confirm only the high settings; raise the cap in
`descriptor.yaml` deliberately, for one installation, after the clamping has been checked.

## Operating procedure

1. Read `stir_rpm_actual` and `torque` to confirm the link (both answer immediately; torque reads 0 at rest).
2. Check the vessel is clamped and the shaft is centred, then write `stir_rpm` (start low, 100-200 rpm).
3. Invoke `start_stirring`. The station ramps to the setpoint; `stir_rpm_actual` follows within seconds.
4. Change `stir_rpm` while running as the viscosity changes (`during_job: true`). Watch `torque`: a rising
   value with a constant speed means the medium is thickening; the station limits itself at `torque_limit`.
5. Invoke `stop_stirring` when done. `estop` sends `STOP_4`.

## What to watch

- `torque` flashing on the display or climbing fast means the shaft is binding; stop and check the vessel.
- The station's own `speed_limit` (IN_SP_6) and `torque_limit` (IN_SP_5) are read back as signals; writing
  them needs a person's confirmation because they loosen what the station will do.
- If the Wireless Controller loses contact with the station, the station drops to its safety speed (`safety_speed`,
  100 rpm from the factory); that is the station's behaviour, not this package's.
- If the display shows an error code, the IKA manual's troubleshooting table names it; this package does not.

## Resources

- `references/setup.md`: cable, port, remote mode, first hardware test.
- `references/namur.md`: the NAMUR commands this package uses, from the IKA operating instructions.
