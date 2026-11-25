# openmhp-cli

Give any AI agent harness safe control of your lab instruments through the
[Open Model Hardware Protocol](https://openmhp.com). This package installs the
[`openmhp`](https://pypi.org/project/openmhp/) Python runtime in `~/.openmhp` and puts its commands on your
PATH. Needs Node 18+ and Python 3.10+.

```bash
npm install -g openmhp-cli
```

That gives you `mhp` and `mhp-mcp`, the same commands a pip install of OpenMHP gives, so every `mhp ...`
command in the [README](https://github.com/kushalsinha/openmhp#readme) and on [openmhp.com](https://openmhp.com)
works as written. The first command you run installs the Python runtime, which takes a minute.

## Try it in five minutes (no hardware)

1. Install the Agent Skills into the harnesses on this machine:
   ```bash
   mhp skills install
   ```
2. Register the MCP server with your agent. For Claude Code:
   ```bash
   claude mcp add --scope user openmhp -- mhp-mcp
   ```
   Any other harness takes `{"mcpServers": {"openmhp": {"command": "mhp-mcp"}}}`.
   (`openmhp setup` does steps 1 and 2 at once, for Claude Code and Codex.)
3. Add two simulated instruments, a thermocycler and a plate-handling arm:
   ```bash
   mhp lab demo
   ```
4. Restart your agent and ask: *“Find a thermocycler, show me its operating instructions, and rehearse a
   3-cycle PCR at 95/58/72 °C before running it.”* Ask for 200 °C too: the driver refuses it.

To check the install at any time, run the command below. It lists each part of this machine's setup, its
state, and the exact command for anything that needs doing:

```bash
mhp status
```

## Join your lab's gateway (scientists)

Your lab's operator runs `mhp gateway pair-agent <your name>` on the gateway and sends you a one-time code
(valid one hour). After the steps above:

1. Join with the gateway's address, its port and the code:
   ```bash
   mhp agent --join https://<gateway>:<port> <code>
   ```
   It shows the gateway's certificate fingerprint. **Stop if it differs from what the operator's
   `pair-agent` printed.** If the operator made the code without a name, add `--name <your name>`: it
   becomes your folder on the gateway. Joining installs the `openmhp-lab-gateway` skill, and sets up
   `ssh mhp-gateway` when the gateway offers it.
2. Check the connection. `gateway link` should say `connected`:
   ```bash
   mhp status
   ```
3. Restart your agent and ask in plain English. For example: *“Find the GC on the lab gateway”*, or
   *“Ask the lab to find GC conditions that separate ethanol from isopropanol, using my retention model.”*

The agent drives the gateway for you. The commands it uses, for running them by hand, are in
[Set up a lab, step by step](https://github.com/kushalsinha/openmhp#3-scientists-machine-once-per-scientist).

## On an instrument PC (the computer wired to an instrument)

No agent is needed there.

1. List the ready-made packages:
   ```bash
   mhp node add
   ```
2. Add the instrument you are standing next to:
   ```bash
   mhp node add waters-empower-hplc
   ```
   It asks the instrument's questions, then for the line from `mhp gateway pair` if the lab has a gateway,
   and keeps the instrument served in the background.
3. Check it:
   ```bash
   mhp status
   ```

`mhp node setup <package>` asks the questions again; `mhp node --service-status` and
`mhp node --uninstall-service` manage the background service.

Some instrument software needs a 32-bit Python (UNICORN's OPC server, the Empower Toolkit). The runtime is
made from the first of `python3`, `python` or `py` on PATH, so make that the 32-bit one before the first run.

## On the lab gateway

The gateway is set up with pip: `pip install -U openmhp`, then `mhp gateway init`. See
[Set up a lab, step by step](https://github.com/kushalsinha/openmhp#1-lab-gateway-the-operator-once) and
[Gateway and relay](https://openmhp.com/gateway).

## Updating

```bash
npm install -g openmhp-cli@latest && openmhp update
```

This updates the command, the runtime and the skills; then restart the agent. On an instrument PC, restart
its service on the new version:

```bash
npm install -g openmhp-cli@latest && mhp node --install-service
```

The OpenMHP server tells your agent when a new version is out, with the command for your install.
Set `OPENMHP_NO_UPDATE_CHECK=1` to turn the check off.

## Without installing

Every command also runs through npx, without a global install:

```bash
npx -y openmhp-cli@latest setup
```

```bash
npx -y openmhp-cli@latest mhp status
```

Always give npx the `@latest`: plain `npx openmhp-cli` reuses whatever version npx cached the first time.
A harness can start the MCP server the same way:
`{"mcpServers": {"openmhp": {"command": "npx", "args": ["-y", "openmhp-cli"]}}}`.

## Without web access

The user guide ships inside the package, so an agent with no web or git access can read it:

```bash
mhp guide
```

`mhp guide <topic>` reads one topic, `mhp guide search <words>` finds every line that mentions those words,
and `openmhp --version` shows this package's version and the OpenMHP it runs.

## If another `mhp` is on your PATH

A separate pip install of OpenMHP has its own `mhp`, and whichever comes first on PATH wins. `openmhp setup`
says when it finds one. Keep one: `pip uninstall openmhp`, or `npm uninstall -g openmhp-cli`.
