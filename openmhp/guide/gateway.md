<!-- generated from https://openmhp.com/gateway by scripts/build_guide.py; edit the website, not this file -->

# Gateway and relay

Most instrument networks are closed: nothing outside may connect in, and IT will not add a rule for a bench PC. OpenMHP works there without one. The bench PC dials *out* to a gateway on the company network and asks it for work; your agent talks to the gateway. Nothing is opened, and the bench PC never needs an AI agent on it.

## The shape of it

Three kinds of machine, and every connection between them points at the one in the middle.

[Figure: Three zones. Bench PCs on the lab network, behind a dashed firewall line, run mhp node and connect outward to one gateway on the company network. Agent machines, an office laptop and a home laptop on the VPN, reach the same gateway with an agent token. The gateway has a node face, an agent face and a directory. Every arrow points at the gateway; none enters the lab.]

*Every arrow points at the gateway. The lab firewall sees only outbound HTTPS from the bench PCs, which is what it already allows for a web browser.*

- **The bench PC** runs `mhp node` exactly as on a [lab node](https://openmhp.com/lab-nodes), serving its instruments locally. Once joined, it also keeps a connection open to the gateway and takes requests from it. It needs `pip install -U openmhp` and one command, nothing else.

- **The gateway** is one Python process, `mhp gateway serve`, on any always-on desktop or small VM on the company network. It listens on one address and one port, over HTTPS. Bench PCs register with it; agents reach every registered instrument through it at the same URL shapes a device has on a LAN, so no client code changes.

- **Agent machines** point `mhp-mcp` at the gateway's directory and use the same `mhp_find`, `mhp_read` and `mhp_invoke` as always. Working from home changes nothing: the moment the VPN is up you are on the company network, and the gateway is where it always was.

> Nobody has to run this in a cloud. The gateway belongs on the company network, where people in the office and people on the VPN already are. IT has one line to confirm: lab PCs and agent machines can reach the gateway's address and port.

## What happens on one call

The relay is ordinary HTTPS from both sides, with the bench PC asking for work instead of waiting for it. That is the whole trick, and it means the gateway never has to connect into the lab.

[Figure: Sequence diagram. The lab PC already has GET /relay/next open on the gateway and waits up to 25 seconds for work. The agent posts a JSON-RPC request with its token to the device URL on the gateway. The gateway checks the token and queues the request with the agent's name as the client. It answers the open poll with the request, once. The driver on the lab PC runs it, enforcing limits, interlocks, approvals and e-stop. The lab PC posts the reply; the gateway returns it to the agent. Events go up as a batch and down as server-sent events. If the lab PC is offline the agent gets 503 at once; if it does not answer within 120 seconds, 504; the request is dropped either way and never re-sent.]

*One request, one delivery. The driver on the bench enforces every limit exactly as it would for an agent on the lab network.*

1. The bench PC keeps a long-poll open on the gateway, `GET /relay/next`, and renews it every 25 seconds. That poll is also how the gateway knows the PC is alive.

2. Your agent sends the usual request to the usual kind of URL, `POST /<node>/<device>/rpc`, with its agent token. An unknown token is refused before anything is queued.

3. The gateway queues the request with the *agent's name* as the client, so leases on the bench PC are per agent, and carries a person's approval because it authenticated who asked.

4. The gateway answers the open poll with the request. It is handed over once.

5. The driver runs it on the bench PC. Limits, interlocks, approval levels and the e-stop are enforced there, beside the hardware, as always.

6. The bench PC posts the reply; the gateway matches it to the waiting request and returns it. Notifications travel the same road, batched upward within half a second and streamed to the agent as server-sent events.

### Once, or not at all

If the bench PC is offline, which the gateway decides when no poll has arrived for 45 seconds, the agent gets a 503 at once naming the PC and when it was last seen. If the PC is online but does not answer within the timeout, 120 seconds unless the agent asks for longer with `X-MHP-Timeout`, the agent gets a 504. In both cases the request is dropped and never re-sent on the agent's behalf, because starting a protocol twice is not the same as starting it once. The agent checks the job's status before repeating anything, which is what the [specification](https://openmhp.com/spec/safety) asks of it on any transport.

## Pairing and trust

Three commands set it up, and each one hands out a different secret to a different machine.

[Figure: Three steps. On the gateway, mhp gateway pair prints a one-time code valid fifteen minutes and the certificate fingerprint. On the lab PC, once, mhp node with --join, the gateway URL and the code compares the fingerprint, pins the certificate, receives a node token, saves node.json and serves; later runs reconnect by themselves. For each agent machine, mhp gateway pair-agent prints a one-hour code; mhp agent --join with the gateway URL and the code pins the certificate and saves the agent token; plain mhp-mcp then uses it. The certificate is pinned by everyone, the node token never leaves the lab PC, the agent token names the session.]

*A lab PC code lasts fifteen minutes and an agent code an hour; both work once. A reinstalled bench PC pairs again with a new code and gets its own name back; the old token stops working.*

### On the gateway machine, once

Any always-on desktop or small VM on the company network. `pip install -U openmhp`, then:

```
mhp gateway init                      # asks for the address others will use and a port; makes a certificate
mhp gateway serve --install-service   # runs now and after every reboot
```

The gateway listens on that one address only, never on every interface. If IT gives you a certificate, pass `--cert` and `--key` to `init`; otherwise it makes one, and every machine that joins pins it. TLS 1.2 is the oldest it will speak.

### For each lab PC

On the gateway, `mhp gateway pair` prints a one-time code and the line to paste. On the lab PC, the scientist names the instrument they are standing next to:

```
pip install -U "openmhp[node]"
mhp node add waters-empower-hplc
```

It asks the instrument's own questions, then *Does your lab have an OpenMHP gateway? Paste the line from mhp gateway pair*. Pasting it joins; the last question installs the background service. `mhp node add` alone lists the ready-made packages; each carries its own vendor route (a serial protocol, a Web API, a COM SDK). A PC that already serves packages joins once with `mhp node --join https://gw.office ab12-cd34`. Joining shows the gateway's certificate fingerprint so you can compare it with what `pair` printed. From then on plain `mhp node` reconnects by itself. If the gateway is down the node retries quietly and the instruments keep working for anyone on the lab network. If a package is not set up or a port is taken, it says so in words, and which `mhp node setup` to run, before it serves anything.

### For each agent machine

On the gateway, `mhp gateway pair-agent` prints a one-time code that lasts an hour. Send it to the person in chat. On their machine, once:

```
mhp agent --join https://gw.office ef56-ab78 --name alice                      # installed with pip
npx -y openmhp-cli@latest join https://gw.office ef56-ab78 --name alice      # installed with npx
```

With npx, run OpenMHP's commands through the launcher (`npx -y openmhp-cli@latest mhp ...`): its `mhp` is not put on your PATH, and a bare `mhp` may be an older pip install.

On a gateway that runs experiments, the name is the scientist's folder there (lower-case letters, digits, `-` and `_`); without `--name` it is the computer's name. The operator can fix it instead with `mhp gateway pair-agent alice`, and the code then joins as alice whatever the machine says.

It shows the gateway's certificate fingerprint to compare with what `pair-agent` printed, pins the certificate, exchanges the code for an agent token and saves it in `~/.openmhp/agent.json`. From then on plain `mhp-mcp` finds every instrument of every joined lab PC through the gateway's directory: no environment variable to set, no certificate to copy, and the token never passes through the operator's hands. `mhp agent` says whether the gateway answers; `mhp agent leave` forgets it.

## Day to day

```
mhp gateway status                # which lab PCs are connected, what they serve, each agent's URL
mhp gateway check                 # OK or FIX for the gateway, each lab PC and each instrument, with the fix spelled out
mhp gateway restart               # after pip install -U openmhp: restarts the service, stops a copy started by hand
mhp gateway --version             # this install, what the service starts, and what the running gateway answers
mhp gateway remove-node bench-2   # its token stops working; pair again to bring it back
mhp gateway remove-agent old-laptop   # its token stops working; pair-agent again to bring it back
```

Both the gateway and the node install as a user service: systemd on Linux, a LaunchAgent on macOS, a Startup-folder entry on Windows. `mhp gateway check` is the thing to run when something seems off; it tells you which of the three machines to look at.

A running gateway keeps the code it started with, so after an update run `mhp gateway restart`. Once the service is installed, do not also start `mhp gateway serve` in a terminal: only one process can hold the port, and a copy started by hand before an update keeps answering with the old code. `restart` finds such a copy and stops it. Agents and lab PCs use exactly the address and port `mhp gateway status` prints; a name or load balancer in front of it must lead there, port included.

## What the relay guarantees

- **Every connection is outbound** from the lab PC, over HTTPS. It passes corporate web proxies. The only thing IT has to confirm is that lab PCs and agent machines can reach the gateway's address and port.

- **A request is delivered once or not at all.** Offline means an immediate error; no answer means a timeout. Nothing is ever re-sent on the agent's behalf.

- **Identity is the gateway's.** Agents hold agent tokens; the lab PC's own token never leaves it. The lab PC sees the agent's name as the session, so one agent cannot take another's lease.

- **The gateway is the approval boundary.** It forwards a person's confirmation from authenticated agents, so give agent tokens only to harnesses that really ask a person.

- **Emergency stop never depends on the relay.** The hardware stop, the vendor software and the device-side watchdog are all on the bench, exactly as on a LAN.

- **Pairing is explicit.** A lab PC code lasts fifteen minutes and an agent code an hour; both work once. A lab PC that is reinstalled pairs again and gets its own name back; the old token stops working.

## What it is not

It is not a VPN into the lab, and it does not make the lab network reachable: only the instruments a bench PC chose to serve are visible, and only through the gateway's device URLs. It is not a message queue: nothing is stored for later delivery, by design. And it is not required. On an open lab network, [lab nodes](https://openmhp.com/lab-nodes) find each other over mDNS and the gateway never enters the picture.

The wire-level rules are in the [specification](https://openmhp.com/spec/transports).

## Why an outbound relay, and not something else

Four other ways of crossing a lab firewall were weighed before the relay was built. A **TLS reverse proxy** inside the instrument network is sound where IT allows one inbound rule and already runs nginx or Caddy; the proxy must then do what the gateway does: hold the device tokens, overwrite the session identity, never retry, and let server-sent events through unbuffered. An **overlay network or reverse tunnel** (WireGuard, Tailscale, `ssh -R`) also needs no inbound rule but makes the whole bench PC reachable, not just its instruments. A **message broker** is right for sharing telemetry with dashboards and partners but wrong for control: a broker acknowledgement is not an instrument's answer, and the approval boundary is lost. A **one-way export** of run logs is the choice for regulated instruments that no agent may touch. The relay is the default because it needs no firewall change at any site and keeps every guarantee above; add a broker or an export beside it for anyone who should see but never control.

## Hardening the crossing

Whether the crossing is the gateway or a proxy of your own, these are the checks. Each names the fact it rests on.

- **Never retry in the middle.** MHP operations are not idempotent: a retried invoke is a second injection. The gateway delivers once or not at all; a proxy must have upstream retries off. On a lost response the agent reads state back instead of resending.

- **Let events through.** Buffering off, a read timeout above the fifteen-second keepalive, HTTP/1.1. Events are hints: after a reconnect the agent confirms outcomes with `jobs/status`, never from the stream alone.

- **Keep the device token on the bench.** Agents hold agent tokens; the crossing adds the device's bearer token itself. Put the device card behind the same authentication: it describes the lab.

- **Pin the session identity.** The device believes the client name it is sent. The crossing overwrites it with the authenticated identity, so no agent can name another's session and take its lease.

- **Forward approvals only from harnesses that ask a person.** With a valid token the device trusts `approved: true` as sent. Give agent tokens to harnesses that really elicit a confirmation, and strip the flag from any other caller.

- **Size leases and watchdogs for the link.** Session TTL and `safety.watchdog_s` longer than the worst hiccup; `watchdog_action: release` for runs that a dropped link should not abort, `estop` for anything that moves.

- **Prove the stop.** After an emergency stop across the crossing, read the device's state back; the response alone is not the proof. Hardware stops and the device-side watchdog stay on the bench.

- **Log on both sides, with clocks in step.** The crossing's access log plus `mhp log audit` give who asked and what the device did; NTP on every machine lines the timestamps up.

- **Write the firewall rules down.** Lab PCs and agent machines outbound to the gateway, and nothing inbound to the bench. For a proxy: agents to the proxy, proxy to the node ports, nothing else.

- **Discovery is by URL.** mDNS does not cross a firewall; agents find instruments through the gateway's directory, or a proxy URL registered with `mhp lab add`.

## Next

[**Experiment flow**A scientist asks in plain English; the gateway plans, runs the closed loop with their own models and optimizer, and sends the results home.](https://openmhp.com/experiment-flow) [**Lab nodes**The bench PC side: serve a folder of device packages and keep it running.](https://openmhp.com/lab-nodes) [**Add an instrument**Write the package a node serves, or have your agent write it.](https://openmhp.com/add-a-device) [**Architecture**Where the gateway sits among the participants.](https://openmhp.com/architecture) [**Transports, in the spec**stdio, HTTP + SSE, and the relay's once-or-not-at-all rule.](https://openmhp.com/spec/transports)
