# openmhp-cli

Give any AI agent harness safe control of your lab instruments through the
[Open Model Hardware Protocol](https://openmhp.com). This launcher installs and runs the
[`openmhp`](https://pypi.org/project/openmhp/) Python runtime in `~/.openmhp`. Needs Node 18+ and
Python 3.10+. Prefer Python only? Every step below has a pip form: see
[Set up a lab, step by step](https://github.com/kushalsinha/openmhp#set-up-a-lab-step-by-step).

Always run it as `npx -y openmhp-cli@latest ...`. Plain `npx openmhp-cli` reuses whatever version
npx cached the first time, however old.

## Try it in five minutes (no hardware)

1. Install the runtime and the Agent Skills, and register the MCP server with Claude Code and Codex:
   ```bash
   npx -y openmhp-cli@latest setup
   ```
2. Add two simulated instruments, a thermocycler and a plate-handling arm:
   ```bash
   npx -y openmhp-cli@latest demo
   ```
3. Restart your agent and ask: *“Find a thermocycler, show me its operating instructions, and rehearse a
   3-cycle PCR at 95/58/72 °C before running it.”* Ask for 200 °C too: the driver refuses it.

Any other MCP harness takes:

```json
{"mcpServers": {"openmhp": {"command": "npx", "args": ["-y", "openmhp-cli"]}}}
```

To check the install at any time, run the command below. It lists each part of this machine's setup, its
state, and the exact command for anything that needs doing:

```bash
npx -y openmhp-cli@latest mhp status
```

## Join your lab's gateway (scientists)

Your lab's operator runs `mhp gateway pair-agent <your name>` on the gateway and sends you a one-time code
(valid one hour).

1. Set up this machine as above:
   ```bash
   npx -y openmhp-cli@latest setup
   ```
2. Join with the gateway's address, its port and the code:
   ```bash
   npx -y openmhp-cli@latest join https://<gateway>:<port> <code>
   ```
   It shows the gateway's certificate fingerprint. **Stop if it differs from what the operator's
   `pair-agent` printed.** If the operator made the code without a name, add `--name <your name>`: it
   becomes your folder on the gateway. Joining installs the `openmhp-lab-gateway` skill, and sets up
   `ssh mhp-gateway` when the gateway offers it.
3. Check the connection. `gateway link` should say `connected`:
   ```bash
   npx -y openmhp-cli@latest mhp status
   ```
4. Restart your agent and ask in plain English. For example: *“Find the GC on the lab gateway”*, or
   *“Ask the lab to find GC conditions that separate ethanol from isopropanol, using my retention model.”*

The agent drives the gateway for you. The commands it uses, for running them by hand, are in
[Set up a lab, step by step](https://github.com/kushalsinha/openmhp#3-scientists-machine-once-per-scientist).
The story behind it is in [Experiment flow](https://openmhp.com/experiment-flow).

## On an instrument PC (the computer wired to an instrument)

No agent is needed there.

1. List the ready-made packages:
   ```bash
   npx -y openmhp-cli@latest node add
   ```
2. Add the instrument you are standing next to:
   ```bash
   npx -y openmhp-cli@latest node add waters-empower-hplc
   ```
   It asks the instrument's questions, then for the line from `mhp gateway pair` if the lab has a gateway,
   and keeps the instrument served in the background.

`node setup <package>` asks the questions again; `node --service-status` and
`node --uninstall-service` manage the background service.

## On the lab gateway

The gateway is set up with pip, not npx.

1. Install OpenMHP:
   ```bash
   pip install -U openmhp
   ```
2. Make this machine the gateway. It asks for an address and a port, and makes a certificate:
   ```bash
   mhp gateway init
   ```
3. Run it now and after every reboot:
   ```bash
   mhp gateway serve --install-service
   ```
4. Print a code for each instrument PC:
   ```bash
   mhp gateway pair
   ```
5. Print a code for each scientist, and send it to them:
   ```bash
   mhp gateway pair-agent alice
   ```

For experiments run through the gateway, there is one more step (`mhp gateway ssh`). See
[Set up a lab, step by step](https://github.com/kushalsinha/openmhp#1-lab-gateway-the-operator-once) and
[Gateway and relay](https://openmhp.com/gateway).

## Updating

On the agent machine, update the runtime and the skills, then restart the agent:

```bash
npx -y openmhp-cli@latest update
```

On an instrument PC, this restarts its service on the new version:

```bash
npx -y openmhp-cli@latest node <folder>
```

The OpenMHP server tells your agent when a new version is out.
Set `OPENMHP_NO_UPDATE_CHECK=1` to turn the check off.

## Without web access

The user guide ships inside the package, so an agent with no web or git access can read it:

```bash
npx -y openmhp-cli@latest guide
```

```bash
npx -y openmhp-cli@latest guide search <words>
```

```bash
npx -y openmhp-cli@latest --version
```

The first lists the topics (`guide <topic>` reads one). The second finds every line that mentions those
words. The third shows this launcher's version and the OpenMHP it runs.

## Other commands

`scan [host...]`, `add <target>`, `list`, `remove <id>`, `validate <folder>`,
`device <folder> --http 18921`, and `mhp <args>` (the full `mhp` command line).

Everything is kept in `~/.openmhp`, and the launcher does not put `mhp` on your PATH, so run it as
`npx -y openmhp-cli@latest mhp ...`. A bare `mhp` belongs to a separate pip install, if there is one; update
that with `pip install -U openmhp` (plain `pip install` keeps an old version).
