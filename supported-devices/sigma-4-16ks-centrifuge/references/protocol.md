# Sigma Spincontrol serial control interface, as used by this package

Sources read: Sigma Laborzentrifugen GmbH, "Serial Control Interface Specification, Spincontrol", version V2.8, 23 August 2023, printed as appendix 11.6 of the "Refrigerated Centrifuge for Robot Use Sigma 4-5KRL / 4-5KRL IVD, Original operating manual", part no. 0703302, version 11/2017, Rev 1.9 (24 October 2023), https://www.pragolab.cz/documents/BA_4-5KRL_IVD_0703302_2017-11_1-9_en.pdf (an earlier edition, Rev 1.7.1 of December 2022, is on ManualsLib); "Sigma 4-16KS operating manual", part no. 0701702, Rev 1.26 (24 October 2023), chapter 9 (interface option). The specification states it applies to every Spincontrol model and is syntax-compatible with the older Zent2 protocol and with IKA labworldsoft. No open-source driver was found. The table is in our words.

## Link

| Item | Value |
|---|---|
| Serial | 9600 baud, 8 data bits, no parity, 1 stop bit, no hardware or XON/XOFF handshake |
| Connector | 9-pin SUB-D on the centrifuge: pin 2 TxD, pin 3 RxD, pin 5 GND; straight 1:1 cable |
| Command | a word, optionally a space and comma-separated parameters, terminated CR LF; case-insensitive |
| Reply | one line terminated CR LF; plain decimal numbers without units; `status1` is four hex digits |
| Prompt | the centrifuge prints `SIGMA>` (or `SIGMA <name>>` on a named unit) when ready, and a reset-reason line (`~hwreset`, `~wdreset`, `~exreset`, `~swreset`) after a reset |
| Echo | off by default. `echoon` echoes characters and acknowledges every command with `OK`, `CNF` (command not found), `NEA` (not enough arguments), `ERR` (not possible) or `CYCLES` (rotor/bucket cycle limit reached; a second `start` overrides). With echo off a set command answers nothing. `cmderror` returns 1 (ok), -1 (error) or 0 (no status) for the last command. |
| Timing | no documented minimum interval; the twin answers at once |

## Commands this package uses

| Command | Reply | Meaning |
|---|---|---|
| `speed` (alias `IN_PV_1`) | rpm | measured rotor speed |
| `temp` (`IN_PV_2`) | degC, signed integer | measured chamber temperature (cooled/heated models) |
| `time` (`IN_PV_3`) | integer | remaining run time; unit not printed in the specification table, seconds inferred from `settime` (unverified) |
| `getsetspeed` (`IN_SP_1`) | rpm | speed setpoint |
| `getsettemp` (`IN_SP_2`) | degC | temperature setpoint |
| `getsettime` (`IN_SP_3`) | integer | time setpoint |
| `status` | one digit | 0 rotor spinning (or lid moving), 1 standstill and the lid may be opened, 2 lid open, 3 error. Robot/hatch models: 1 also "rotor positioned", 2 "hatch open and rotor locked, ready to load" |
| `status1` | 4 hex digits | bits 1..0: 00 lid opening/closing, 01 open, 10 closed; bits 3..2: 00 wait, 01 can be opened, 10 can be closed, 11 either (hatch models); bit 4 imbalance shutdown; bit 5 spinning; bit 6 error shutdown |
| `syserror` (`geterr`) | 0 or error number (plus three servo parameters for errors 90/93/95) | current error |
| `setspeed n` (`OUT_SP_1`) | none | speed setpoint, rpm |
| `settemp n` (`OUT_SP_2`) | none | temperature setpoint, degC |
| `settime n` (`OUT_SP_3`) | none | run time in seconds; 0 = continuous |
| `start` | none (or `OK`/`ERR`/`CYCLES` with echo on) | start with the current setpoints |
| `stop` | none | stop on the set deceleration curve |
| `fstop` | none | stop with maximum deceleration |
| `door` | none | open the lid (only at standstill); the hatch-open command on hatch models |
| `reseterr` | none | clear a logged warning or error |

Not used: `close` (motorised hatch, robot models), `reset`, `setaccel`/`setdecel`/`getaccel`/`getdecel` (curves), `curr [/tn]` (snapshot table of speed, temp, status, status1, optionally repeated every n seconds), `status2` (robot models: lid/hatch and bucket-lifter bits), `info`, `getprocess` (all setpoints with a CRC), `getrotor`/`setrotor`/`getrotorlist`, program handling (`setpara`, `getpara`, `setprog`, `loadprog`), `raoss` (run time counted from reaching speed), `run n` / `setpos n` / `pos` / `lift` / `release` / `lock` / `unlock` (robot models), cycle counters (`rcycle`, `bcycle`, ...), `echoon`/`echooff`, `cmderror`.

## Parsing notes

Every numeric reply is taken by the regex `^(?:[^>]*>)?\s*(-?\d+)`, which skips a `SIGMA>` prompt if one precedes the value. `lid_closed`, `standstill` and `robot_access_ready` are the `status` digit mapped through boolean tables: lid closed = status 0 or 1; standstill = 1 or 2; robot access ready = 2 only; status 3 (error) matches no table and therefore counts as an open interlock. Set commands answer nothing with echo off, so a write returns after the 1 s serial timeout.

## Unverified

- The unit of `time` (seconds assumed).
- Where the `SIGMA>` prompt appears on the wire (before or after a reply line, with or without a terminator); the regex tolerates a prefix.
- Whether the 4-16KS as shipped has the serial socket (listed as model-dependent) and whether `settemp` is accepted on a non-refrigerated unit.
- The exact refusal when `start` is sent with the lid open and echo off (assumed silent; the twin stays at status 2).
