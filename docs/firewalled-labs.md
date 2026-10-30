# OpenMHP across a lab firewall

*Strategies for relaying instructions to, and fetching telemetry from, instruments that sit on an
isolated network. Written against openmhp 0.9 (SPEC 2026-09-12) on 2026-10-28. Topology in scope:
the agent runs on the same site as the lab, the instruments sit on an instrument VLAN or behind a
host firewall. Off-site and multi-institution topologies are noted where they differ.*

---

## 1. The problem in MHP terms

Three different things cross the firewall, and they carry different risk:

| Flow | What it is in MHP | Direction | Weight |
|---|---|---|---|
| **Commands** | `POST /rpc`: `settings/write`, `actions/invoke`, `jobs/*`, `safety/*`, and the `session/renew` heartbeat that keeps a lease alive | agent → device | Highest. A command that arrives twice, late, or from the wrong session moves hardware. |
| **Telemetry** | `GET /events` (Server-Sent Events: `signals/update`, `jobs/progress`, `jobs/finished`, `safety/*`), plus pulled reads: `signals/read`, `jobs/status`, `mhp_data op=updates` | device → agent | Low on its own. Danger is the agent *acting* on stale or missing telemetry. |
| **Approvals** | `approved: true` on a request, meaning "a person confirmed exactly this" (SPEC §7.2) | agent → device | High. The device trusts the channel's word that a human was asked. |

Two things must never depend on the cross-firewall link:

1. **The stop path.** `safety/estop` sent across the crossing is a request; the stop is proven only
   by reading state back. The device-side watchdog (`safety.watchdog_s`), the hardware e-stop and
   the vendor GUI on the bench PC must all keep working with the link down.
2. **Local operator control.** A person at the bench must be able to take over, pause, or end a run
   without going through the agent's network path.

### What the reference implementation gives you today

Facts the rest of this document rests on (file references are in the openmhp repo):

- **Devices only listen.** `serve_http` (`openmhp/transport.py`) exposes `POST /rpc`, `GET /events`
  and `GET /mhp.json`. `mhp node <dir>` serves every package on consecutive ports from 18900,
  bound to `127.0.0.1` unless `--host` names a LAN address. Before the relay (§F) nothing in MHP
  dialled out to a hub, registered itself, or heartbeated upstream. The fleet (`fleet.py`) and directory (`directory.py`) are pull-only: they connect to a
  URL you give them and ping it. mDNS discovery does not cross a VLAN.
- **No TLS.** The HTTP transport has no certificate code. SPEC §9.1: "There is still no transport
  encryption here: run it on a trusted segment or behind a TLS proxy."
- **One shared bearer token per device or node.** Created automatically on a non-loopback bind
  (`OPENMHP_DEVICE_TOKEN` or `~/.openmhp/device_token`). `GET /mhp.json`, the descriptor, is always
  open. `--no-auth` serves openly on purpose; then requests from off the machine are served but
  **cannot assert `approved`** (transport strips the flag and reports `ignoredApproved`).
- **A token holder is trusted entirely,** "including about which session it is" (SPEC §9.1).
  The session id is whatever the caller puts in `X-MHP-Client`; the device does not issue it
  (SPEC §5.7). Leases, and therefore who may operate a watchdog device, hang on that header.
- **No idempotency.** SPEC §7.6: "servers do not deduplicate requests. Clients MUST NOT retry writes
  or invokes automatically." A lost response must be reconciled by reading state or listing jobs.
- **SSE has no replay.** The client reconnects with backoff, but events emitted during the gap are
  gone. There is no `Last-Event-ID` and no "events since sequence N" call on the device.
- **Unreliable-link safety already exists:** leases with a client heartbeat (`session/renew` every
  `min(ttl, watchdog_s)/3`); `safety.watchdog_s` with `watchdog_action: estop` (default) or
  `release` (drop the lease, keep the work running, report it); `safety/estop` and
  `safety/shutdown` are never blocked by a lease or by queued requests; the run log is a
  sha256-chained JSONL (`mhp log audit`); every device keeps its own record under
  `~/.openmhp/records/<id>/` (not yet readable off-host, SPEC §16).
- **The MQTT adapter is not a transport.** `adapters/mqtt.py` connects *outbound* to a broker, but
  it binds an MQTT-speaking instrument to an MHP driver that is still served over HTTP. Its e-stop
  publishes at QoS 2, which proves the broker got the message, not that the instrument stopped.
- **The MCP bridge over HTTP** (`mhp-mcp --http`) has its own bearer token, an `Origin` allowlist,
  and **no server-initiated requests, so confirm-gated steps are unavailable over it**.

---

## 2. Patterns

```
                     agent subnet                    │ firewall │           instrument VLAN
                                                     │          │
 A  Claude Code ─ mhp-mcp ──TLS 443──▶ [reverse proxy, DMZ] ──▶ mhp node (bench PC)  ×N
                                                     │          │   mhp serve-directory
 B  Claude Code ─ mhp-mcp ◀══ WireGuard / Tailscale / ssh -R ══╡ bench PC dials OUT; no inbound rule
 C  dashboards, partners ◀── MQTT/AMQP broker (TLS) ◀───────── bench PC publishes telemetry (outbound)
 D  shared store ◀── one-way export of run log + events ◀────── control stays with a person
 E  Claude Code ──TLS 443──▶ [proxy] ──▶ mhp-mcp --http inside the VLAN ──▶ mhp node ×N
 F  Claude Code ─ mhp-mcp ─▶ [relay] ◀══ bench node dials out and registers   (does not exist yet)
```

| # | Pattern | Inbound hole into the VLAN | TLS | SSE works | `approved` boundary kept | E-stop ground truth | OpenMHP code needed | Pick when |
|---|---|---|---|---|---|---|---|---|
| A | TLS reverse proxy as the single crossing | One: proxy → node ports | Yes, at the proxy | Yes, with buffering off | Yes, if the proxy is treated as the trust boundary (see §4) | Read-back + device watchdog | None | Default for same-site VLANs |
| B | Overlay network or reverse tunnel | None (bench dials out) | Yes, in the tunnel | Yes | Yes, same as A | Same | None | IT forbids any inbound rule; small number of bench PCs |
| C | Message broker, both sides outbound | None | Yes (8883) | n/a: broker fan-out | **No** | **No** (broker ack only) | A publisher sidecar (small) | Telemetry sharing only; never control |
| D | One-way telemetry export | None | Yes | n/a | n/a | n/a | An exporter (small) | Strictest labs, regulated instruments, partner read access |
| E | MCP bridge inside the VLAN, only `/mcp` exposed | One: proxy → bridge | Yes, at the proxy | n/a (bridge handles it locally) | **Confirm gates unavailable** over bridge-HTTP today | Same as A | None, but loses `approval: confirm` | Labs with no confirm-gated actions, or once elicitation over HTTP exists |
| F | MHP-native outbound relay | None | Yes | Yes (multiplexed) | Yes | Same as A | **Yes, new** (node dial-out, registration, relay) | Off-site agent, partner sites, many labs |

### A. Controlled crossing: a TLS reverse proxy

One host inside the instrument VLAN (or in a DMZ between the two networks) runs nginx. It terminates
TLS, authenticates the agent, and forwards to the bench PCs. The firewall allows exactly two things:
agent subnet → proxy:443, and proxy → bench ports 18900–18939. The device bearer token is **added by
the proxy** and never leaves the VLAN; agents hold an agent token the proxy knows, not the device
token, and the proxy sets `X-MHP-Client` from that identity.

Run `mhp serve-directory` inside the VLAN so agents search one place. The directory manifest must
list the **proxy URLs** of the devices (`https://lab-gw/auto-echem/ob1-2bar/`), not their VLAN
addresses, because the agent's `mhp-mcp` connects to each device target itself after the search. The
directory pings devices at query time, so `state` stays truthful. Zero OpenMHP code; this is the
deployment SPEC §9.1 already assumes. **Implemented** as `mhp gateway` (init, add-node, add-agent,
check): [deploy/nginx/README.md](../deploy/nginx/README.md) is the bench-side guide, and
`tests/test_gateway.py` exercises it end to end.

### B. Overlay network or reverse tunnel

WireGuard or Tailscale between the agent host and each bench PC, or an `ssh -R` reverse forward
from the bench PC to the agent host. The bench PC initiates, so the instrument VLAN needs no
inbound rule at all. MHP configuration is identical to A, except the agent adds devices by their
tunnel address (`mhp lab add http://bench3.tailnet:18921`) because mDNS still stops at the VLAN.
Costs: tunnel software and key management on every bench PC, and the overlay becomes a flat
network, so bind `mhp node` to the tunnel interface only, keep the token on, and treat the overlay
as the trusted segment the spec talks about. Prefer WireGuard/Tailscale over `ssh -R` for anything
that runs unattended; SSH tunnels drop and nobody notices.

### C. Message broker for telemetry

Both the bench PC and the consumers connect outbound to a TLS broker (MQTT on 8883, or AMQP).
A small sidecar on the bench subscribes to the device's `GET /events` on localhost and republishes
`signals/update`, `jobs/*` and `safety/*` as retained topics; dashboards and partners subscribe.
Good for fan-out, retention and partners who should see but never touch. **Do not put control
over a broker:** MHP is request/response with leases and dry runs; a broker acknowledgement says
nothing about whether the instrument acted, there is no channel for `approved`, and the existing
MQTT adapter is for instruments that speak MQTT, not for carrying MHP.

### D. One-way export

The most conservative option: the bench PC pushes the run log, device records and exported result
files to a shared store (object storage, a LIMS drop folder) through a one-way path, and all
control stays with a person at the bench. Fits instruments whose own software owns the audit
trail (Empower, UNICORN) and labs under regulatory review. The agent still analyses and proposes;
a person executes.

### E. Move the bridge inside

Run `mhp-mcp --http` on a machine inside the VLAN and expose only `/mcp` through the proxy. The
lab becomes one endpoint with one token, and devices never need to be reachable from outside.
The catch is in the bridge itself: over HTTP it cannot ask the person anything, so every
`approval: confirm` action is refused. Use it only for a lab with no confirm-gated steps, or once
the bridge supports elicitation over HTTP.

### F. MHP-native outbound relay (implemented: `mhp gateway` + `mhp node --join`)

The bench PC dials out to a gateway over HTTPS, registers its device cards, and serves requests that
arrive by long-poll; events are pushed the same way. Agents reach the devices at the gateway with the
ordinary MHP HTTP shape (`/<node>/<device>/rpc`, `/events`, `/mhp.json`) and search them through
`/directory/`. No inbound rule anywhere, works through corporate proxies, pairing by one-time code
with certificate pinning. Requests are never re-sent (503 offline, 504 no answer). Guide:
[relay.md](relay.md); protocol: SPEC §9.2.

---

## 3. Recommendation

**Primary: Pattern F, the relay**, because it needs no firewall change at any site:
`mhp gateway init && mhp gateway serve` on one reachable machine, `mhp gateway pair` →
`mhp node <dir> --join <url> <code>` once per bench PC, `mhp gateway add-agent` per agent host.
Guide in [relay.md](relay.md).

**Pattern A (nginx in the VLAN)** remains a sound manual alternative where IT allows one inbound rule
and prefers a standard reverse proxy they already operate; the checklist below is written for it and
every item also applies to the relay's gateway.

**Add C or D for anyone who should see telemetry but never control**: a read-only broker feed for
dashboards and partners, or one-way export for regulated instruments.

---

## 4. Hardening checklist for the crossing

Each item names the fact it rests on, so it can be re-checked when OpenMHP changes.

1. **Never retry at the proxy.** MHP operations are not idempotent (SPEC §7.6); a retried
   `actions/invoke` is a second injection, a retried `settings/write` a second move. nginx:
   `proxy_next_upstream off;` and no `proxy_connect_timeout` retries; Caddy: no `lb_try_duration`,
   one upstream per route. On a lost response the agent reads state (`jobs/list`,
   `signals/read`) instead of resending, which is what the client already does.
2. **Let SSE through.** nginx: `proxy_buffering off; proxy_cache off; proxy_read_timeout 3600s;
   proxy_http_version 1.1; proxy_set_header Connection "";` and honour `X-Accel-Buffering: no`.
   The device sends a `: keepalive` every 15 s, so any read timeout above that keeps the stream
   open. Treat events as hints: they are lost during a reconnect, so the agent confirms outcomes
   with `jobs/status` and `mhp_data op=updates`, never from the event stream alone.
3. **Keep the device token inside the VLAN.** The proxy authenticates the agent (a per-agent token the
   proxy maps to a name, as `deploy/nginx` does; mTLS or SSO also work) and adds `Authorization: Bearer <token>` itself. Agents never hold node
   tokens, so a lost laptop does not expose a bench. Put `GET /mhp.json` behind the same
   authentication: it is open by design, and it describes the lab.
4. **Pin the session identity at the proxy.** The device believes `X-MHP-Client` as sent. Have the
   proxy overwrite it with the authenticated identity (the agent's name, certificate CN or SSO subject). Otherwise
   any agent holding access could name another agent's session and take its lease.
5. **Make the proxy the approval boundary.** With a token present, the device trusts the proxy's
   peer entirely, including `approved: true` (`dispatch(..., trusted=True)`). So the proxy must
   only pass `approved` from callers whose harness really elicited a person: today that is Claude
   Code through the stdio `mhp-mcp`, and explicitly not `mhp-mcp --http`. Simplest rule: strip
   `approved` from any caller not on an allowlist of harness identities.
6. **Size leases and watchdogs for the link.** Set `session/acquire` ttl and `safety.watchdog_s`
   longer than the proxy's or tunnel's worst hiccup, and use `watchdog_action: release` on devices
   whose runs outlast any outage (the supported-devices packages already do: an electrolysis or a
   purification stopped by a dropped VPN is itself the damage). Keep `watchdog_action: estop` for
   anything that moves.
7. **Prove the stop.** After `safety/estop` across the crossing, read `ping` state and the
   device's signals back; the response alone is not the proof. Hardware e-stops and vendor GUIs
   stay on the bench; the device-side watchdog covers a dead agent host.
8. **Log on both sides and synchronise clocks.** Proxy access logs plus `mhp log audit` give who
   asked, what the device did, and whether the chain is intact. MHP errors carry a
   device-anchored timestamp; NTP on bench PCs and proxy makes them line up.
9. **Write the firewall rules down:** agent subnet → proxy:443; proxy → bench VLAN 18900–18939;
   bench VLAN → agent subnet: nothing; optionally bench VLAN → broker:8883 outbound for telemetry.
   Nothing else.
10. **Discovery is by URL.** `mhp lab scan` (mDNS plus port probes) does not cross the VLAN;
    register devices with `mhp lab add <proxy url>` or through the in-VLAN directory.

---

## 5. Gaps in OpenMHP this exposes

Ranked by how much they would simplify the picture above; each has a natural place in the spec.

1. **TLS in `serve_http`**, or a normative statement that the HTTP transport is proxy-only.
   SPEC §9.
2. **Device-issued lease tokens.** `session/acquire` returns a secret the caller must present;
   then a token holder is no longer trusted "about which session it is". SPEC §5.7 says this is
   "not in this draft".
3. **Telemetry resume.** `Last-Event-ID` on `GET /events`, and an `events/since {seq}` call on
   the device, so a reconnect does not lose `jobs/finished`. The run log already has sequence
   numbers (`mhp_data op=updates since=`); the device stream does not. SPEC §3.5, §8.
4. **Request idempotency tokens**, so a proxy or flaky link can be allowed one safe retry. SPEC §16.
5. **Outbound relay and node self-registration** (Pattern F): `mhp node --relay wss://...`, a
   `directory/register` primitive, relay-side multiplexing. New SPEC §9.2.
6. **Reading a device's record off-host**, with a rule about who may read who did what. SPEC §16.
7. **Elicitation over the bridge's HTTP transport**, so Pattern E can carry confirm gates.

Until 1–4 land, Pattern A with the §4 checklist is the supported way to cross a firewall, and
Pattern B is its no-inbound variant.
