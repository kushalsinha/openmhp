# NE-1000 pump network protocol used by this package

Source: New Era Pump Systems, "Multi-Phaser NE-1000 Series of Programmable Syringe Pumps" user manual,
Publication 1200-01, firmware V3.923, dated 04/06/16 (syringepump.com/download/NE-1000 Syringe Pump User
Manual.pdf), chapter 10 "RS-232 Communications" and section 12.1 "RS-232 Command Summary". The NE-4000
manual (same publisher) documents the same chapter for the two-channel pump.

Serial (manual 10.2): 19200, 9600, 2400, 1200 or 300 baud; 8 data bits, no parity, 1 stop bit. Basic mode
command: `[address]<command> CR`; spaces and control characters are stripped and text is upper-cased by
the pump. Basic mode reply: `STX <address> <status> [<data>] ETX` (STX 0x02, ETX 0x03). The address is
two digits 0-99; a command without an address goes to address 0. The pump answers only after it has
processed the command and accepts nothing until then. A packet with no command is a status query.

Status letters (manual 10.2.4): `I` infusing, `W` withdrawing, `S` program stopped, `P` program paused,
`T` timed pause, `U` operational-trigger wait, `X` purging; alarms `A?R` reset (power was interrupted),
`A?S` motor stalled, `A?T` safe-mode timeout, `A?E` program error, `A?O` phase out of range. An alarm
must be acknowledged (any valid command's reply carries it) before data changes or the pump starts.

Errors in the data field (manual 10.3): `?` command not recognised, `?NA` not applicable now, `?OOR`
out of range, `?COM` invalid packet, `?IGN` ignored because a phase just started.

| Command | Meaning (manual 10.4) | Reply data | Used as |
|---|---|---|---|
| `DIA [<float>]` | set/query syringe inside diameter; set only while stopped; sets the volume units | `<float>` on query | setting `diameter_mm`, signal `diameter_actual` |
| `RAT [C|I] [<float> [UM|MM|UH|MH]]` | set/query pumping rate; units uL/min, mL/min, uL/h, mL/h; units not settable while pumping | `<float><units>` on query | setting `rate_ml_min` (`RAT <v> MM`), signal `rate_actual` |
| `VOL [<float> | UL | ML]` | set the volume to be dispensed (no units in the set), or set the volume units | `<float> <units>` on query | setting `volume_ml`, signals `target_volume`, `volume_units`; actions send `VOL ML` first |
| `DIR [INF|WDR|REV|STK]` | set/query direction; not while running with a non-zero volume | `INF`/`WDR` on query | actions `infuse` (`DIR INF`), `withdraw` (`DIR WDR`) |
| `RUN [<phase>]` | start the program (resumes if paused) | status only | actions `infuse`, `withdraw` |
| `STP` | stop and pause; a second STP resets to phase 1 | status only | action `stop`, estop |
| `DIS` | query volumes dispensed | `I<float>W<float><units>` | signals `infused_volume`, `withdrawn_volume`; polled by infuse/withdraw |
| `CLD {INF|WDR}` | clear the infused or withdrawn total; only while stopped | status only | action `clear_dispensed` |
| `SAF [<timeout>]` | 0 = Basic mode, 1-255 = Safe mode with that timeout in seconds; retained | status only | action `basic_mode` |
| `VER` | firmware version | `NE<model>V<n>.<nnn>` | signal `firmware_version` |
| `PUR` | purge at top speed until STP | | not used |
| `* ADR [<n> [B <baud>]]` | set address and baud (system command) | | not used; set once from a terminal |
| `* RESET` | clear program memory, Basic mode, address 0 | | not used |
| `PHN`, `FUN`, `LN`, `AL`, `PF`, `TRG`, `BP`, `OUT`, `IN` | program phases and I/O | | not used |

Numbers: at most four digits plus a decimal point, at most three decimals (manual 10.2.1). The rate
limits of the pump depend on the diameter (manual: a rate out of range answers `?OOR`); the
descriptor's 0.01-50 mL/min and 0.1-50 mm are placeholders.

Unverified: the reply to an address-only packet (`00` CR) in Basic mode is described as a status-only
packet and is read here as the `pump_status` signal; whether `VOL ML` is accepted before a rate has
ever been set; the NE-4000's second channel (addressed as a second pump in Dual mode, not driven here).
