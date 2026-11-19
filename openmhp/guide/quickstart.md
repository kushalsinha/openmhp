<!-- generated from https://openmhp.com/quickstart by scripts/build_guide.py; edit the website, not this file -->

# Quickstart

Install OpenMHP into your agent, add two simulated instruments, and talk to them. No hardware needed. Then, when your lab is ready, set up the instrument PCs and the gateway step by step.

## Try it in five minutes

You need Python 3.10 or newer, and an agent such as Claude Code or Codex. Install one of two ways; both give the same result.

### With pip

1. Install the runtime and its Agent Skills:

```
pip install -U "openmhp[all]"
```

```
mhp skills install
```

2. Register the MCP server with your agent. For Claude Code:

```
claude mcp add --scope user openmhp -- mhp-mcp
```

Any other harness (Codex, OpenClaw, Hermes, Claude Science, Open Science, or your own) takes:

```
{"mcpServers": {"openmhp": {"command": "mhp-mcp"}}}
```

3. Add two simulated instruments, a thermocycler and a plate-handling arm:

```
mhp lab demo
```

### With npx

Needs Node 18 or newer as well. One command installs the runtime in `~/.openmhp` and the Agent Skills, and registers the MCP server with Claude Code and Codex; for any other harness it prints the line to paste.

```
npx -y openmhp-cli@latest setup
```

```
npx -y openmhp-cli@latest demo
```

2. Other harnesses take:

```
{"mcpServers": {"openmhp": {"command": "npx", "args": ["-y", "openmhp-cli"]}}}
```

The npx launcher does not put `mhp` on your PATH: run any `mhp ...` command on this site as `npx -y openmhp-cli@latest mhp ...`.

### Then talk to it

Restart your agent and ask:

```
Find a thermocycler, show me its operating instructions, and rehearse a
3-cycle PCR at 95/58/72 °C before running it.
```

Ask for a 200 °C setpoint too: the driver refuses it and returns the allowed range. If your harness shows MCP prompts, `/setup-my-lab` starts a guided setup. Whenever something seems off, ask the machine itself; it lists each part of its setup, its state, and the exact command for anything that needs doing:

```
mhp status
```

| You say | What happens |
|---|---|
| "find the instruments on my network" | the agent scans for devices that speak MHP (mDNS and a probe of `/mhp.json`) and lists what it found |
| "add the thermocycler" | it joins your lab, is searchable from then on, and its owner's instructions are one call away |
| "onboard my hotplate" | the server interviews you through the agent, about ten plain-language questions, then writes the device package itself, validates it and adds it; hand-operated and serial/USB instruments need no code, and the hotplate is now under the same safety gates as everything else |
| "run a 30-cycle PCR at 95/58/72 and hold at 4 °C" | the agent finds the matching recipe, rehearses it in plan mode and shows you every step and every point where it will ask you, then runs it and reports the temperature it actually read |
| "log the incubator overnight" | a background run writes readings to a CSV in the run folder; in the morning "what happened last night?" reads the run log and the file |
| "is it safe to let the agent use the hotplate?" | a safety card: the limits the driver enforces, which actions need a person, whether e-stop and watchdog exist, and live probes showing an out-of-range request being refused |

## Set up a lab, step by step

A lab uses up to three kinds of machine. Trying OpenMHP needs only the first.

| Machine | Who sets it up | What runs there |
|---|---|---|
| **Agent machine**: a scientist's laptop or workstation, where the agent runs | each scientist | the MCP server and the Agent Skills |
| **Instrument PC**: the computer wired to an instrument; no agent on it | whoever looks after the instrument | `mhp node`, serving its instruments in the background |
| **Lab gateway**: an always-on machine on the company network | the lab's operator | the relay, pairing, and experiments run for scientists |

You need the gateway when the lab network is closed to the outside, or when scientists hand whole experiments to the lab. On an open lab network, agent machines find instrument PCs directly ([lab nodes](https://openmhp.com/lab-nodes)). Set up the gateway first: it prints the codes the other two use to join.

Always start pip as `pip install -U` and npx as `npx -y openmhp-cli@latest`: plain `pip install` keeps whatever version is already installed, and plain `npx openmhp-cli` reuses whatever version npx cached the first time.

### 1. Lab gateway (the operator, once)

Any always-on Linux, macOS or Windows machine on the company network that lab PCs and agent machines can reach.

1. Install OpenMHP:

```
pip install -U openmhp
```

2. Make this machine the gateway. It asks for the address others will use and a port (take 8443), and makes a certificate:

```
mhp gateway init
```

3. Run it now and after every reboot:

```
mhp gateway serve --install-service
```

4. Only if scientists will run experiments through the lab: give each scientist a folder reached over SSH. Run this, then the one `sudo` line it prints:

```
mhp gateway ssh
```

For one Linux user per scientist instead of one shared account, run `mhp gateway ssh users`; `pair-agent` then runs with `sudo`, because it creates each scientist's user. Also install the agent harness (for example Claude Code) on the gateway and sign it in once with the lab's account: the gateway starts a session of it for each run.

5. Check everything; each problem comes with its fix:

```
mhp gateway check
```

6. For each instrument PC, print a one-time code (15 minutes) and the line to paste there:

```
mhp gateway pair
```

7. For each scientist, print a one-time code (1 hour) and send it to them in chat. Naming them sets their folder on the gateway, so they type no name:

```
mhp gateway pair-agent alice
```

After an update (`pip install -U openmhp`), restart it:

```
mhp gateway restart
```

More: [gateway and relay](https://openmhp.com/gateway).

### 2. Instrument PC (once per PC)

No agent is needed on it. Every ready-made package ships inside OpenMHP, so this needs no web or git access.

1. Install OpenMHP:

```
pip install -U "openmhp[node]"
```

2. List the ready-made packages:

```
mhp node add
```

3. Add the instrument you are standing next to:

```
mhp node add waters-empower-hplc
```

It asks only what a person knows and checks the answers against the instrument. If the lab has a gateway, paste the line from `mhp gateway pair` when it asks. Its last question installs the background service.

4. Check it:

```
mhp status
```

With Node instead: `npx -y openmhp-cli@latest node add waters-empower-hplc`. For an instrument not on the list, tell your agent *"Onboard my IKA hotplate. I have the manual."* More: [lab nodes](https://openmhp.com/lab-nodes), [add an instrument](https://openmhp.com/add-a-device).

### 3. Scientist's machine (once per scientist)

1. Install OpenMHP as in [Try it in five minutes].

2. Join the lab gateway with the code the operator sent, using the gateway's address with its port:

```
mhp agent --join https://gw.office:8443 <code>
```

Installed with npx:

```
npx -y openmhp-cli@latest join https://gw.office:8443 <code>
```

It shows the gateway's certificate fingerprint: **stop if it differs from what the operator's `pair-agent` printed.** If the operator made the code without a name, add `--name alice`: the name becomes your folder on the gateway. Joining also installs the `openmhp-lab-gateway` skill and, when the gateway offers it, sets up `ssh mhp-gateway`. There are no keys to paste.

3. Check the connection; `gateway link` should say `connected`:

```
mhp status
```

4. Restart your agent and ask in plain English: *"Find the GC on the lab gateway"*, or *"Ask the lab to find GC conditions that separate ethanol from isopropanol, using my retention model."*

5. Optional: hear about your runs (questions, plans to approve, results) even when no agent is open:

```
mhp agent watch --install-service
```

Your agent drives the gateway for you. The commands it runs, for doing it by hand, are on [experiment flow](https://openmhp.com/experiment-flow#by-hand).

On machines where the agent has no web or git access, the whole guide is in the installed package: `mhp guide` lists the topics, `mhp guide troubleshooting` settles the usual setup problems, `mhp guide search <words>` finds a command. `mhp --version` says which OpenMHP a machine has; `mhp gateway --version`, `mhp node --version` and `mhp agent --version` also say what the running gateway, the instrument PC's service, or the joined gateway runs.

## Run the simulated instruments as network devices

To see what an instrument PC serves, run the two simulated instruments as network devices from the repository or the pip install. For a real instrument PC, `mhp node add <package>` does this properly and keeps it running.

```
pip install -U "openmhp[discovery]"                              # from PyPI; or clone github.com/kushalsinha/openmhp
mhp serve pkg:openmhp/devices/thermocycler-01 --http 18921     # this machine only; add --host <this PC's address> to serve the LAN
mhp serve pkg:openmhp/devices/arm-01 --http 18922
mhp lab scan                                                   # finds both; then: mhp lab add http://127.0.0.1:18921
```

## Check it from the shell

```
mhp http://localhost:18921 describe card                    # level 1
mhp http://localhost:18921 describe summary                 # level 2: operating instructions
mhp http://localhost:18921 write target_temperature 200     # refused: above the 105 degC limit
mhp http://localhost:18921 invoke run_protocol '{"steps":[{"temp":95,"hold_s":5}],"cycles":3}' --wait
mhp http://localhost:18921 estop
```

## First conversation

Ask the agent something concrete: *"Run a 3-cycle PCR at 95/58/72 on a thermocycler in bay 3, then hold at 4 °C."* A well-behaved agent will:

1. call `mhp_find` with that sentence and get a card for `thermocycler-01`;

2. call `mhp_describe` and read the owner's operating procedure, which says to close the lid and pre-heat it;

3. call `mhp_read` for `lid_closed`, then `mhp_write` for `lid_heater`;

4. call `mhp_invoke` for `run_protocol` and poll `mhp_job`, or hand the whole sequence to `mhp_run` using the package's `scripts/pcr.py`;

5. report the block temperature it read, not the temperature it intended.

Try asking for 200 °C. The driver refuses with a `LimitViolation` that names the limits, and the agent has to come back to you.

## Big labs: a shared directory

When devices are served from many bench PCs, run one directory that indexes them all and point every harness at it. The bridge then loads nothing until an agent searches.

```
python openmhp/skills/openmhp-adapt-fleet/scripts/build_manifest.py fleet.json tc=http://bench3:18921 arm=http://bench3:18922 ...
mhp serve-directory fleet.json --http 18900
mhp-mcp --directory http://lab-server:18900 --http 18800      # MCP over HTTP for remote harnesses
```

## See it scale

```
python examples/scale_demo.py      # 2,000 devices: 1,224,382 tokens the naive way, about 1,300 the MHP way
python tests/test_adapters.py      # adapters, live directory, device packages, against fakes
```

## Updating

When a new version is out, the OpenMHP server tells your agent once per session, with the command for your install. Run it and restart the agent:

Installed with pip:

```
pip install -U "openmhp[all]" && mhp skills install
```

Installed with npx (upgrades the runtime and the skills):

```
npx -y openmhp-cli@latest update
```

Instrument PCs never update themselves; how to update one is on [lab nodes](https://openmhp.com/lab-nodes#updating). The check reads PyPI at most once a day and sends nothing but the package name. Set `OPENMHP_NO_UPDATE_CHECK=1` to turn it off.

## Next

[**Add an instrument**Put your own hardware behind MHP.](https://openmhp.com/add-a-device) [**Lab nodes**Serve a bench PC's instruments; find them from your laptop.](https://openmhp.com/lab-nodes) [**Adapters**Already on OPC UA, ROS 2, SiLA 2, MADSci, PyLabRobot or MQTT.](https://openmhp.com/adapters)
