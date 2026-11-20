<!-- generated from https://openmhp.com/cookbook by scripts/build_guide.py; edit the website, not this file -->

# Cookbook

Worked examples, one experiment per page, every step written out: what you type, what you say to the agent, what the agent does, and what you see. Each example runs on simulated instruments, so you can follow it exactly on your laptop with nothing plugged in, then swap in your real instrument at the end.

## Before any example

Do this once. It takes about two minutes.

### Install OpenMHP into your agent

```
npx -y openmhp-cli@latest setup
```

You will see it create `~/.openmhp`, install the runtime, copy the skills, and register the MCP server with Claude Code and Codex. For any other harness it prints a JSON snippet to paste into that harness's MCP settings.

### Add the two simulated instruments

```
npx -y openmhp-cli@latest demo
```

You will see `added thermocycler-01` and `added arm-01`. These behave like a real thermocycler and plate arm, sped up.

### Open your agent and check it sees the lab

> What instruments do I have?

The agent should answer with the two devices, their locations (bay 3) and what each can do. If it says the lab is empty, restart the agent so it reconnects to the MCP server.

## Examples

[**1. Run a PCR with a plate transfer**Two instruments, one sentence. Shows plan mode and a confirmation step.](https://openmhp.com/cookbook/pcr-with-plate-transfer) [**2. Monitor an instrument overnight**A background run, alerts, and reading the results the next morning.](https://openmhp.com/cookbook/overnight-monitoring) [**3. Calibrate with a setpoint sweep**Step a setting through values and get a table and a CSV.](https://openmhp.com/cookbook/calibration-sweep) [**4. Reflux on a stirrer hotplate**Add an instrument from the registry, read its safety card, run a timed hold.](https://openmhp.com/cookbook/reflux-on-a-hotplate) [**5. Any SCPI or Modbus instrument, no code**Write a package from the manual in a few lines of YAML, rehearse on its twin, read its rubric score.](https://openmhp.com/cookbook/any-scpi-or-modbus-instrument)

New examples are added regularly. Want one for your workflow? [Open an issue](https://github.com/kushalsinha/openmhp/issues) with the instruments and the procedure.


## Any SCPI or Modbus instrument, no code

A source meter on the bench speaks SCPI over USB; a stability chamber in the corner speaks Modbus over Ethernet. Neither has a community package. This example writes the package for each from its manual in a few lines of `descriptor.yaml`, with no driver code, and ends with the rubric score that says what is still missing.

**You need:** the setup from the [cookbook front page](https://openmhp.com/cookbook), `pip install pyvisa pyvisa-py` for the SCPI instrument and `pip install pymodbus` for the Modbus one, and the instrument's command reference (every vendor publishes one). About twenty minutes per instrument.

### Name the instrument and the route

> Onboard the Keithley 2400 on the bench. It is on USB.

The agent runs the onboarding interview and, hearing "SCPI", picks the declarative route: `driver.py` is one line, `from openmhp.drivers.scpi_visa import ScpiVisaDriver as Device`, and everything else goes in `descriptor.yaml`. For a Modbus device the line is `from openmhp.drivers.modbus import ModbusDriver as Device`. Nothing in the package is executable beyond that import.

### Write the command map from the manual

Each signal is a query, each setting a command with `{value}`, each action a list of commands, and the e-stop a list that removes energy. The agent copies the strings from the manual's command table:

```
signals:
  - {name: voltage, type: number, unit: V, notes: measured at the terminals}
  - {name: current, type: number, unit: A}
  - {name: output_on, type: boolean}
  - {name: state, type: string, source: runtime}
  - {name: busy,  type: boolean, source: runtime}
  - {name: calibration_status,   type: string, source: record}
  - {name: qualification_status, type: string, source: record}
  - {name: usage_count, type: integer, source: record, notes: sweeps run from here}
settings:
  - {name: voltage_setpoint, type: number, unit: V, limits: {min: -20, max: 20}, resolution: 0.001, approval: auto}
  - {name: compliance_current, type: number, unit: A, limits: {min: 0, max: 0.1}, approval: auto}
  - {name: output_on, type: boolean, approval: auto, notes: a person confirms the wiring before the first enable}
actions:
  - {name: reset, duration: short, approval: auto}
safety: {estop: true, watchdog_s: 20, notes: estop turns the output off and aborts any sweep}
scpi:
  resource: "USB0::0x05E6::0x2400::1234567::INSTR"     # config.json overrides this
  idn_match: KEITHLEY
  read:    {voltage: "MEAS:VOLT?", current: "MEAS:CURR?", output_on: "OUTP?"}
  write:   {voltage_setpoint: "SOUR:VOLT {value}", compliance_current: "SENS:CURR:PROT {value}", output_on: "OUTP {value}"}
  actions: {reset: ["*RST", "*CLS"]}
  estop:   ["OUTP OFF", "ABOR"]
```

The Modbus version names registers instead of commands: `{reg: 100, kind: input, type: int16, scale: 0.1}` for a temperature, `{reg: 20, kind: coil, value: 0}` in `estop` to drop the run relay. The limits are the lab's, not the instrument's: the agent asks what the cell can take and writes that.

### Let the base answer what the instrument cannot

The signals with `source: runtime` and `source: record` have no command. The base answers them: `state` and `busy` from its own state machine, and the self-state ones from the dates a person entered at setup (`mhp node setup --all` asks for the last and next calibration and whether the instrument is qualified). An agent now asks every instrument the same question, *is it calibrated*, and gets the same shape of answer.

### Write the twin and rehearse

A twin for a declarative driver is a fake port: an object with `write()` and `readline()` that answers the same strings. Twenty lines for most instruments. With it, `mhp lab add <folder> --sim` lets you drive the whole package with nothing plugged in, and `sim/fault` drives it into failure on purpose so you see what the agent does when a read hangs.

### Check the gate and the score

```
mhp validate  supported-devices/keithley-smu
mhp inclusion supported-devices/keithley-smu
mhp rubric    supported-devices/keithley-smu
```

The validator names anything untyped, unbounded, undefaulted or missing a unit. The inclusion gate loads the twin and tries to talk its way past every limit. The rubric prints a line per device-level procurement criterion with its evidence, so "why is this one 19 of 21" has an answer: *C19 N/A, no automated load; C20 N/A, nothing meets a robot*. Then put the instrument on the bench PC:

```
mhp node add keithley-smu --from ./supported-devices/keithley-smu
```

It asks one question, which VISA resource (listed, not typed), proves the answer with `*IDN?`, and serves.

What you did not write: any Python beyond one import, any retry logic, any limit check, any state machine, any e-stop plumbing. What you did write: the truth about the instrument, in a file a colleague can read and a reviewer can diff.


## Calibrate with a setpoint sweep

Step a setting through a list of values, let each settle, measure a signal several times, and get a table and a CSV. The same steps calibrate a laser's power against drive current, a stage's position against its command, or an oven's real temperature against its setpoint.

**You need:** the setup from the [cookbook front page](https://openmhp.com/cookbook). We sweep the simulated thermocycler's setpoint and measure its block temperature. About five minutes.

### Ask for the sweep

> Sweep the thermocycler from 30 to 60 degrees in steps of 10. Let each point settle for 5 seconds, take 3 readings at each, and give me the table.

### The agent shows the plan

It finds the `setpoint-sweep` recipe and rehearses it:

```
Plan for setpoint-sweep (values=[30,40,50,60], settle_s=5, samples=3, restore=22)
 1  thermocycler-01  set target_temperature = 30   ok
 2  thermocycler-01  read block_temperature (×3)
 3  thermocycler-01  set target_temperature = 40   ok
 ...
 9  thermocycler-01  set target_temperature = 22   ok   (restore)
Verdict: ok; no human confirmation needed. Run it?
```

Try asking for a top value of 120. The plan stops at that step with *REFUSED: target_temperature=120 above max 105*. The limit is in the instrument's package; the agent cannot change it.

### Say go and wait

> Go ahead.

Four points at five seconds each: about half a minute on the simulator.

### Read the table

```
setpoint  measured  sd
      30     30.00  0.00
      40     40.00  0.00
      50     50.00  0.00
      60     60.00  0.00
```

The simulator is exact; a real instrument's measured column is where the calibration lives. The agent also tells you the block is back at 22 °C.

### Use the CSV

> Fit a straight line to the sweep and tell me the offset and slope.

The agent reads `sweep.csv` from the run folder and does the arithmetic. The file stays at `~/.openmhp/runs/<run-id>/sweep.csv`.

## Doing it on a real instrument

1. Name the device, the setting and the signal: *"sweep the laser driver's current from 100 to 500 mA in steps of 50 and measure the power meter"*. The measured signal can come from a different device than the one being stepped.

2. Give a realistic settle time. Long sweeps run in the background; ask for the table when they are done.

3. For two-dimensional sweeps, copy the recipe into `~/.openmhp/recipes/` and add a second loop.


## Monitor an instrument overnight

Log a reading every few seconds for a set time, raise an alert if it leaves a band, and read the results back the next morning. The agent starts the run and leaves; the run carries on by itself.

**You need:** the setup from the [cookbook front page](https://openmhp.com/cookbook). We use the simulated thermocycler's block temperature as the thing to watch, with a two-minute "night" so you can see the whole cycle. About five minutes.

### Give the thermocycler something to hold

> Set the thermocycler block to 37 degrees.

The agent calls `mhp_write` for `target_temperature` = 37. Ask *"what is the block temperature?"* and it reads it back: 37.0.

### Start the watch

> Watch the thermocycler block temperature every 5 seconds for 2 minutes and alert me if it leaves 36.5 to 37.5. Run it in the background.

The agent finds the `periodic-readings` recipe and starts it with `background=true`:

```
mhp_run recipe="periodic-readings" background=true
        params={"device": "thermocycler-01", "signals": ["block_temperature"],
                "every_s": 5, "hours": 0.033, "alert": {"block_temperature": [36.5, 37.5]}}
```

It replies with the run id, for example `20260910-1402-a1b2`, and says it is running in the background. Nothing else happens in the chat while it runs.

### Cause an alert

About a minute in, change the setpoint so the watch has something to catch:

> Set the block to 40 degrees.

The block ramps to 40 within a few seconds. The running watch sees it leave the band.

### Ask what happened

After two minutes:

> What happened with the watch?

The agent calls `mhp_data op="runs"`, sees the run is done, and reads its output:

```
ALERT t=65s block_temperature=40.0 outside 36.5..37.5
ALERT t=70s block_temperature=40.0 outside 36.5..37.5
...
24 rows in readings.csv; 11 alert(s)
```

It summarises: *"The block left the band at 65 seconds when it rose to 40 °C and stayed there until the end. 24 readings are in readings.csv."*

### Look at the data

> Show me the readings.

The agent reads `readings.csv` from the run folder with `mhp_data op="read"`:

```
t_s,block_temperature
0.0,37.0
5.0,37.0
...
65.0,40.0
```

The file is also on disk at `~/.openmhp/runs/<run-id>/readings.csv` if you want to open it yourself.

### Check the log

> What has happened in the lab today?

The agent reads the run log (`mhp_lab op="events"`): the two setpoint writes, the run start and finish, and any refusals. If your harness accepts MCP logging messages, the finish and the alerts arrived as they happened.

## Doing it on a real instrument

1. Any device with readable signals works: an incubator via PyLabRobot or OPC UA, a chamber behind a PLC, a serial thermometer on a freezer.

2. Say the real numbers: *"every minute for 12 hours, temperature 36.5 to 37.5 and CO₂ 4.8 to 5.2"*.

3. Runs are not limited in length. The CSV is written after every reading, so nothing is lost if the laptop sleeps late in the run.


## Run a PCR with a plate transfer

A plate arm moves a 96-well plate onto a thermocycler, the thermocycler runs a cycling program and holds at 4 °C, and the arm puts the plate back. You say one sentence. Every step below is what actually happens, in order.

**You need:** the setup from the [cookbook front page](https://openmhp.com/cookbook) (install plus the two simulated instruments). About ten minutes.

### Ask for the experiment

In your agent, type:

> Run a 3-cycle PCR at 95/58/72 on the plate in deck slot A1, hold it at 4 °C afterwards, and put the plate back in A2.

Three cycles keeps the simulated run short. On a real instrument you would say 30.

### The agent looks for a recipe

Behind the scenes it calls `mhp_lab op="recipes"` with your sentence and gets back `pcr-with-plate-transfer`, which needs a robot arm and a thermocycler. You may see it say something like *"There is a tested recipe for this. I'll use it."*

### The agent finds the instruments and reads their notes

It calls `mhp_find` for an idle thermocycler and an idle arm, then `mhp_describe` on each. The thermocycler's notes say the lid must be closed and the lid heater should be on before loading. The arm's notes say to use 30% speed near open plates. The agent will follow both without being told.

### The agent rehearses and shows you the plan

It runs the recipe in plan mode. Nothing moves. You see a plan like this:

```
Plan for pcr-with-plate-transfer (cycles=3, plate_slot=deck_A1, return_slot=deck_A2)
 1  arm-01           set speed = 30                          ok
 2  arm-01           read homed → false
 3  arm-01           home                                    ok
 4  thermocycler-01  read lid_closed → true
 5  arm-01           pick_plate from deck_A1                 ok
 6  arm-01           place_plate at thermocycler             ok
 7  thermocycler-01  set lid_heater = true                   ok
 8  thermocycler-01  run_protocol (3 steps × 3 cycles)       ok   long-running
 9  thermocycler-01  set target_temperature = 4              ok
10  arm-01           pick_plate from thermocycler            ok
11  arm-01           place_plate at deck_A2                  ok
Verdict: ok; no human confirmation needed. Shall I run it?
```

Every step passed the instrument's safety checks. If you had asked for a 110 °C step, step 8 would show *REFUSED: step temp 110 outside block limits* and the agent would stop here and ask you what to do.

### Say go

> Yes, run it.

The agent runs the same recipe for real. With three cycles on the simulator this takes about ten seconds. On a real thermocycler with 30 cycles it would start the run in the background and tell you the run id.

### Read the result

The agent reports what the instruments actually did, from the recipe's output:

```
pcr done on thermocycler-01: {'cycles_completed': 3, 'final_block_temperature': 72}; plate at deck_A2; block 4.0 C
```

Notice it reports the block temperature it read (4.0 °C), not the one it set. Ask *"where is the plate now?"* and it reads the arm's `holding_plate` and position to answer.

### Try a step that needs a human

> Now open the thermocycler lid.

The thermocycler's owner marked `open_lid` as "a person must confirm", because the lid may be hot. In Claude Code you get a confirmation prompt from the server itself; in a harness without that feature, the agent asks you in the chat and only proceeds after you say yes. Either way the answer is written to the run log.

### See the record

> Show me what happened in that run.

The agent reads the run log and the run's output file (`mhp_data`) and lists every write, action and reading with timestamps. This is the record you would paste into a notebook.

## Doing it on real instruments

1. Onboard your thermocycler (say *"onboard my thermocycler"*; serial or hand-operated needs no code) or add a community package. Keep the action name `run_protocol` with `steps` and `cycles`, and the recipe works unchanged.

2. Add your plate mover the same way. If you do not have one, onboard a "manual" arm: the agent will ask the operator to move the plate at steps 5, 6, 10 and 11 and wait.

3. Use *"30 cycles"* and let the agent run it in the background. Ask for the result when it is done, or ask it to notify you.

## The recipe file

You do not need to read it, but it is `openmhp/recipes/pcr_with_plate_transfer.py` in the repository. The parameters the agent fills from your sentence:

```
PARAMS = {"arm": None, "thermocycler": None,        # None = pick an idle one by search
          "plate_slot": "deck_A1", "return_slot": "deck_A2",
          "steps": [{"temp": 95, "hold_s": 30}, {"temp": 58, "hold_s": 30}, {"temp": 72, "hold_s": 45}],
          "cycles": 30, "hold_c": 4}
```


## Reflux on a stirrer hotplate

Add a hotplate from the community registry, read its safety card, then bring a flask to 80 °C, hold for a while, and cool down. This example shows how an instrument gets into the lab and how limits protect you, using the IKA C-MAG HS 7 package's simulated twin.

**You need:** the setup from the [cookbook front page](https://openmhp.com/cookbook), and `git` on your machine (the registry pulls packages from GitHub). About ten minutes.

### Ask whether a package exists

> Is there a package for the IKA C-MAG hotplate?

The agent calls `mhp_lab op="registry"` and finds `ika-c-mag-hs7`: a serial driver using IKA's command set, with a simulated twin.

### Add the simulated twin

> Add its simulated twin so I can try it.

The agent calls `mhp_lab op="add" target="github:kushalsinha/openmhp/packages/ika-c-mag-hs7" sim=true`. It clones the package and registers it as `ika-c-mag-hs7-01-sim`. Ask *"what instruments do I have?"* and the hotplate is now in the list, tagged simulated.

For a real instrument the agent also asks where it stands, because a shared package cannot know, and records it with `mhp_lab op="location" id="ika-c-mag-hs7-01" location="fume hood 2"`. That is what *"find me an idle hotplate in hood 2"* searches on later. A simulated twin stands nowhere and is labelled `simulated`.

### Read the safety card

> Is it safe to let you use the hotplate?

The agent calls `mhp_lab op="safety_card"` and reads it to you:

```
SAFETY CARD: ika-c-mag-hs7-01 (IKA C-MAG HS 7)

Limits the driver enforces (values are also type-checked):
  - target_temperature: 20 to 300 degC  (the instrument allows 500; this package caps at 300 for glassware)
  - stir_rpm: 0 to 1500 rpm
Actions and their gates:
  - start_heating, stop_heating, start_stirring, stop_stirring: no gate
  - shutdown: a person must confirm each time
Emergency stop: declared (sends STOP_1 and STOP_4, heater and stirrer off); not exercised by this card
Watchdog: 30 s while a client holds a lease; not exercised by this card
Probes (dry runs; nothing was actuated):
  - write target_temperature above-max: refused as expected: 301 above max 300
  - write target_temperature wrong-type: refused as expected: expected number, got str
  - write stir_rpm above-max: refused as expected: 1501 above max 1500
  - invoke shutdown: passes the gates once a person confirms

RESULT: no configuration errors found. Setting probes refused as expected: 6 of 6.
Not checked: emergency-stop behaviour, watchdog expiry, physical behaviour.
The owner must review this card; it is not a safety certification.
```

### Ask for the reflux

> Reflux the flask on the hotplate at 80 degrees for 2 minutes, stirring at 400 rpm, then cool it to room temperature.

Two minutes stands in for an hour so you can watch the whole thing.

### The agent shows the plan

It reads the hotplate's operating procedure (stir first, then heat), picks the `timed-hold` recipe for the hold, and rehearses:

```
Plan
 1  ika-c-mag-hs7-01-sim  set stir_rpm = 400           ok
 2  ika-c-mag-hs7-01-sim  start_stirring               ok
 3  ika-c-mag-hs7-01-sim  set target_temperature = 80  ok
 4  ika-c-mag-hs7-01-sim  start_heating                ok
 5  ika-c-mag-hs7-01-sim  read plate_temperature until within 0.5 of 80
 6  hold 2 min, logging plate_temperature every 10 s
 7  ika-c-mag-hs7-01-sim  set target_temperature = 22  ok
 8  ika-c-mag-hs7-01-sim  stop_heating                 ok
 9  ika-c-mag-hs7-01-sim  stop_stirring                ok
Verdict: ok; no human confirmation needed. Run it?
```

### Say go

> Yes.

The simulated plate warms at a few degrees a second, holds, and cools. The agent reports:

```
held 80 for 2 min; readings in readings.csv; now 22.4
```

### See a refusal

> Set the hotplate to 350 degrees.

The agent tries `mhp_write` and the driver refuses: *target_temperature=350 above max 300*. The agent tells you the limit and does not try another way. The refusal is in the run log.

### Try the confirmation gate

> Shut the hotplate down.

`shutdown` needs a person's yes because the plate stays hot. You get the confirmation prompt; say yes and it runs.

## Doing it on the real hotplate

1. Add the package without `sim`: *"add the IKA package"*. The agent asks which USB port it is on (`/dev/ttyUSB0`, `/dev/tty.usbserial-…` or `COM3`) and where it sits, and fills those in.

2. A different hotplate with no package: say *"onboard my hotplate"*. If it has a USB cable and a command table in the manual, the interview produces a serial driver; if not, a hand-operated one, where the agent tells the operator what to set and records what they read.

3. Use real times: *"hold for an hour"*. The run goes to the background and you ask for the result later.
