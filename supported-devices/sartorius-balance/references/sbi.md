# SBI commands and frame used by this package

Primary source: Sartorius "Entris II - Description of the Interface", technical note, October 2020
(sartorius.hr, entris-ii-technical-note-en-sartorius.pdf). Secondary: an open-source (Apache-2.0) SBI balance
driver README, which cites the Sartorius SBI
interface description 98647-000-53 and the Secura/Quintix/Practum (WSE6004) and Cubis (WMS6004,
WMC6028) manuals. Nothing here was copied from those documents; the tables are in this package's words.

Serial (Entris II note, factory settings): RS-232, 9600 baud, 7-bit ASCII with odd parity, 1 stop bit,
hardware handshake; selectable 600-115200 baud, 7 or 8 data bits, odd/even/no parity, software/hardware
handshake. Operating mode must be SBI.

Command formats (note): format 1 is `ESC <letter> CR LF`; format 2 is `ESC <code>_ CR LF`. ESC and LF
are marked optional in the note; this package sends them. Control commands produce no acknowledgement.

| Command | Meaning (note) | Used as |
|---|---|---|
| `ESC P` | print once (or toggle auto print if that is enabled) | signals `mass`, `mass_frame` |
| `ESC T` | zero/tare command | action `tare` |
| `ESC U` | TARE key | not used (T chosen as the cross-generation tare) |
| `ESC V` | ZERO key | action `zero` |
| `ESC O` | block keys | action `lock_keys` |
| `ESC R` | unblock keys | action `unlock_keys` |
| `ESC S` | restart / self-test | action `restart` |
| `ESC Z` | perform internal adjustment (balances with an internal weight) | action `internal_adjustment` |
| `ESC W` | adjustment as set in the menu | not used |
| `ESC K` / `L` / `M` / `N` | ambient-condition filter very stable / stable / unstable / very unstable | not used (not a keypad lock, contrary to an earlier assumption) |
| `ESC kP` | PRINT key output to all interfaces | not used |
| `ESC x1_` | print model number | signal `model` |
| `ESC x2_` | print serial number | signal `serial_number` |
| `ESC x3_` | print software version (old notation; `x20_` new) | signal `software_version` |
| `ESC f3_` / `f4_` | ZERO / TARE keys (Essential line) | not used |

Data output frame (note): 16 characters: position 1 sign (`+`, `-` or space), 2-10 the value with
decimal point (unused digits as spaces), 11 space, 12-14 unit symbol, 15-16 CR LF; or 22 characters
with a 6-character id before it (`N` net, `G#` gross, `T` tare, `Stat` for status lines such as
`Stat ERR ###`, `Stat APP.ERR`). The unit field is blank while the reading is not stable (secondary
source quoting 98647-000-53: no unit symbol is output while the weighing system has not stabilised).
The driver's `_text` joins a sign separated from its digits by spaces so `-   0.0012 g` parses as
-0.0012; the parse rule for `mass` then takes the signed number followed by a space.

Unverified: the exact id strings and column of the sign in the 22-character frame on each model; the
reply text of `x1_`/`x2_`/`x3_` (the note says "print", with no example); whether `ESC Z` answers at all;
and whether Cubis II accepts any MT-SICS-style command (nothing read says so, so SBI is used).
