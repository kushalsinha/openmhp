<!-- generated from https://openmhp.com/quickstart by scripts/build_guide.py; edit the website, not this file -->

# Quickstart

One command installs OpenMHP into any agent harness. Then you add instruments by talking to your agent. No hardware needed to try it.

## The short version

```
npx -y openmhp-cli@latest setup
```

That is the whole install for a scientist. It puts the runtime in `~/.openmhp`, installs four Agent Skills where your harness looks for them, and registers the OpenMHP MCP server with Claude Code and Codex. For any other harness (OpenClaw, Hermes, Claude Science, Open Science, or your own) it prints the one line to paste:

```
{"mcpServers": {"openmhp": {"command": "npx", "args": ["-y", "openmhp-cli"]}}}
```

Then open your agent and talk to it. If your harness shows MCP prompts, `/setup-my-lab` starts the whole thing.

| You say | What happens |
|---|---|
| "find the instruments on my network" | the agent scans for devices that speak MHP (mDNS and a probe of `/mhp.json`) and lists what it found |
| "add the thermocycler" | it joins your lab, is searchable from then on, and its owner's instructions are one call away |
| "onboard my hotplate" | the server interviews you through the agent, about ten plain-language questions, then writes the device package itself, validates it and adds it; hand-operated and serial/USB instruments need no code, and the hotplate is now under the same safety gates as everything else |
| "run a 30-cycle PCR at 95/58/72 and hold at 4 °C" | the agent finds the matching recipe, rehearses it in plan mode and shows you every step and every point where it will ask you, then runs it and reports the temperature it actually read |
| "log the incubator overnight" | a background run writes readings to a CSV in the run folder; in the morning "what happened last night?" reads the run log and the file |
| "is it safe to let the agent use the hotplate?" | a safety card: the limits the driver enforces, which actions need a person, whether e-stop and watchdog exist, and live probes showing an out-of-range request being refused |

Requires Node 18 and Python 3.10 or newer. The launcher is [openmhp-cli](https://www.npmjs.com/package/openmhp-cli) on npm and pulls the [openmhp](https://pypi.org/project/openmhp/) runtime from PyPI into `~/.openmhp`; nothing is installed globally.

## Which machine runs what

Trying OpenMHP needs only your own machine. A lab adds the other two as it needs them.

| Machine | With Node | With pip only |
|---|---|---|
| **Agent machine**: your laptop or workstation, where the agent runs | `npx -y openmhp-cli@latest setup` | `pip install -U "openmhp[all]"` `mhp skills install` then add the MCP server `mhp-mcp` to your harness |
| **Instrument PC**: the computer wired to an instrument; no agent on it | `npx -y openmhp-cli@latest node add <package>` | `pip install -U "openmhp[node]"` `mhp node add <package>` |
| **Lab gateway**: an always-on machine on the company network, when the lab network is closed or scientists run experiments through the lab | (pip) | `pip install -U openmhp` `mhp gateway init` `mhp gateway serve --install-service` |

Always start npx as `npx -y openmhp-cli@latest`, and pip as `pip install -U`: plain `npx openmhp-cli` reuses whatever version npx cached the first time, and plain `pip install` keeps whatever version is already installed. Details: [lab nodes](https://openmhp.com/lab-nodes) for the instrument PC, [gateway and relay](https://openmhp.com/gateway) for pairing the other two with a gateway, [experiment flow](https://openmhp.com/experiment-flow) for runs through it.

On machines where the agent has no web or git access, the whole guide is in the installed package: `mhp guide` lists the topics, `mhp guide troubleshooting` settles the usual setup problems, `mhp guide search <words>` finds a command. `mhp --version` says which OpenMHP a machine has; `mhp gateway --version`, `mhp node --version` and `mhp agent --version` also say what the running gateway, the instrument PC's service, or the joined gateway runs.

## Try it with no hardware

The package ships two simulated instruments, a thermocycler and a plate-handling arm. Add them to your lab and use them exactly like real ones:

```
npx -y openmhp-cli@latest demo
npx -y openmhp-cli@latest list
```

Or clone the repository and run them as network devices. For a real instrument PC, `mhp node add <package>` does this properly and keeps it running — see [lab nodes](https://openmhp.com/lab-nodes).

```
pip install -U "openmhp[discovery]"                              # from PyPI; or clone github.com/kushalsinha/openmhp
mhp serve pkg:openmhp/devices/thermocycler-01 --http 18921     # this machine only; add --host <this PC's address> to serve the LAN
mhp serve pkg:openmhp/devices/arm-01 --http 18922
npx -y openmhp-cli@latest scan                                                # finds both; then: npx -y openmhp-cli@latest add http://127.0.0.1:18921
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

```
npx -y openmhp-cli@latest update                       # installed with npx: upgrades the runtime and the skills
pip install -U "openmhp[all]" && mhp skills install    # installed with pip
```

Instrument PCs never update themselves; how to update one is on [lab nodes](https://openmhp.com/lab-nodes#updating). The check reads PyPI at most once a day and sends nothing but the package name. Set `OPENMHP_NO_UPDATE_CHECK=1` to turn it off.

## Next

[**Add an instrument**Put your own hardware behind MHP.](https://openmhp.com/add-a-device) [**Lab nodes**Serve a bench PC's instruments; find them from your laptop.](https://openmhp.com/lab-nodes) [**Adapters**Already on OPC UA, ROS 2, SiLA 2, MADSci, PyLabRobot or MQTT.](https://openmhp.com/adapters)
