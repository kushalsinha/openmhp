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

Other commands: `npx openmhp-cli scan [host...]`, `add <target>`, `list`, `remove <id>`,
`validate <folder>`, `device <folder> --http 18921`, `update`.

Requires Node 18+ and Python 3.10+. Everything is kept in `~/.openmhp`.
