# Setting up an Agilent 708-DS: read this first

## This package is a template

Agilent does not publish the 708-DS serial command set. On its own community forum (thread "708-DS
RS232 Command List?") Agilent staff answer that there is no command list or documentation for control
by third-party software: the apparatus is driven by Dissolution Workstation (G4974AA, now OpenLab
Dissolution Workflow Manager G7903AA) or by the UV dissolution software, and they point to
dissolution.hotline@agilent.com. No SDK, API or open-source driver exists. The older VanKel VK 7000 /
7010 / 7025 manuals state that the main-menu settings can be queried and changed over RS-232 but print
no commands either.

What is known (references/protocol.md): a 25-pin RS-232 port on the drive head, 9600 baud, a
two-digit Comm ID (default 01) that host software addresses as `COMx:nn`, and three real frames
captured in Agilent's own tester-driver log showing a 10-character numeric frame format. Every
frame in this package's `serial:` block except the identity query is a **placeholder with letters in
the code field**, chosen so that a real 708-DS rejects it. **The commands must be confirmed against your
lab's documentation or a protocol trace before this package is used on hardware**, and until then the
only thing to run is the twin (`sim.py`).

## How to get the real command set

1. Ask Agilent (dissolution.hotline@agilent.com) for the 708-DS serial interface description, citing the forum thread; a service contract sometimes unlocks it.
2. Or trace it: the ChemStation "Dissolution Tester Driver" (AgtBath.exe) has a documented `/log` switch that writes every frame sent and received to a log file; Dissolution Workstation can be observed with a serial tap (a Y cable and a second PC port, or a USB serial sniffer) while a person uses its manual-control screen to set speed, set temperature, start, stop, raise and lower the head and fire the DDM. Record each frame next to the action.
3. Replace the placeholder frames in descriptor.yaml, update `references/protocol.md` with the trace, set the parse rules to the real data encoding (temperatures appear to be ttt.t as four digits; the VK 750D circulator, which shares the frame family, encodes them that way), and rerun `mhp validate`, `mhp rubric` and `mhp inclusion`. Editing the package changes its fingerprint; the lab accepts the new version with `mhp_lab op='reload'`.

## Cabling and port (once the frames are known)

- `pip install openmhp pyserial` on the computer cabled to the apparatus (Linux, macOS or Windows; pure Python).
- Agilent cable 5075-0552 (DB9 to DB25, single tester) or 5075-0252 from the Dissolution Workstation kit; a USB-to-serial adapter such as Agilent 8121-1013 is what Agilent recommends. Daisy-chained testers use the RJ-11 "RS232 in/out" sockets with the 5075-0260 adapter kit.
- 9600 baud (fixed on the 708-DS; required by all Agilent dissolution equipment); data bits, parity and stop bits are not documented (8N1 assumed, unverified).
- Comm ID: Menu > Instrument > Instrument Settings 1 on the 708-DS; the placeholder frames use 01.
- While under remote control the 708-DS shows "Remote Control" and locks its touchscreen; a person stops it with the front-panel STOP key or the mains switch.
- Firmware: OpenLab DWM requires 708-DS firmware 3.01 or later; older VK 7000 units need 2.02 for sampler control.

## First hardware test (only after the frames are confirmed)

1. Copy `config.example.json` to `config.json`, set `port`.
2. `mhp serve pkg:<this folder>`; read `connected`, then `identity`; compare with the log of the vendor software.
3. Read `bath_temperature` and `paddle_speed` with the bath at temperature and spindles stopped; compare with the display.
4. Write `paddle_speed_setpoint` 50 (confirm), invoke `start_run` (confirm) with the head over empty vessels; watch `paddle_speed` and `run_state`; invoke `stop_run`.
5. Invoke the e-stop while spindles turn: they must stop and `state` must read `estop`; reset. Only then run a method with medium.

## Status

Template. The signals, settings and actions describe a 708-DS; the serial frames are placeholders marked unverified in protocol.md and have never been run on hardware. The twin passes the package checks so the orchestration around a dissolution test can be rehearsed.
