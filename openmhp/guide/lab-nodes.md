<!-- generated from https://openmhp.com/lab-nodes by scripts/build_guide.py; edit the website, not this file -->

# Lab nodes

The two-computer setup most labs already have: instruments wired to a bench PC, an agent on your laptop. One command on each, and they find each other over the network. When the lab network is closed to the outside, the bench PC dials out instead, and nothing is opened.

| Machine | What you run | What it does |
|---|---|---|
| **The computer wired to your instruments** | `pip install -U "openmhp[node]"` `mhp node add <package>` | serves each instrument over HTTP, advertises them on the LAN, keeps doing it after a reboot |
| **Your laptop** | `npx -y openmhp-cli@latest setup` | the agent harness and the MCP bridge; finds nodes and operates what they serve |
| **A gateway on the company network** (only when the lab network is closed) | `pip install -U openmhp` `mhp gateway init` / `serve` | bench PCs dial out to it; agents reach every instrument through it. See [gateway and relay](https://openmhp.com/gateway) |

> They can be the same machine. If your agent runs on the bench PC itself, install both and skip the network entirely — nothing else about the setup changes.

## On the instrument computer

This is the machine with the USB cable, the vendor software, or the network link to the instrument. It never needs an agent on it. The person at the bench knows which instrument it is, so they name it, and the package brings the vendor route with it (a serial protocol, a Web API, a COM SDK); the node only needs to know which folder the package is in:

```
pip install -U "openmhp[node]"                      # the node extra adds serial, MQTT and mDNS
mhp node add                                    # lists the ready-made packages
mhp node add waters-empower-hplc                # fetches it, asks the questions, leaves it running
```

That second command does the rest. It installs the vendor client, then asks only what a person knows, with an example beside each question: the Empower address, the user (the password goes to the operating system's keyring, never into a file), the project, and the node and system picked from the list the server returns. It writes the settings file, checks them against the instrument (`Empower reachable, Arc_HPLC_1 idle`), asks for the gateway pairing line if your lab has one, and installs the background service or serves in that window. Limits and timings keep their defaults; the file stays plain JSON.

```
A few questions about waters-empower-hplc. ? explains.
  Empower Web API address, from your Empower administrator   e.g. https://empower-api.lab.local:3076
  > https://emp01.acme.local:3076
  Empower user the agent logs in as   e.g. svc_openmhp
  > svc_openmhp
  Password for svc_openmhp (goes to the OS keyring, never into a file; Enter to skip)
  >
  Chromatographic system on that node
    (1) Arc_HPLC_1   (2) Arc_HPLC_2
  > 1
saved ~/.openmhp/devices/waters-empower-hplc/config.json
checking ...
  waters-empower-hplc is ready: Empower at https://emp01.acme.local:3076 answers; Arc_HPLC_1 is idle

Does your lab have an OpenMHP gateway? Paste the line from `mhp gateway pair` there (address and code), or Enter to skip
  > https://gw.acme.local:8443 ab12-cd34
paired with https://gw.acme.local:8443 as 'hplc-pc-3'
Run in the background from now on, also after reboots? [Y/n] > y
installed; running now, and at every login. Agents can find this PC's instruments through the gateway now.
```

`mhp node setup waters-empower-hplc` asks the same questions again when something changes. `--yes` with `--set key=value` runs it with no questions for scripted installs, and `--from` a copied folder or .tar.gz takes the package from there on a PC with no internet; your own package is just a folder you drop in. On a PC that has Node rather than a Python you want to manage, the launcher does the same, in its own runtime under `~/.openmhp`:

```
npx -y openmhp-cli@latest node add                         # lists the ready-made packages
npx -y openmhp-cli@latest node add waters-empower-hplc     # the same questions as above
```

For a folder that already holds packages, `npx -y openmhp-cli@latest node` asks which folder and which port to start counting from (default 18900), then installs the background service and starts it:

```
[openmhp] found 3 package(s): balance-02, hotplate-01, pump-03
  wrote /home/lab/.config/systemd/user/openmhp-node.service
  systemctl --user daemon-reload: ok
  systemctl --user enable --now openmhp-node.service: ok
installed. running now, and at every login.
```

From then on the machine answers on its own. Two commands manage it:

```
mhp node --service-status      # installed? running?   (npx -y openmhp-cli@latest node --service-status)
mhp node --uninstall-service   # remove the service
```

The service is a systemd `--user` unit on Linux, a LaunchAgent on macOS, and a Startup-folder entry on Windows. On Windows that means it starts once someone logs in, not before; on a headless Linux bench PC where nobody stays logged in, also run `loginctl enable-linger $USER` so the unit survives logout.

## One computer, several instruments

Common case: a USB hub with a hotplate, a balance and a syringe pump on it. **One node process serves all of them** — you do not run one per instrument. What the node needs is one [device package](https://openmhp.com/add-a-device) per instrument in that folder, because it serves packages, not USB ports. It does not scan the bus and guess what is plugged in; each package says which port its instrument is on, along with its limits and how to stop it.

```
~/.openmhp/devices/
├── balance-02/      DEVICE.md + descriptor.yaml  (serial.port: /dev/ttyUSB1)
├── hotplate-01/     DEVICE.md + descriptor.yaml  (serial.port: /dev/ttyUSB0)
└── pump-03/         DEVICE.md + descriptor.yaml  (serial.port: /dev/ttyUSB2)
```

Each gets its own port, counting up from the base, and each is advertised separately, so they arrive in a scan as three instruments rather than one computer:

| Package folder | Serial port | Served at |
|---|---|---|
| `balance-02` | `/dev/ttyUSB1` | `http://bench-pc:18900` |
| `hotplate-01` | `/dev/ttyUSB0` | `http://bench-pc:18901` |
| `pump-03` | `/dev/ttyUSB2` | `http://bench-pc:18902` |

Ports follow the folder names alphabetically, not the order things are plugged in — which is why the balance on `ttyUSB1` is first. One consequence worth knowing: adding a package whose name sorts earlier shifts the ones after it by a port. Discovery re-announces either way, so a fresh `scan` is always correct, but an entry you added by hand to your lab may need adding again.

### Keep the port names stable

On Linux, `/dev/ttyUSB0` is assigned in the order devices appear, so two instruments on one hub can swap after a reboot — and a driver that opens the wrong one will happily send a hotplate's command to a pump. Use the stable path instead:

```
serial:
  port: /dev/serial/by-id/usb-FTDI_FT232R_A50285BI-if00-port0
  baud: 9600
```

Run `ls /dev/serial/by-id/` with the instrument plugged in to find its name. On Windows the COM number is remembered per adapter, so `COM3` generally stays with the same instrument; confirm in Device Manager.

## On your laptop

```
npx -y openmhp-cli@latest setup
```

Then open your agent and say *"find the instruments on my network"*, or do it from the shell:

```
npx -y openmhp-cli@latest scan
```

```
[
  { "target": "http://10.0.0.41:18900", "id": "balance-02", "class": "balance", "state": "idle" },
  { "target": "http://10.0.0.41:18901", "id": "hotplate-01", "class": "hotplate", "state": "idle" },
  { "target": "http://10.0.0.41:18902", "id": "pump-03", "class": "pump", "state": "idle" }
]
```

Add the ones you want, and tell the lab where they stand, since a package cannot know that:

```
npx -y openmhp-cli@latest add http://10.0.0.41:18901 --location "bay 3, fume hood 2"
```

From then on they are in `mhp_find` results for every agent pointed at that bridge, with their owner's operating instructions and safety envelope attached.

## When scan finds nothing

`scan` works two ways at once: it listens for mDNS adverts (`_mhp._tcp`) and probes ports 18900 to 18939 on localhost. Across machines it is the mDNS half that does the work, and multicast is the part most likely to be blocked — by a corporate network, a guest VLAN, or the two machines simply being on different subnets. Name the host directly and it probes that instead:

```
npx -y openmhp-cli@latest scan 10.0.0.41              # or bench-pc.local
npx -y openmhp-cli@latest add http://10.0.0.41:18901  # or skip scanning; the address is enough
```

Other things worth checking, in order: the node is running (`mhp node --service-status` on the bench PC), it was started with `--host` set to the bench PC's address (a node listens on `127.0.0.1` only until you say otherwise), the firewall allows inbound on those ports, and the instruments sit inside 18900–18939 if you want the plain probe to find them — a base port outside that range still works, you just have to name the address yourself.

Serving the network directly is protected by a token. With `--host` set, the node generates one the first time it starts (`~/.openmhp/device_token`) and requires `Authorization: Bearer <token>` on `/rpc` and `/events`. Copy it to the machine running the bridge (`export OPENMHP_DEVICE_TOKEN=...`); discovery stays open, so `scan` still finds the devices. `--no-auth` serves the network without one, and callers from other machines can then no longer confirm approval-gated operations.

If the answer to the firewall question is "IT will not open it", stop here and use the relay below. It is built for exactly that case.

## Behind the lab firewall

In most companies the instrument network is one nothing outside may enter, and IT will not add a rule for a lab PC. OpenMHP does not need one: the bench PC dials **out** over HTTPS to a **gateway** on the company network and takes its work from there, and your agent talks to the gateway. `mhp node add` asks for the pairing line; a PC that already serves packages joins once:

```
mhp node --join https://gw.office:8443 ab12-cd34
```

How it works, how to set up the three machines, and what the relay guarantees are on their own page: [gateway and relay](https://openmhp.com/gateway).

## Updating an instrument PC

Nothing updates itself, so a qualified instrument PC changes only when someone runs the update on that PC. A node says when it is behind, in its log and in `mhp node --service-status`, and the gateway's `mhp gateway status` lists every lab PC that is behind, with the command to run there. A lab PC with no internet hears of a release from its gateway.

```
npx -y openmhp-cli@latest node <devices folder>                                 # set up with npx; restarts the service on the new version
pip install -U "openmhp[node]" && mhp node <devices folder> --install-service   # set up with pip
```

Every ready-made package ships inside OpenMHP, so `mhp node add` needs no download and installs the version tested with the OpenMHP on that PC; `pip install -U openmhp` brings the newer packages and the longer list. A package added to the repository after your release is taken with `mhp node add <name> --from github:kushalsinha/openmhp/supported-devices/<name>`. Set `OPENMHP_NO_UPDATE_CHECK=1` to turn the check off.

## Next

[**Add an instrument**Write the package a node serves, or have your agent write it.](https://openmhp.com/add-a-device) [**Architecture**What a node actually serves, and what it does not.](https://openmhp.com/architecture) [**Instruments supported**Which route fits the hardware you have.](https://openmhp.com/instruments) [**Adapters**Instruments already on OPC UA, ROS 2, SiLA 2, MADSci, PyLabRobot or MQTT.](https://openmhp.com/adapters) [**Gateway and relay**When the lab network is closed: dial out, nothing opened inbound.](https://openmhp.com/gateway)
