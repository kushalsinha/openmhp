# Files this package writes and reads (TEMPLATE)

## Sources

- Arbin's public pages: MITS Pro schedules are built in a schedule editor from steps with
  logic-based limits (arbin.com, "Schedule and state machine", "Sub-schedule / subroutine feature");
  a schedule file made in one MITS major version should not be used in another (Arbin FAQ). The
  *Arbin-002 MITS Pro 3.0 - BT2000 User Manual* table of contents names schedule files with the
  `.sdu` extension, a "Start Channel(s)" dialog for launching a test on selected channels, and
  results export through Data Pro / Excel. The MITS Pro console protocol and the SDK are under
  NDA and were not read; nothing here talks to them.
- Column names of MITS Pro CSV/Excel exports from a public battery-data-format guide and two
  open-source parsers (an R package and a Python package for cycler data): `Test_Time(s)`,
  `Cycle_Index`, `Step_Index`, `Current(A)`, `Voltage(V)`, `Charge_Capacity(Ah)`,
  `Discharge_Capacity(Ah)`, auxiliary channels as `Aux_Temperature_1(C)`; capacities are cumulative
  within a step; newer MITS Pro versions add a `SubSch_Step` column; the native `.res` file is a
  Microsoft Access database. A MathWorks example of the same export adds `Date_Time`, `Step_Time(s)`,
  `Charge_Energy(Wh)`, `Discharge_Energy(Wh)`, `dV/dt(V/s)` and `Internal_Resistance(Ohm)`.

## Request (written by this package): `request_dir/mhp_<job>.json`   (this package's own layout)

```json
{"token": "mhp_job_1a2b3c4d", "channel": "3", "test_name": "CC-2026-0007_mhp_job_1a2b3c4d",
 "barcode": "CC-2026-0007", "schedule": "Formation_C2_3cyc.sdu",
 "steps": [{"mode": "cc_charge", "current_a": 0.0225, "voltage_v": 4.2, "time_limit_s": 14400}, "..."],
 "cycles": 3, "export": "CC-2026-0007_mhp_job_1a2b3c4d.csv", "written": 1760000000.0}
```

`steps` and `cycles` are informative: the schedule file holds the real program and the person
starting the test checks they match. The request is deleted by whoever starts the test;
`queue_depth` counts those left; an e-stop deletes them. The package cannot write `.sdu` files.

## Results export (read by this package): `results_dir/*mhp_<job>*.csv` or `.txt`

Lines before the first one containing `Test_Time` are skipped. Columns matched by name
(**unverified** against the lab's MITS Pro version; the parser ignores extra columns):

```
Data_Point,Test_Time(s),Step_Time(s),Step_Index,Cycle_Index,Current(A),Voltage(V),Charge_Capacity(Ah),Discharge_Capacity(Ah)
1,10.0,10.0,1,1,0.0225,3.52,0.0000625,0
```

- `cycles_completed`: largest `Cycle_Index`.
- `last_capacity_ah`: largest `Discharge_Capacity(Ah)` among the rows of the last cycle (capacities
  are cumulative within a step, so that is the last discharge step's capacity); the largest
  `Charge_Capacity(Ah)` if no discharge was recorded; null if neither column exists.
- `final_voltage_v`, `test_time_s`: the last row's `Voltage(V)` and `Test_Time(s)`.
- Excel (.xlsx) exports are not read: export as CSV.

## Twin

The fake MITS Pro PC starts the test as soon as the request lands (`channel_state` reads `running`),
simulates a 45 mAh, 3.0-4.2 V coin cell with a 2 ohm internal resistance through the requested steps
and cycles at 10 s resolution, waits the protocol's length scaled by `OPENMHP_SIM_TIME_SCALE`, then
writes `<barcode>_mhp_<job>.csv` in the layout above and deletes the request.
