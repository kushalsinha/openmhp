# Setting up

Runs on any Linux, macOS or Windows machine with a serial port (or USB-serial adapter) to the Titrino.
`pip install openmhp pyserial`.

## Cable and port

- **870 KF Titrino plus** (and the other Titrino plus models): remote control needs Metrohm's
  **6.2148.030 RS-232/USB box** on the instrument's USB port; only its second port, **RS-232/2 (COM2)**,
  accepts remote commands (COM1 is for a balance). A null-modem cable from that port to the PC.
  In the instrument's system settings set the COM2 port to 19200 baud, 8 data bits, 1 stop bit, no parity,
  software handshake (the manual's recommendation); the box supports 1200 to 115200 (default 9600).
- **7xx Titrinos** (758 KFD, 784 KFP, 787 KF ...): the instrument's own RS-232 port (two per Titrino);
  settings under `Config.RSSet1` (baud 300 to 115200, default 9600; 8 data bits, 1 stop bit, no parity
  recommended; XON/XOFF handshake). The instrument is a DTE; apply changes with `$G` while inactive and wait
  2 s.

## Install

1. Copy `config.example.json` to `config.json`: `port`, `dialect` (`plus` or `classic`), `baud`, and the
   reagent's `titer_mg_ml` (the classic dialect's drift is reported as water equivalent with it).
2. `mhp serve pkg:<this folder> --http <port>` and read `connected`, `titrator_status`.

## Methods

The KF methods live in the Titrino (`$L(name)` on the plus, `UserMeth.Recall "name"` on the classic);
this package only names them. Keep one per sample type and store its name, sample size handling and
result unit as an OpenMHP method record (`methods/_shared/kf-std.yaml` is the pattern).

## First hardware test

1. Read `connected` and `titrator_status` (Cond while the cell conditions, Ready when the method is stopped);
   compare with the display.
2. Invoke `condition` and watch `cell_conditioned` go true as the drift settles.
3. Write `sample_mass_g` 0.5; on the classic dialect the display's sample size changes.
4. Invoke `determine` with the example method on a water standard (for example 1 mg/g); inject when the
   status reads Busy; compare the result with the display and the printout.
5. Invoke `determine` again and call `safety/estop` during the titration: the display shows the manual
   stop (E26 on a classic Titrino) and the job ends cancelled.

## Status

twin tested. Written from the Metrohm manuals named in `references/rs232.md`; the plus dialect's `$D` reply
layout and several classic reply formats are unverified; not yet run on hardware.
