# openmhp-cli

Give any AI agent harness safe control of your lab instruments through the
[Open Model Hardware Protocol](https://openmhp.com). This launcher installs and runs the
[`openmhp`](https://pypi.org/project/openmhp/) Python runtime in `~/.openmhp`. Needs Node 18+ and
Python 3.10+.

Always run it as `npx -y openmhp-cli@latest ...`. Plain `npx openmhp-cli` reuses whatever version
npx cached the first time, however old.

## On your laptop or workstation (where the agent runs)

```bash
npx -y openmhp-cli@latest setup     # runtime, Agent Skills, and the MCP server for Claude Code and Codex
npx -y openmhp-cli@latest demo      # optional: two simulated instruments to try it with no hardware
```

Then, in your agent: *"find the instruments on my network"*, *"add the thermocycler"*,
*"onboard my hotplate"*, *"run a 30-cycle PCR at 95/58/72"*. Any other MCP harness takes:

```json
{"mcpServers": {"openmhp": {"command": "npx", "args": ["-y", "openmhp-cli"]}}}
```

If your lab has a gateway, join it once with the code its admin gives you
(from `mhp gateway pair-agent`):

```bash
npx -y openmhp-cli@latest join https://<gateway>:<port> <code> --name <your name, e.g. alice>
```

The name becomes your folder on the gateway (unless the admin already chose it when making the code).

Through the gateway you can also ask the lab for a whole experiment in plain English and hand over
your own models and optimizer: see [Experiment flow](https://openmhp.com/experiment-flow).

## On an instrument PC (the computer wired to an instrument)

No agent is needed there. Name the instrument:

```bash
npx -y openmhp-cli@latest node add                       # lists the ready-made packages
npx -y openmhp-cli@latest node add waters-empower-hplc   # fetches it, asks its questions, pairs with the gateway, keeps it running
```

`node setup <package>` asks the questions again, `node --service-status` and
`node --uninstall-service` manage the background service. A PC with only Python can do the same
with `pip install -U "openmhp[node]"` and `mhp node add`.

## On the lab gateway

The gateway is set up with pip: `pip install -U openmhp`, then `mhp gateway init`. See
[Gateway and relay](https://openmhp.com/gateway).

## Without web access

The user guide ships inside the package, so an agent with no web or git access can read it:

```bash
npx -y openmhp-cli@latest guide                    # the topics; guide <topic> reads one
npx -y openmhp-cli@latest guide search <words>     # every line that mentions them
npx -y openmhp-cli@latest --version                # this launcher and the OpenMHP it runs
```

## Updating

```bash
npx -y openmhp-cli@latest update           # on the agent machine: runtime and skills; then restart the agent
npx -y openmhp-cli@latest node <folder>    # on an instrument PC: restarts its service on the new version
```

The OpenMHP server tells your agent when a new version is out.
Set `OPENMHP_NO_UPDATE_CHECK=1` to turn the check off.

Other commands: `scan [host...]`, `add <target>`, `list`, `remove <id>`, `validate <folder>`,
`device <folder> --http 18921`, and `mhp <args>` (the full `mhp` command line). Everything is kept
in `~/.openmhp`, and its `mhp` is not put on your PATH: run it as `npx -y openmhp-cli@latest mhp ...`.
A bare `mhp` belongs to a separate pip install, if there is one; update that with
`pip install -U openmhp` (plain `pip install` keeps an old version).
