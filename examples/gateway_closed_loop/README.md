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

Everything runs on this machine in a temporary folder. The gateway, the charter checks, the run token,
the supervisor and `mhp-gw` are real. SSH is not used: the scientist's commands go to `mhp-gw` directly,
as the gateway's SSH server would hand them over, and files are copied instead of sent with rsync.

`--harness claude-code` uses Claude Code as the planner and the run agent instead of the scripted
stand-in. It needs `ANTHROPIC_API_KEY`, which the demo stores as the gateway's key for runs, and it
costs money. The instrument is still simulated.
