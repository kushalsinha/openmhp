# MHP descriptor field reference

Served by `device/describe`. Authored in YAML or JSON. Every object may carry `notes`.

| Field | Rule |
|---|---|
| `device.id` | unique in the lab; lowercase, hyphenated, e.g. `thermocycler-01` |
| `device.class` | open vocabulary: thermocycler, liquid_handler, robot_arm, microscope, plate_reader, centrifuge, incubator, hotplate, balance, pump, valve, spectrometer, laser, stage, cnc, 3d_printer, oven, power_supply, camera, generic |
| `device.location`, `device.tags` | SHOULD be set; the directory filters on them |
| `device.notes` | first sentence appears on the directory card |
| `physical` | free-form: `mass_kg`, `footprint_mm`, `payload_kg`, `reach_mm`, `power_w`, plus `notes` |
| `signals[]` | `name`, `type` (number, integer, boolean, string, object, array), `unit`, `notes` |
| `settings[]` | as signals plus `limits` (`{min,max}` or `{enum:[...]}`), `approval`, `interlocks` |
| `actions[]` | `name`, `duration` (short, long), `approval`, `interlocks`, `params` (name → description), `limits` (param → [min,max]), `examples` (list of param objects), `concurrent` |
| `approval` | `auto` (agent may act), `confirm` (needs `approved: true` after a human said yes), `forbid` (never agent-operated; still listed so the agent knows why) |
| `interlocks` | names of boolean signals that must read true at call time |
| `safety` | `estop` (bool), `interlocks` (all interlock signals), `watchdog_s`, `notes` |
| other top-level keys | allowed and preserved, e.g. `locations` for a robot arm |

Gate order enforced by every driver on write/invoke: state → approval → interlocks → limits → lease → busy.

Detail tiers returned by `device/describe {detail}`: `card` (~40 tokens), `summary` (~200), `full`;
`select: {actions: [...]}` returns full specs of named items only.
