# Register reference: sputter tool PLC over Modbus TCP (TEMPLATE, unverified)

**Status of this map: every address below is a placeholder.** None of the three vendors publishes
a Modbus or OPC UA register map:

- AJA International, *Phase II J Installation & Operation Manual* (November 2005, revision 1; the
  copy hosted by the KTH Nanolab): describes the LabVIEW control program only. Its layer screen has
  the fields this package mirrors: power set point (percent of the supply), SHUTTER DELAY (seconds
  after the power reaches its setpoint until the shutter opens), COAT TIME (seconds the shutter
  stays open), HEAT with a setpoint and SOAK TIME, rotation, and gas flows; the process screen
  chains layers; the "IMPORTANT" note says the control laptop is set up for direct network control
  of the Phase II controller only and further networking is not recommended. AJA's current pages
  name the Phase II-Au / Phase II-XS software and a spreadsheet recipe emulator; no register map.
- Kurt J. Lesker, *PRO Line PVD 75 datasheets* (13-122 rev 2-15, 16-077): list the automation
  (eKLipse-style PLC control, recipes, interlocks) but no external protocol.
- Moorfield nanoPVD: product pages name PLC control and recipe software; no protocol document found.

Some installations expose the PLC through a Modbus TCP gateway or an OPC UA server in the vendor
software. Get the integrator's tag list, rewrite the `modbus:` block of `descriptor.yaml`, and
confirm each row on the tool before the first deposition. For OPC UA, the openmhp OPC UA adapter
route replaces this package's `modbus:` block (see openmhp/adapters).

## Placeholder Modbus map used by descriptor.yaml

All rows **unverified**. Floats are IEEE-754 in two registers, big-endian word order (`word_order`
switches it), unit id 1, TCP port 502.

| Signal / setting | Kind | Address | Type | Meaning | Verified |
|---|---|---|---|---|---|
| base_pressure | input | 100 | float32 | chamber wide-range gauge, mbar | unverified |
| process_pressure | input | 102 | float32 | capacitance manometer, mbar | unverified |
| power | input | 104 | float32 | supply forward power, W | unverified |
| substrate_temperature | input | 106 | float32 | heater thermocouple, degC | unverified |
| gas_flow | input | 108 | float32 | Ar MFC read-back, sccm | unverified |
| power_setpoint | holding | 200 | float32 | supply setpoint, W (read and write) | unverified |
| substrate_temperature_setpoint | holding | 202 | float32 | heater setpoint, degC | unverified |
| gas_flow_setpoint | holding | 204 | float32 | Ar MFC setpoint, sccm | unverified |
| shutter_open | coil | 10 | bit | target shutter (1 open) | unverified |
| plasma_on | coil | 11 | bit | supply output enable; PLC clears it on failed ignition | unverified |
| rotation_on | coil | 12 | bit | substrate rotation | unverified |
| heater_on | coil | 13 | bit | substrate heater enable | unverified |
| pumping | coil | 20 | bit | pump-down request / sequence active | unverified |
| (vent) | coil | 21 | bit | vent request | unverified |
| door_closed | discrete | 0 | bit | chamber door switch | unverified |
| base_pressure_ok | discrete | 1 | bit | PLC base-pressure permissive | unverified |
| water_flow_ok | discrete | 2 | bit | cooling-water flow switches | unverified |
| robot_access_ready | discrete | 3 | bit | load lock vented, door open, arm parked (load-lock tools only) | unverified |

The `deposit` action writes 204, 200 and coil 11 (from `modbus.actions.deposit`), waits for coil 11
to read back true, presputters, writes coil 10 (`modbus.sequences.shutter_open`), waits, then writes
coil 10 = 0, coil 11 = 0 and 200 = 0 (`modbus.sequences.deposit_finish`). The e-stop writes the same
three plus coil 13 = 0. No target-selection, gate-valve or load-lock transfer register was invented:
those stay in the vendor software.

Ranges used for the limits: placeholders for a 300 W DC supply on a 2-inch target, a 100 sccm argon
MFC, a 400 degC substrate heater and a base-pressure permissive of 5e-6 mbar; the lab sets its own.
Pressure units: the vendor software shows mTorr; 1 mTorr = 1.333e-3 mbar. If the PLC reports Torr,
add `scale: 1333.22` to the pressure rows.

## Twin

The fake PLC models an overnight-pumped chamber (2e-7 mbar), venting in about three minutes and
pumping back down in about three hours (exponential in log pressure), a plasma that strikes 3 s after
coil 11 is set when the process pressure is between 1e-3 and 2e-1 mbar and the door and water
permissives are made (otherwise the coil clears after 10 s), power following the setpoint once struck,
a heater ramping at 0.5 degC/s, and thickness growing at 8.5 nm/min per 100 W while the shutter is open
(`link.thickness_nm`), all scaled by `OPENMHP_SIM_TIME_SCALE`.
