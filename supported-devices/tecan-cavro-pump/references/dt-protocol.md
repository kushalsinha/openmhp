# Cavro DT protocol used by this package

Primary source: Tecan "Operating Manual, Cavro XLP 6000 Modular Syringe Pump", part 734237-C, revision C,
October 2005, chapter 3 "Software Communication" (sections 3.2.2 Communication Protocols, 3.6 Error Codes
and Pump Status) and appendix G "Quick Reference" (G.1-G.10), read through a manualslib mirror. Secondary:
an open-source (Apache-2.0) Cavro pump driver README, which implements the same manual.

Frames (manual 3.2.2): command block `/` (2Fh), pump address character, data block of commands, CR
(0Dh); the commands run when the block ends with `R`. Answer block `/` (2Fh), master address `0` (30h),
status character, data, ETX (03h), then CR LF. DT protocol serial parameters: 9600 or 38400 baud, 8 data
bits, no parity, 1 stop bit. Report commands answer in the data field; `Q` answers status only.

Status byte (manual 3.6): bit 5 set means ready to accept commands, clear means busy (only Report and
Terminate are accepted while busy); bits 0-3 are the error code. The manual gives no hex values; from
the bit rule, a ready byte with no error is 0x60 (`` ` ``) and a busy one 0x40 (`@`), with the error code
added (ready with error 7 is `g`). The regexes here use that mapping; unverified on hardware. Error codes
(manual G.10 and 3.6): 0 none, 1 initialisation, 2 invalid command, 3 invalid operand, 6 EEPROM failure,
7 device not initialised, 8 internal failure, 9 plunger overload, 10 valve overload, 11 plunger move not
allowed, 12 internal failure, 14 A/D converter failure, 15 command overflow. Errors clear the command
buffer; 9 and 10 persist until a successful initialisation.

| Command | Meaning (manual) | Used as |
|---|---|---|
| `Z` (`ZR`) | initialise plunger and home valve clockwise; `Y` counter-clockwise; `W` plunger only | action `initialize` |
| `A n` | absolute plunger position, 0-6000 standard (0-48000 fine/microstep) | action `move_to` |
| `P n` | relative pickup (aspirate) n increments | action `aspirate` |
| `D n` | relative dispense n increments | action `dispense` |
| `I` / `O` / `B` / `E` | valve to input / output / bypass / extra | actions `valve_input`, `valve_output` |
| `S n` | speed code 0-40 (default 11) | setting `speed_code` |
| `V n` | peak speed 5-6000 increments/s (default 1400) | setting `top_velocity` |
| `v n`, `c n`, `L n` | start speed 50-1000, cutoff speed 50-2700, slope 1-20 | not used |
| `N n` | 0 standard, 1 fine positioning (8x increments), 2 microstep | not used; steps_full_stroke in config.json must match |
| `T` | terminate the plunger move (sent without R) | action `terminate`, estop |
| `?` | report absolute plunger position | signal `plunger_position` |
| `?6` | report valve position | signal `valve_position_reply` |
| `Q` | report status byte (the only valid busy/ready source) | signal `status_reply`; polled after moves |
| `&` (`?23`) | report firmware version | signal `firmware` |
| `?1`, `?2`, `?3`, `?4`, `?10`/`F`, `?12`-`?17`, `?20`/`#`, `?24` | other reports (speeds, buffer, counters, checksum) | not used |
| `g`/`G n`, `M n`, `H n`, `X`, `J n`, `s n`/`e n`, `U n`, `K n` | loops, delays, halts, outputs, EEPROM strings, config, backlash | not used |

Stroke (manual): XLP 6000, 6000 increments per 60 mm stroke in standard mode, 48000 in fine-positioning
and microstep modes. XCalibur: 3000 increments (secondary source, from Tecan web specifications,
unverified). Volume per increment is syringe_ul / steps_full_stroke; the driver rounds to the nearest
increment.

Address mapping (secondary source, unverified in the manual pages read): switch 0 is address character
`1`, switch 1 is `2`, ... switch 8 is `9`, switches 9-E are `:;<=>?`. Position F is the self-test
(manual, figure 2-5).

Unverified: whether report commands (`?`, `?6`, `Q`, `&`) accept a trailing `R` (this package sends
them without); the hex values of the status byte; the data encoding of `?6`; XCalibur stroke count.
