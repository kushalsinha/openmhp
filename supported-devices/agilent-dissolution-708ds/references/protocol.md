# Agilent 708-DS serial link: what is known, and the placeholders this template uses

Sources read: Agilent Community thread "708-DS RS232 Command List?" (community.agilent.com, dissolution forum; Agilent staff reply: no command list for third parties); "708-DS Dissolution Apparatus Operator's Manual", Agilent part 70-9058 Rev H (February 2020): instrument settings, Comm ID, remote control, connections; "850-DS Dissolution Sampling Station Operator's Manual", 70-9074 Rev D (March 2018): apparatus control cable and the diagnostic screen that drives a 708-DS; "Agilent Dissolution Tester Driver User's Manual" (UV-Vis ChemStation, 2011-2012): connection, `/log` switch and an example communication log; "VK 7000/7010 Operator's Manual", 70-9003 Rev J (2006) and "VK 7025 Operator's Manual", 70-9033 Rev G (2006): RS-232 settings and the statement that menu items can be queried and changed over the port; "VK 750D Heater/Circulator Operator's Manual", 70-9005 Rev H (November 2010), page "RS232 Command Set": the documented command table of the sibling circulator, which shows the frame grammar of the family. No open-source driver, no GitHub project, no open-source connector, no patent with the command set was found.

## Link (verified from the documents)

| Item | Value |
|---|---|
| Port | 25-pin D-sub "RS232" on the rear of the 708-DS drive head (also VK 7000/7025); RJ-11 "RS232 in/out" for daisy-chaining |
| Cable | DB9 (PC) to DB25 (tester): Agilent 5075-0552 or 5075-0252; 850-DS to apparatus 5075-0042 |
| Baud | 9600 (required whenever Agilent/VanKel dissolution units talk to each other; the 708-DS has no baud setting). Data bits, parity, stop bits: not documented (8N1 assumed, unverified) |
| Addressing | two-digit Comm ID 01 to 99, default 01, set on the 708-DS (Instrument Settings 1); host software addresses `COMx:nn`; accessories have fixed IDs (sampler pump 76, filter changer 75) |
| Remote mode | the 708-DS shows a flashing "Remote Control", hides Run/Stop and locks the touchscreen while a host controls it |
| Functions the host software exercises | set spindle speed, set bath temperature, run/stop spindles, drive head up/down, manifold (probe) up/down, DDM single position / all, read bath temperature (set and actual), read vessel temperatures (probes lowered, about 40 s per read), firmware and serial number |

## Frames captured in Agilent's own driver log (real, meaning inferred)

| Host sends | Reply | Inferred meaning |
|---|---|---|
| `0152930000` | `5293DLO0710C000` (OCR of a screenshot; digits uncertain) | identity / firmware query, sent first on connect |
| `0154310000` | `54310000` | a status or configuration read; reply echoes the 8 characters after the address |
| `0185100002` | `85100002` | a write with data 0002, sent just before the driver asked for the "probe down" state |

Inferred frame grammar (medium confidence): 10 ASCII characters = 2-digit Comm ID + 4-digit code + 4-digit data; the reply is the frame without the address, with data filled in, or a longer string for text replies. In the documented VK 750D circulator set the first code digit is 2 for read and 3 for write, e.g. `0122200000` reads the actual temperature and answers `01222ftttt` (f = unit flag, tttt = ttt.t), `01320ftttt` sets the setpoint, `0125000000` reads status. The 708-DS log shows code groups 52xx, 54xx and 85xx, so its map is different and **not known**. Whether frames carry a CR terminator is not documented.

## The placeholder frames in this package (ALL UNVERIFIED)

The code field uses letters so that a real 708-DS, whose codes are digits, rejects every one of them.

| Capability | Placeholder frame | Twin reply | To be replaced by |
|---|---|---|---|
| identity | `0152930000` | `5293DLO0710C000` | (real frame; meaning inferred) |
| bath_temperature | `01RBAT0000` | `01RBAT0370` (37.0) | the bath actual-temperature read |
| vessel_temperature_1 | `01RVT10000` | `01RVT10368` | the vessel probe read (probes lowered) |
| paddle_speed | `01RRPM0000` | `01RRPM0050` | the spindle speed read |
| run_state | `01RRUN0000` | `01RRUN0001` | the run/stop state read |
| time_remaining | `01RTIM0000` | `01RTIM0045` | the timer read |
| heater_on | `01RHTR0000` | `01RHTR0001` | the heater state read |
| temperature_setpoint | `01WBAT{value}` | echo | the setpoint write (ttt.t as four digits) |
| paddle_speed_setpoint | `01WRPM{value}` | echo | the speed write |
| run_time | `01WTIM{value}` | echo | the duration write |
| start_run / stop_run | `01WRUN0001` / `01WRUN0000` | echo | run / stop (and head lower / raise if separate) |
| drop_samples | `01WDDM0000` | echo | DDM fire-all |
| estop | `01WRUN0000`, `01WHTR0000` | echo | the real stop frames |

## Methods

A 708-DS run is a method (medium, volume, temperature, speed, dosing and sampling times per product). The package declares no `methods: true` action and ships no `methods/` folder because the run action cannot be validated against the instrument until the frames are real; add them (SPEC 4.5) when it can.
