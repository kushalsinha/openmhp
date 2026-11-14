# openmhp-cli

One command to give any AI agent harness safe control of your lab instruments through the
[Open Model Hardware Protocol](https://openmhp.com).

```bash
npx openmhp-cli setup      # installs the runtime and skills, registers the MCP server with your harness
```

Then, in your agent: *"find the instruments on my network"*, *"add the thermocycler"*,
*"onboard my hotplate"*, *"run a 30-cycle PCR at 95/58/72"*.

Harness config, if you prefer to add it by hand:

```json
{"mcpServers": {"openmhp": {"command": "npx", "args": ["-y", "openmhp-cli"]}}}
```

Try it with no hardware: `npx openmhp-cli demo` adds a simulated thermocycler and plate arm.

Other commands: `scan [host...]`, `add <target>`, `list`, `remove <id>`, `validate <folder>`,
`device <folder> --http 18921`, `node` (serve the instruments on a bench PC), and `mhp <args>`
(the full `mhp` command line, for example `npx openmhp-cli mhp node add`).

A scientist can also ask a lab gateway for a whole experiment in plain English and hand over
their own models and optimizer: see [Experiment flow](https://openmhp.com/experiment-flow).

To update, run the command below, then restart your agent. It upgrades the runtime and the
skills. The OpenMHP server tells your agent when a new version is out.

```bash
npx -y openmhp-cli@latest update
```

Requires Node 18+ and Python 3.10+. Everything is kept in `~/.openmhp`.
