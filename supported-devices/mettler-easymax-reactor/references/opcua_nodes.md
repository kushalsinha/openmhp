# iControl over OPC UA: the node keys this package uses

## Why node ids are configuration

Mettler Toledo documents no item or node list for iControl's OPC interface. The iControl datasheet
(mt.com, "iControl" DS, 2019) and the product pages do not mention OPC at all; the OPC capability is sold
as an option. What is public:

- Mettler's **iC OPC UA Server** add-on (for iC IR, iC FBRM and the iC family) exposes nodes of the form
  `ns=2;s=Local.iCIR.ConnectionStatus`, `ns=2;s=Local.iCIR.Probe1.Methods.Start Experiment`,
  `...Probe1.Methods.Stop`, default endpoint `opc.tcp://localhost:62552/iCOpcUaServer` (seen in the
  open-source flowchem driver for iC IR, github.com/automatedchemistry/flowchem,
  `src/flowchem/devices/mettlertoledo/icir.py`, MIT). Those are iC IR nodes, not iControl's.
- The only public code that reads **iControl** over OPC UA is PyPete/Helix
  (`Helix.Orchestration.Devices/Drivers/EasyMax.cs`): it browses `ns=2;s=Local.iControl`, reads
  `ns=2;Local.iControl.ConnectionStatus`, `...{Experiment}.ExperimentName`, `...{Experiment}.DocumentName`
  and `...{Experiment}.Trends` (a list of name/value/unit trends). It reads only; no write node or method
  for setpoints appears anywhere public.
- The Acceleration Consortium's process-chemistry cell (github.com/AccelerationConsortium/sdl2-gibbie-server)
  reaches an EasyMax through a Windows service that "serves OPC UA on loopback" and reads per-zone Tr/Tj,
  stir rates and "Stirrer and Thermostat State nodes"; the node names are not published.

So this package names what it needs and lets the lab bind each name to a node after browsing the server.

## Node keys (config.json `nodes`)

| Key | Direction | Used for | Status |
|---|---|---|---|
| `connection_status` | read (boolean) | `connected` | `Local.iControl.ConnectionStatus` seen in Helix; id form unverified |
| `object` | object node | parent for method calls | placeholder `ns=2;s=Local.iControl`, unverified |
| `tr`, `tj` | read (number) | reactor and jacket temperature | trend names unverified (Helix reads them from the Trends list) |
| `stirrer_rpm` | read (number) | stirrer speed | unverified |
| `stirrer_running` | read (boolean) | `stirrer_running` interlock; null falls back to `stirrer_rpm > 0` | unverified |
| `dosing_total_ml`, `ph` | read (number) | optional signals; null when unmapped | unverified |
| `phase` | read (string) | experiment phase; unmapped falls back to idle/running from this package | unverified |
| `tr_setpoint`, `tj_setpoint` | write (number) | setpoints | unverified: no public write node |
| `stirrer_setpoint` | write (number) | stirrer | unverified |
| `ramp_rate` | write (number, K/min) | ramp for the next setpoint | unverified |
| `thermostat_mode` | write (integer) | 0 idle, 1 Tr mode, 2 Tj mode (values are placeholders) | unverified |
| `start_experiment(name)`, `end_experiment()` | method | open/close an iControl experiment; skipped when unmapped | unverified |
| `dose(volume_ml, rate_ml_min)`, `stop_dosing()` | method | the dosing unit; `dose` fails with a plain reason when unmapped | unverified |
| `safe_state()` | method | called by e-stop after stirrer 0 and thermostat idle | unverified |

Every id in `config.example.json` is a placeholder in the Helix naming style; none has been read from a
real server.

## Instrument facts used (vendor documents)

- EasyMax 102/402 Advanced datasheet (DS 30248031D, 01/2021): Tj -40 to 180 degC (102 LT: -90 to 80),
  stirrer 50 to 1000 rpm; Operating Instructions 30092610D: Tr -40 to 180, Tj-Tr limited to 60 K in Tr
  mode, ramps as duration or rate in degC/min, user limits Tsafe, Tr max/min, Tj max/min, Rsafe (0 to
  1000 rpm), Rmax 500 rpm with glass or anchor stirrers; emergency programs E (resettable: cool to Tsafe,
  stirrer to Rsafe) and A (hardware faults). No physical emergency stop; connectors are RS232, USB, CAN,
  Ethernet.
- OptiMax 1001 Operating Instructions 51712001F and datasheet 51727012B: Tj/Tr -40 to 180 degC,
  stirrer 30 to 1200 rpm, a Safeguard button (emergency cooling to Tsafe; release and Reset to continue)
  and a safety relay output.
- Dosing: task sequences dose "with a DU SP-50" or "via an ECB", at once or by duration/rate; the SP-50's
  rate and volume ranges were not found, so the `dose` limits here (0.1 to 500 mL, 0.01 to 50 mL/min) are
  placeholders.

## Alternative routes, not implemented

iControl also has a TCP "remote experiment control" in some versions and the newer EasyMax touchscreen
firmware has Ethernet; no public document describes either protocol. The package should move to a
documented route if Mettler provides one.
