# Flow Commander over OPC UA: the node keys this package uses

## What is public

- Vapourtec R-Series brochure (vapourtec.com, "Vapourtec-R-Series-brochure.pdf", 2024), Connectivity:
  "The R-Series software includes an optional OPC UA server simplifying connectivity to other laboratory
  instruments. Python script examples are included, enabling integration into AI platforms." No node
  names, namespace, endpoint or port are published; no document titled "Flow Commander Open API" was found.
- cambridge-cares/TheWorldAvatar `Agents/VapourtecAgent` (MIT): a second, .NET route through
  `FCRemote.dll` / `FCRemoteCSV.dll` (supplied by Vapourtec, not in the repository) with
  `FlowCommander.Connect(ip)`, `Disconnect`, `ClearReactions`, `CSVParser.AddReactions(csv, fc)`, `Run`,
  `GetState` (0 Idle, 1 Initialising, 2 RunningReaction, 3 CleaningReaction, 4 FinalCleaning) and a
  commented-out `LoadExperiment(fc, "...fcexp")`. No stop or abort call is used there.
- automatedchemistry/flowchem (MIT) drives the R2 and R4 directly over serial (19200 8N1, CR LF) with
  command strings in an NDA-only package; the public code shows only the command families
  (SET_FLOWRATE, SET_TEMPERATURE, GET_STATUS, POWER_ON/OFF, KEY_PRESS for valves) and the R2 status
  reply layout (run state, pump speeds, airlocks, pressure limit, LEDs, four channel temperatures; run
  states 0 Off, 1 Running, 2 System overpressure, up to 7 Pump B pressure loss). richardingham/octopus
  (MIT) documents the same property model with the control file withheld at Vapourtec's request.

So the OPC UA route is the vendor-supported one, and its node ids are the lab's to bind.

## Node keys (config.json `nodes`)

| Key | Direction | Used for | Status |
|---|---|---|---|
| `object` | object node | parent for method calls | placeholder, unverified |
| `pump_a_flow`, `pump_b_flow` | read (number, mL/min) | pump flows | unverified |
| `pump_a_flow_setpoint`, `pump_b_flow_setpoint` | write (number, mL/min) | pump setpoints; 0 stops | unverified |
| `system_pressure` | read (number, bar) | pressure; `pressure_ok` interlock | unverified (the R2 itself reports mbar) |
| `system_state` | read (integer or string) | run state (0..4 mapped as the VapourtecAgent does) | unverified |
| `collection_valve` | read (boolean or string) | collect/waste | unverified |
| `collection_valve_set` | write (boolean) | true = collect | unverified |
| `bpr_pressure` | write (number, bar) | electronic BPR setpoint | unverified |
| `reactor_n_temperature` (n = 1..4) | read (number, degC) | channel temperature; null when unmapped | unverified |
| `reactor_n_setpoint` | write (number, degC) | channel setpoint | unverified |
| `reactor_n_enable` | write (boolean) | channel heater on/off; skipped when unmapped | unverified |
| `start(name)`, `stop()`, `prime(pump, volume_ml)` | method | experiment bracketing, stop, prime; skipped when unmapped | unverified |

Every id in `config.example.json` is a placeholder; none has been read from a real server.

## Instrument facts used (vendor pages)

- Pump modules (vapourtec.com, "R-Series flow chemistry pump modules"): R2 and R2 Plus 0.05 to 10 mL/min,
  42 bar; R2 C 0.05 to 10, 42 bar; R2 S peristaltic 0.02 to 10, 10 bar; R2 HP 0.05 to 10, 200 bar;
  R2 HF 0.2 to 50, 42 bar.
- R4 (vapourtec.com, "R-Series reactor heater cooler"): -70 to 250 degC; channels 1 and 3 ambient to
  150, channels 2 and 4 ambient to 250; cooling module on channels 1, 3 and 4; ramp up to 80 degC/min.
  Reactor types: glass coil to 150, stainless/Hastelloy to 250, cooled coil -70 to ambient, UV-150
  -40 to 80.
- BPR range: not found (the eBPR page was unavailable); the 0 to 20 bar setting limit here is a placeholder.
- Hardware emergency stop: not described in any public document; the brochure says pumps "shutdown
  safely in the event of a leak or blockage".
