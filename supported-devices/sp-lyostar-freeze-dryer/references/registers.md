# Register reference: SP LyoStar 3 / 4 (TEMPLATE, unverified)

**Status of this map: every address below is a placeholder.** SP Scientific's LyoStar 3 and
LyoStar 4 are controlled by SP's LyoS / Telstar-derived SCADA software on a PC in front of a
PLC; Martin Christ's Epsilon 2-4 LSCplus by its LPCplus controller with LyoLogplus. Their tag
lists (OPC DA/UA server tags, or the PLC's Modbus map) are given to customers by the vendor's
service organisation and are not published; none was available while this package was
written. Obtain the tag or register list for your unit, confirm every row, and rewrite the
`modbus:` block of descriptor.yaml before the first hardware use.

## Sources read

- SP Scientific LyoStar 3 product literature and the LyoStar 4 brochure (shelf range -70 to
  +60 °C, condenser -85 °C, capacitance manometer and Pirani gauge, ControLyo nucleation,
  SMART freeze-dryer option, 21 CFR Part 11 SCADA): the signals and their ranges.
- Martin Christ Epsilon 2-4 LSCplus catalogue and LSCplus instruction manual rev. 1.4 (2014):
  -70 to +60 °C, 4 kg/24 h condenser, process documentation over USB/Ethernet, no protocol
  description.
- Searches for "LyoStar Modbus", "LyoS OPC", "LPCplus Modbus" found no register map.

The ranges used for limits are the LyoStar's: shelf setpoint -60 to 60 °C (the shelf reaches
-70), chamber pressure setpoint 0.01–1 mbar (controller range is roughly 10 µbar to
atmosphere).

## Placeholder Modbus map used by descriptor.yaml

All rows **unverified**. Temperatures as signed 16-bit tenths of a degree, pressures as
32-bit floats in mbar (big-endian), unit id 1, TCP port 502.

| Signal / setting / action | Kind | Address | Type, scale | Meaning | Verified |
|---|---|---|---|---|---|
| shelf_temperature | input | 0 | int16 × 0.1 °C | shelf temperature | unverified |
| condenser_temperature | input | 1 | int16 × 0.1 °C | condenser coil temperature | unverified |
| product_temperature_1..3 | input | 2, 3, 4 | int16 × 0.1 °C | product thermocouples | unverified |
| phase_code | input | 5 | uint16 | recipe phase code (table below) | unverified |
| chamber_pressure | input | 10–11 | float32 mbar | capacitance manometer | unverified |
| pirani_pressure | input | 12–13 | float32 mbar | Pirani gauge | unverified |
| door_closed | discrete | 0 | bit | chamber door contact, 1 = closed | unverified |
| vacuum_ok | discrete | 1 | bit | pressure in band and pump healthy | unverified |
| idle | discrete | 2 | bit | no recipe and no defrost active | unverified |
| recipe_running | coil (read) | 0 | bit | run coil read back | unverified |
| shelf_setpoint | holding | 100 | int16 × 0.1 °C | manual shelf setpoint | unverified |
| chamber_pressure_setpoint | holding | 101–102 | float32 mbar | manual pressure setpoint | unverified |
| start_recipe | holding 110 then coil 0 | 110, 0 | uint16 recipe number; coil 1 | select recipe, set run | unverified |
| hold | coil | 1 | 1 | hold current step | unverified |
| stop_recipe | coil | 0 | 0 | clear run | unverified |
| defrost_condenser | coil | 2 | 1 | start defrost (controller clears it) | unverified |
| estop | coil 0 → 0, coil 3 → 0 | 0, 3 | bits | clear run, shelf-heater enable off | unverified |

### Phase codes (placeholder coding)

| code | phase |
|---|---|
| 0 | idle |
| 1 | loading / ready |
| 2 | freezing |
| 3 | annealing |
| 4 | primary drying |
| 5 | secondary drying |
| 6 | hold |
| 7 | stoppering / venting |
| 8 | defrost |
| 9 | alarm hold |

Replace this table with the controller's own enumeration; the `phase_code` notes in
descriptor.yaml must match it.

## Martin Christ Epsilon 2-4 LSCplus

The same signals exist (shelf, condenser, product probes, Pirani and capacitance manometer,
section/phase, vacuum). Copy this package, rename make/model, and fill the `modbus:` block from
Christ's interface description for LPCplus; the recipe number becomes the program number.
