# Instruments behind the lab firewall: the MHP relay

Lab instruments usually sit on a network nothing outside can reach, and IT will not open it. With the
relay, nothing has to be opened: each lab PC connects **outward** to a gateway and registers its
instruments, and agents reach them at the gateway. The lab PC needs no AI agent and no network change.

```
lab PC (behind firewall)                  office or cloud                     agent machine
mhp node C:\lab\devices  ──HTTPS out──▶  mhp gateway serve :443  ◀──HTTPS──  Claude Code + mhp-mcp
```

Everything is done with two commands, `mhp node` on the lab PC and `mhp gateway` on the gateway. Each
either finishes or prints the one thing to do next. No files to edit.

## On the gateway machine, once

Any always-on machine on the enterprise network that the lab PCs and the agent machines can reach:
a desktop or small VM in the office. Someone working from home reaches it the moment their VPN is
up, exactly as they would at their desk. `pip install openmhp`, then:

```
mhp gateway init
mhp gateway serve --install-service
```

`init` asks for the address others will use and the port (press Enter for the defaults), and makes a
certificate if IT has not given you one (`--cert`/`--key` when they do). `serve` runs the gateway and
listens on **that one address only**, never on every interface; if the name does not resolve to this
machine it says so and stops. `--install-service` keeps it running across reboots.

## For each lab PC

On the gateway:

```
mhp gateway pair
```

prints a one-time code and a line to run on the lab PC. On the lab PC, where the device packages are:

```
pip install openmhp
mhp node C:\lab\devices --join https://gw.office ab12-cd34
```

It shows the gateway's certificate fingerprint (compare with what `pair` printed), joins, and serves.
From then on plain `mhp node C:\lab\devices` connects by itself, and `--install-service` keeps it
running. If the gateway is down it retries quietly; the instruments keep working for anyone on the lab
network meanwhile.

If a `config.json` is not filled in or a port is taken, `mhp node` says so and what to do before it
serves anything.

## For each agent machine

On the gateway:

```
mhp gateway add-agent kushal-laptop
```

prints what to run on that machine: a token to put in `OPENMHP_DEVICE_TOKEN`, the certificate to trust
if it is self-made, and `mhp-mcp --directory https://gw.office/directory/`. The agent then finds every
instrument of every joined lab PC through that one URL. `mhp gateway remove-agent <name>` revokes it.

## Day to day

- `mhp gateway status`: which lab PCs are connected, their instruments and states, the agent URLs.
- `mhp gateway check`: `OK` or `FIX` for the gateway, each lab PC and each instrument, with the fix spelled out.
- The only network requirement, for IT: lab PCs and agent machines must reach the gateway's address on
  its port. Nothing inbound to the lab.

## What the relay guarantees

- Every connection is outbound from the lab PC, over HTTPS; it also passes corporate web proxies.
- A request is handed to a node **once**. If the node is offline the agent gets 503 at once; if the node
  does not answer in time (120 s, or the `X-MHP-Timeout` header) the agent gets 504. In both cases nothing
  is re-sent, because MHP operations are not idempotent (SPEC 7.6). The agent checks `jobs/status` before
  repeating an action.
- Identity is the gateway's. The lab PC sees the agent's name as the session, so one agent cannot take
  another's lease (SPEC 5.7). The lab PC's own token never leaves it; agents hold agent tokens.
- Events reach agents over SSE as the node pushes them. Events during a gap are not replayed; agents
  confirm with `jobs/status`, `signals/read` and `mhp_data op=updates`, as on a LAN.
- The gateway is the approval boundary: it forwards `approved: true` from authenticated agents, so give
  agent tokens only to harnesses that really ask a person (Claude Code through the stdio bridge, not
  `mhp-mcp --http`).
- Emergency stop never depends on the relay: the hardware stop, the vendor GUI and the device-side
  watchdog are on the bench. Pick `watchdog_action` per device as on a LAN.

## Files

- Gateway: `<OPENMHP_HOME>/gateway/gateway.json` (nodes, their tokens, agents, pending codes; mode 0600),
  `gateway.crt|key` when self-made.
- Lab PC: `<OPENMHP_HOME>/node.json` (gateway address, node token, name) and `gateway-pin.pem`
  (the pinned certificate).

`tests/test_relay.py` runs the whole thing on one machine.
