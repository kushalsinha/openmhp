# Closed loop on a lab gateway

A scientist asks a lab gateway, in plain English, to optimise a GC separation using their own optimizer.
The gateway plans it, asks one question, rehearses, gets the charter approved, runs the loop on a simulated
chromatograph, and the results come home, checked against their manifest.

```bash
python examples/gateway_closed_loop/demo.py
```

| File | What it is |
|---|---|
| `request.md` | what the scientist asks for, as they would say it |
| `handover/gc-separation-loop/` | what they hand over: a skill and a small sequential optimizer (`suggest.py`) |
| `scripted_agent.py` | a stand-in for an agent harness, playing the planner and the run agent |
| `demo.py` | the gateway, a lab PC serving the simulated chromatograph, the supervisor, and the scientist's side |
| `playground.py` | the same gateway kept running, with a live feed of everything that reaches it, for a second terminal to talk to |
| `scientist_agent.py` | a real agent (Claude Code) as the scientist's go-between, against the playground |

Everything runs on this machine in a temporary folder. The gateway, the charter checks, the run token,
the supervisor and `mhp-gw` are real. SSH is not used: the scientist's commands go to `mhp-gw` directly,
as the gateway's SSH server would hand them over, and files are copied instead of sent with rsync.

`--harness claude-code` uses Claude Code as the planner and the run agent instead of the scripted
stand-in. It needs `ANTHROPIC_API_KEY`, which the demo stores as the gateway's key for runs, and it
costs money. The instrument is still simulated.

## Watching both sides

`playground.py` keeps a gateway running and prints everything that reaches it: each command and file copy
from the scientist's machine, each run's state changes and questions, the gateway's agent waking and
finishing turns, and every call to the instrument (dry runs and refusals marked). It also writes stand-ins
for `ssh` and `rsync` that reach it as the gateway's SSH server would, so a second terminal can be the
scientist's machine:

```bash
python examples/gateway_closed_loop/playground.py                 # terminal 1: the gateway; prints a bin folder
export PATH="<bin folder>:$PATH"                                   # terminal 2: the scientist's machine
ssh mhp-gateway mhp-gw open
rsync -a examples/gateway_closed_loop/handover/gc-separation-loop/ mhp-gateway:runs/<run id>/in/gc-separation-loop/
ssh mhp-gateway mhp-gw request <run id> < examples/gateway_closed_loop/request.md
ssh mhp-gateway mhp-gw wait <run id> --timeout 60
```

Every answer carries a `say` line, the same news in plain English. The gateway's agents are scripted, so
this costs nothing; `--claude` makes runs that ask for `--harness claude-code` use Claude Code signed in on
the machine instead.

To have a real agent be the scientist's go-between, with only the `openmhp-lab-gateway` skill to go on:

```bash
python examples/gateway_closed_loop/scientist_agent.py <playground folder> --budget 1.00
```

A scripted scientist talks to Claude Code in plain English; the agent opens the run, hands over the
optimizer, relays the lab's question, explains the plan, approves only after a yes, and brings the results
home. The script then checks each of those against the gateway's record. It costs money (about $0.80 with
Sonnet); results land in `~/openmhp-runs/<run id>/`, where the skill puts them.
