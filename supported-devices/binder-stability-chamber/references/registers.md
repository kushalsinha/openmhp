# Register reference: BINDER MB2 controller (TEMPLATE, unverified)

**Status of this map: every address below is a placeholder.** BINDER documents the MB2's Modbus
interface in *BINDER Interface Technical Specifications*, Art. No. 7001-0242, issue 10/2017
(38 pages; section 2.11.14 "Base address table for MB2"). That document is distributed by
BINDER service and was not available to read while this package was written; only fragments
of it surfaced in search snippets. Obtain it from BINDER, confirm every row, and rewrite the
`modbus:` block of descriptor.yaml before the first hardware use.

## What is known of the BINDER interface (from the document's summary and snippets, unverified)

- The interface is Modbus, on RS-422 for older controllers and tunnelled over TCP/IP on the
  MB2's Ethernet port.
- Setpoints and actual values are IEEE-754 floats occupying two consecutive 16-bit registers
  (the document's worked example reads a setpoint of 30 as two words). The word order was not
  visible in the fragments; the twin assumes big-endian and `word_order` in descriptor.yaml
  switches it.
- Fragments attributed to the MB2 table mention a humidity process value at base address
  0x100A (float, read-only) and a humidity setpoint at 0x10B4, with conflicting entries
  (0x11CD, 0x1079, 0x1A6D) that may belong to the older MB1 table. None of these is relied on
  below; they are the reason the placeholders sit in the 0x1000 range.
- The KBF operating manual (e.g. 7001-0284 for KBF E5.3, and the MB2 KBF 240 manual) describes
  the Ethernet interface, web server and e-mail alarms but gives no register addresses.

## Placeholder Modbus map used by descriptor.yaml

All rows **unverified**. Floats, big-endian, unit id 1, TCP port 502.

| Signal / setting | Kind | Address (dec / hex) | Type | Meaning | Verified |
|---|---|---|---|---|---|
| temperature | holding | 4096 / 0x1000 | float32 | temperature actual value | unverified |
| humidity | holding | 4106 / 0x100A | float32 | humidity actual value (snippet-attributed) | unverified |
| temperature_setpoint(_actual) | holding | 4270 / 0x10AE | float32 | temperature setpoint, read and write | unverified |
| humidity_setpoint(_actual) | holding | 4276 / 0x10B4 | float32 | humidity setpoint, read and write (snippet-attributed) | unverified |
| door_closed | discrete | 0 | bit | door contact, 1 = closed | unverified |
| alarm_active | discrete | 1 | bit | collective alarm | unverified |
| light_on | discrete | 2 | bit | interior light (KBF P ICH light) | unverified |

No program-control register (start/stop of a time or week program) was verified, so the
package declares no `start_program` / `stop_program` actions; add them as coil writes once the
document names the register. No standby coil was verified either, which is why `safety.estop`
is false.

Ranges used for the limits: KBF data sheets give 0–70 °C and 10–80 % rH (KBF P: 0–70 °C with
ICH light; KMF: -10 to 100 °C and 10–98 % rH). The attainable humidity depends on the
temperature per the climatic diagram in the operating manual; the controller refuses or
cannot reach combinations outside it.

## Memmert ICH / HPP chambers

Memmert's ICH and HPP chambers (AtmoCONTROL, Ethernet) also offer Modbus TCP; the register
map is in Memmert's "Modbus" interface description and differs from BINDER's. Copy this
package, replace the `modbus:` block from Memmert's document, and keep the same signal names.
