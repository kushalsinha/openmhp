# Innova remote-programming command set, as used by this package

Sources read: New Brunswick Scientific "Innova 44 & 44R Incubator Shakers Operating Manual", M1282-0050 Revision M, chapter 12 "Appendix: Remote Programming" and section 7.4.5 (RS232 screen); Eppendorf "New Brunswick Innova 44/44R Shaker Operating manual", M1282-0050-00/112017, chapter 15; "Innova 42 & 42R Guide to Operations", M1335-0050 Rev D (2010), chapter 11; "Innova 43 & 43R User's Guide", M1320-0050 Rev E (2008), chapter 12; "New Brunswick Innova 40/40R Operating manual", M1299-0051-G/092014, section 5.14. The 2022 Innova 43 manual no longer prints the appendix. No open-source driver for these shakers was found. The table is in our words.

## Link

| Item | Value |
|---|---|
| Serial | 9600 / 19200 (factory) / 38400 baud selected on the RS232 (COMM) screen; 8 data bits, no parity, 1 stop bit, no flow control. Point-to-point, no addressing. |
| Mode (COMM screen) | Off (port closed), Slave (full control), Talk (a report every minute, unprompted), Monitor (answers report requests only) |
| Command | two upper-case letters (plus `=D`/`?D`), space-separated arguments, CR (an LF may follow) |
| Echo | every received character is echoed, CR included, before any reply; a set command's only response is the echo |
| Reply | data fields separated by Tab (RV, RS, RP, RI, ?D) or Space (PM, PR), terminated CR LF |
| Timing | 10 s between characters of one command resets the port; `OK` CR LF is sent once at power-up |
| Errors | no error reply is documented |

## Commands this package uses

| Command | Arguments | Reply after the echo | Meaning |
|---|---|---|---|
| `RV` | | speed Tab temperature Tab %RH Tab %CO2 Tab grow-lamp Tab UV-lamp | measured values (44/43/40: six fields; 42: speed, temperature, CO2). CO2 always 0.0 (never implemented); RH 0 without the humidity option. |
| `RS` | | same layout | setpoints |
| `RI` | | display firmware Tab control firmware | software revisions |
| `PM` | | run Space profile Space step | profile status: run 1 while a stored profile runs, profile and step 0 if none selected |
| `CS <rpm>` | integer `####` | echo only | speed setpoint; 0 stops shaking |
| `CT <temp>` | `###.#` | echo only | temperature setpoint, degC |
| `PS <profile> [<step>]` | 1..4, 1..15 | echo only | start a stored profile at a step (default 1) |
| `PS` | | echo only | stop the running profile |

Not used: `RP` (column headers for RV/RS), `PR <profile> <step>` (read a stored step: profile, step, temp, rpm, CO2, hours, minutes, UV, grow), `PW ...` (write a step), `PC` (clear steps), `CL`/`CU` (grow / UV lamp on 43/44), `CC`/`CH` (CO2 / humidity, listed for the 40 only, format not documented), `=D`/`?D` (clock).

## What the protocol cannot report

Whether the cabinet is open, alarms (speed or temperature deviation, imbalance, power failure, timer end), time remaining on a timed run, and a run/stop state outside stored profiles. The cabinet safety switch halts the platform in hardware; `RV` then presumably reads speed 0 (unverified).

## Parsing notes

The driver sends `RV` + CR and reads one line: because the echo (`RV` CR) carries no LF, pyserial's `readline` returns the echo and the data line together, and the field rules pick the n-th number (the echoed letters carry none). Set commands return only the echo with no LF, so a write returns after the 1 s serial timeout. `profile_running` is field 1 of `PM` mapped through the boolean tokens 0/1.

## Unverified

- Whether `CT` accepts `37` as well as `37.0` (the manual prints `###.#`; the driver sends the value as given, so write 37.0).
- Whether `PM`'s reply ends in CR LF (printed as CR in one manual).
- The shaker's response to an unknown command (none documented; the twin echoes and stays silent).
- The RS-232 connector pinout (not printed).
