# Biobrain OPC UA: what this package reads, writes and calls

Sources read:

- Sartorius, "Product Datasheet Biobrain: Integrating Biobrain-Powered Products Into Higher Level
  Systems" (biobrain-integration-datasheet-en-b). Server structure: process-data layer (control
  modules with process values, setpoints and alarm ranges), alarm events, audit trail, phase-level
  integration (start, hold, pause, suspend, stop, abort; writable phase parameters) and recipe-level
  integration (start/stop recipes, batch reports); OPC UA HDA.
- Sartorius application note "Connecting Biobrain Supervise to Biostat STR Generation 3 via OPC
  Unified Architecture (UA)", August 2023: endpoint `<ip>:4840`, Sign and Encrypt, Basic256Sha256,
  username authentication with a device user holding the Remote operation permission, self-signed
  certificates trusted on both sides.
- Sartorius Biostat B-DCU operating manual (DCU 4): controller names TEMP, JTEMP, STIRR, pH, pO2 (DO),
  FOAM, LEVEL, SUBS (feed), ACID, BASE, GLUCO, VWEIGH/BALANCE; each with Setpoint, Out, Mode, Alarm,
  Param; modes Off, Auto, Manual.
- Sartorius "OPC UA SimApi User Guide" (doc 00135, 2024-12): on the MFCS / Biobrain Supervise server
  the convention is `/Unit/<UnitName>/Variables/<Variable>.Value`.

The node list itself is in the per-product "OPC UA interface report" and "OPC UA integration
manual" Sartorius supplies to customers, which were not available. Every id below is therefore a
placeholder built from the DCU controller names, and the whole map is **unverified** until the site's
report replaces it in config.json.

| config key | role | placeholder id | access | unverified |
|---|---|---|---|---|
| temperature | TEMP process value, Cel | ns=2;s=Unit1.TEMP.PV | read | yes |
| temperature_setpoint / temperature_mode | TEMP setpoint and mode (0 Off, 1 Auto) | ns=2;s=Unit1.TEMP.SP / .Mode | write | yes (mode coding too) |
| ph, ph_setpoint, ph_mode | pH loop | ns=2;s=Unit1.PH.* | read/write | yes |
| do, do_setpoint, do_mode | pO2 loop, % air saturation | ns=2;s=Unit1.DO.* | read/write | yes |
| agitation, agitation_setpoint, agitation_mode | STIRR loop, rpm | ns=2;s=Unit1.STIRR.* | read/write | yes |
| gas_flow, gas_flow_setpoint, gas_flow_mode | total gas flow, L/min | ns=2;s=Unit1.GASFL.* | read/write | yes |
| weight | balance / VWEIGH, kg | ns=2;s=Unit1.BALANCE.PV | read | yes |
| foam_alarm | FOAM alarm flag | ns=2;s=Unit1.FOAM.Alarm | read | yes |
| feed_rate_setpoint, feed_mode | SUBS feed pump setpoint (mL/h) and mode | ns=2;s=Unit1.SUBS.* | write | yes |
| acid_mode, base_mode | ACID / BASE pump modes (e-stop sets Off) | ns=2;s=Unit1.ACID.Mode, .BASE.Mode | write | yes |
| phase | current recipe phase name | ns=2;s=Unit1.Recipe.Phase | read | yes |
| recipe_object, recipe_start, recipe_stop | recipe-level integration object and its start/stop methods (start takes the recipe name) | ns=2;s=Unit1.Recipe, .Start, .Stop | call | yes (argument list too) |

Behaviour assumed from the documents: writing a setpoint then setting the loop mode to Auto makes
the DCU act on it; a recipe's phase node reads a phase name while it runs and a terminal word
(Complete/Stopped) after. The driver treats `Complete`, `Completed`, `Idle`, `Stopped` and an empty
string as "no recipe running".
