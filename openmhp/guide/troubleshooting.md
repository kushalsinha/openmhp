# Troubleshooting

What goes wrong when setting up OpenMHP on the three kinds of machine, and the command that settles each. Start
with the versions: most problems are a machine, or a process, running older code than the instructions assume.

## Which version is running where

```
mhp --version              # this install, and the Python it runs in
mhp gateway --version      # on the gateway: also what its service starts and what the running gateway answers
mhp node --version         # on an instrument PC: also what its service starts
mhp agent --version        # on a scientist's machine: also what the joined gateway runs
```

A long-running process keeps the code it started with. After `pip install -U openmhp`, the gateway and an
instrument PC's service still run the old version until they restart. With npx, the same commands run as
`npx -y openmhp-cli@latest mhp --version`.

## Getting the latest version

- pip: always `pip install -U ...`. Plain `pip install` keeps whatever version is already there.
- npx: always `npx -y openmhp-cli@latest ...`. Plain `npx openmhp-cli` reuses the launcher npx cached the first
  time, however old.
- A company package mirror (Artifactory, Nexus, a devpi proxy) may offer an older OpenMHP than PyPI. If
  `pip install -U openmhp` stays on an old version, ask whoever runs the mirror to add the current `openmhp` with
  its dependencies (pyyaml, zeroconf, pyserial, paho-mqtt). The npx launcher says so when it detects it.
- Two installs on one machine: the npx launcher keeps its own copy in `~/.openmhp/venv`, which is not on PATH. A
  bare `mhp` belongs to a separate pip install; update that one with `pip install -U openmhp`.

## The gateway

### `mhp gateway status` says NOT running, or agents and lab PCs get odd answers

```
mhp gateway restart
```

It stops any `mhp gateway serve` that was started by hand (only one process can hold the gateway's port, and a
copy started before an update keeps serving the old code), restarts the installed service, waits until it
answers, and says which version it runs. If no service is installed:

```
mhp gateway serve --install-service      # runs now and after every reboot
```

Do not also start `mhp gateway serve` in a terminal once the service is installed.

On Linux the service is a systemd user unit, `openmhp-gateway`:

```
systemctl --user status openmhp-gateway
journalctl --user -u openmhp-gateway -n 30      # why it stopped
loginctl enable-linger $USER                    # keep it running when nobody is logged in
```

`cannot listen on <address>:<port>: Address already in use` means another process holds the port, usually an
older `mhp gateway serve`: `mhp gateway restart` stops it.

### The address agents and lab PCs use

The gateway listens on one address and one port: those `mhp gateway status` prints, for example
`https://10.242.190.59:9443/`. Use exactly that, port included. A DNS name or a load balancer in front of it
must lead to that address and port; `https://name` with no port means port 443.

## Adding a scientist's machine

On the gateway, for each scientist:

```
mhp gateway pair-agent alice        # a one-time code, valid an hour; the name is their folder on the gateway
```

On the scientist's machine (`pip install -U openmhp` first, or use npx):

```
mhp agent --join https://<gateway address>:<port> <code>
npx -y openmhp-cli@latest join https://<gateway address>:<port> <code> --name alice     # the npx form
mhp agent status                                                                        # check
```

That is enough to reach the instruments. For a folder on the gateway and experiments in plain English, the
gateway operator also runs `mhp gateway ssh` once (see the `gateway` and `experiment-flow` topics).

| What the join prints | What it means | Do this |
|---|---|---|
| `unknown target 'agent'` / `unrecognized arguments: --join` or `--name` | this machine's OpenMHP is older than 0.10.0 | update it (above); check `mhp --version` |
| `401 ... unknown agent token; the gateway operator issues one with mhp gateway add-agent` | the process answering is an old gateway build | on the gateway: `mhp gateway restart`, then `mhp gateway --version` |
| `the gateway refused the code` (403) | the code expired (an hour) or was already used | a new code: `mhp gateway pair-agent <name>` |
| `cannot reach https://...` | wrong address or port, the gateway is not running, or a firewall | the address from `mhp gateway status`; `mhp gateway restart` |
| certificate fingerprint differs from what `pair-agent` printed | a different server answered | stop; check the address |

## Instrument PCs

```
mhp node --service-status      # installed? running? which version, and the update command
mhp node --check               # packages and ports, without serving
mhp node <devices folder>      # after an update: restarts the service on the new version
```

A lab PC shown offline in `mhp gateway status` reconnects by itself once the gateway answers again.

## Reading this guide

```
mhp guide                      # the topics
mhp guide gateway              # one topic
mhp guide search restart       # every line that mentions a word
mhp guide path                 # the folder, to read the files directly
```
