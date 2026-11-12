# MultiPyVu calls used (Quantum Design MultiVu socket server)

Sources: Quantum Design, "MultiPyVu" project description on PyPI (https://pypi.org/project/MultiPyVu/,
version 3.8.1, MIT licence; the project page is the reference the vendor points to) and Quantum Design
application note 1070-220 Rev. A1 (11/2023), "MultiPyVu: Controlling QD Cryostats Using Python"
(platforms PPMS, DynaCool, VersaLab, MPMS-3, OptiCool; server and client may run on the same PC or the
client on a remote PC). The server runs beside MultiVu on its PC (pywin32); the client runs on Windows,
macOS or Linux. Default port 27183; one client at a time; a client object connects once.

| Call | Meaning | Used by |
|---|---|---|
| `mpv.Client(host, port)`, `.open()`, `.close_client()` | connect to / leave the server (`with` form also exists) | connected, close |
| `get_temperature()` -> `(temperature, status)` | system temperature in K and MultiVu's status word | temperature, temperature_status, ramp polling |
| `set_temperature(set_point, rate_K_per_min, client.temperature.approach_mode.<fast_settle|no_overshoot>)` | temperature setpoint, rate in K/min, approach | temperature_setpoint, set_temperature_and_wait |
| `get_temperature_setpoints()` -> `(temperature, rate, approach)` | what MultiVu is driving toward | temperature_setpoint_actual |
| `get_field()` -> `(field, status)` | field in Oe and MultiVu's magnet status word | field, field_status, ramp polling |
| `set_field(set_point, rate_oe_per_sec, client.field.approach_mode.<linear|no_overshoot|oscillate>[, client.field.driven_mode.<persistent|driven>])` | field setpoint, rate in Oe/s, approach; driven mode is PPMS-only and raises elsewhere; no_overshoot is not on VersaLab | field_setpoint, set_field_and_wait, discharge_magnet |
| `get_field_setpoints()` -> `(field, rate, approach, driven)` | what MultiVu is driving toward | field_setpoint_actual |
| `get_chamber()` -> status string | chamber status word | chamber_state |
| `set_chamber(client.chamber.mode.<seal|purge_seal|vent_seal|pump_continuous|vent_continuous|high_vacuum>)` | chamber command; not used on OptiCool | set_chamber |
| `wait_for(delay_sec, timeout_sec, bitmask)`, `is_steady(bitmask)` | MultiPyVu's own wait on `client.temperature.waitfor | client.field.waitfor | client.chamber.waitfor` | not used: the driver polls the status words itself so a job can be cancelled between polls |

Units: K, K/min, Oe, Oe/s (10000 Oe = 1 T), seconds. Scaffolding: `mpv.Server(flags=['-s', '<PLATFORM>'])`
or `python -m MultiPyVu -s dynacool` mimics MultiVu without the instrument.

## Unverified

- The status strings. The project page documents that `get_temperature`, `get_field` and `get_chamber`
  return a status word but does not list them; the words this package names (`Stable`, `Tracking`,
  `Near`, `Chasing`, `Pot Operation`, `Standby`, `Diagnostic`, `Impedance Control Error`, `Failure`;
  `Stable Persistent`, `Warming Switch`, `Cooling Switch`, `Stable Driven`, `Iterating`, `Charging`,
  `Discharging`, `Current Error`, `Unknown`; `Sealed`, `Purged and Sealed`, `Vented and Sealed`,
  `Pumping Continuously`, `Venting Continuously`, `High Vacuum`, `Pumping`, `Flooding`) are MultiVu's
  display words as commonly seen and are compared case-insensitively. The driver treats `Stable`,
  `Stable Driven` and `Stable Persistent` as settled and the first word of a chamber status as its
  state; a different spelling makes a ramp job time out with `reached: false` rather than misreport.
- The temperature and field ranges (1.8-400 K, +/-90000 Oe) are placeholders for the base platforms;
  the lab sets its own.
- No abort or stop call is documented; `estop` is therefore false (see safety.notes).
- `get_sdo` / `set_sdo` and the rotator and resistivity calls exist in MultiPyVu but are not used.
