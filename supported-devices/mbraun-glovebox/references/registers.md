# Register reference: MBRAUN glovebox PLC (TEMPLATE, unverified)

**Status of this map: every address below is a placeholder.** MBRAUN gloveboxes (LABstar,
UNIlab, LABmaster, MB200 workstations) are run by an MBRAUN or Siemens PLC with a touch panel;
the data sheets list a "PLC - M. Braun or Siemens PLC" control unit and an Ethernet option, and
the operating manuals (*Operating Instructions for MBRAUN Systems with TOUCH Screen Operation
Panel*; *Operating Manual Glove Box Systems MB20/MB200*) describe the O2 and H2O analyzers as
0-10 V signals into the PLC, box pressure regulation, antechamber evacuate/refill cycles, purge
and regeneration. None of the public documents lists Modbus registers; the signal list comes
with the interface option from MBRAUN service (service@mbraun.de). Obtain it for your box,
confirm every row, and rewrite the `modbus:` block in descriptor.yaml before first use.

## What is known (from the operating manuals and data sheets, no addresses)

- O2 and H2O analyzers: 0-10 V proportional to ppm, displayed by the PLC; typical working range
  below 1 ppm each.
- Box pressure: regulated by the PLC between about -15 and +15 mbar relative to the room; the
  foot pedal changes it by hand.
- Antechamber: evacuate/refill cycles with a programmable number of purges (usually 3), inner
  and outer doors interlocked against each other; the small antechamber on some boxes has the
  same logic.
- Purifier: purge valve to flush the box; regeneration of the catalyst under forming gas for
  about 24 h, during which the box is not purified.

## Placeholder Modbus map used by descriptor.yaml

All rows **unverified**. Unit id 1, TCP port 502, floats big-endian.

| Name | Kind | Address | Type | Meaning | Verified |
|---|---|---|---|---|---|
| o2_ppm | holding | 0-1 | float32 | O2 analyzer, ppm | unverified |
| h2o_ppm | holding | 2-3 | float32 | H2O analyzer, ppm | unverified |
| box_pressure | holding | 4-5 | float32 | box working pressure, mbar relative | unverified |
| antechamber_pressure | holding | 6-7 | float32 | large antechamber absolute pressure, mbar | unverified |
| antechamber_state (code) | holding | 10 | uint16 | 0 idle, 1 evacuating, 2 refilling, 3 at box pressure, 4 fault | unverified, codes invented |
| purge_state (code) | holding | 11 | uint16 | 0 off, 1 purging, 2 regenerating | unverified, codes invented |
| box_pressure_setpoint | holding | 20-21 | float32 | working pressure setpoint, mbar | unverified |
| purges | holding | 22 | uint16 | purge count for the next cycle | unverified |
| blower_on | discrete | 0 | bit | circulation blower running | unverified |
| inner_door_closed | discrete | 1 | bit | inner antechamber door closed | unverified |
| outer_door_closed | discrete | 2 | bit | outer antechamber door closed | unverified |
| antechamber_cycle_active | discrete | 3 | bit | cycle running | unverified |
| regenerating | discrete | 4 | bit | regeneration running | unverified |
| antechamber cycle start | coil | 0 | bit | momentary start | unverified |
| antechamber cycle stop | coil | 1 | bit | momentary abort | unverified |
| purge valve | coil | 2 | bit | 1 open | unverified |
| regeneration | coil | 3 | bit | 1 start, 0 abort | unverified |
| inner door release | coil | 4 | bit | momentary | unverified |
| outer door release | coil | 5 | bit | momentary | unverified |

Derived by the driver, not registers: `antechamber_state` and `purge_state` names from the codes,
`antechamber_idle` (code 0 and no cycle bit), `robot_access_ready` (inner door open and idle).
