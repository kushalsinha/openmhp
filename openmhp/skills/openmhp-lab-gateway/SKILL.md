---
name: openmhp-lab-gateway
description: Work with an OpenMHP lab gateway on the scientist's behalf over SSH - open runs, hand over skills, scripts and data with rsync, check run status, bring results home. Use when the scientist talks about running an experiment on the lab gateway, a run ID such as R-2611-0042, handing code or data to the lab, or getting lab results back, and this machine has joined a gateway (`mhp agent` shows it).
license: Apache-2.0
compatibility: Needs a shell with ssh and rsync, and a machine paired with `mhp agent --join` on a gateway that has SSH access turned on. Works in any harness that can run shell commands.
metadata:
  author: openmhp
  version: "0.1"
---

# Working with the lab gateway

The scientist talks to you in plain English. You talk to the gateway in plain commands. Never ask
the scientist to type these commands; run them yourself and tell them what happened in plain words.

## Is this machine connected?

```bash
mhp agent
```

It names the gateway and, when SSH access is set up, the scientist name this machine works as.
Pairing added a host called `mhp-gateway` to the SSH configuration, so no address, user or key is
ever needed on the command line. If `mhp agent` says the machine is not paired, the scientist needs
a code from whoever runs the gateway (`mhp gateway pair-agent` there), and then you run
`mhp agent --join https://<gateway> <code>`.

## Talking to the gateway

Every gateway command is `ssh mhp-gateway mhp-gw <verb> ...`. Each answers one JSON object on
stdout and an exit code:

| Exit code | Meaning |
|---|---|
| 0 | done |
| 2 | waiting for a person: tell the scientist what is needed |
| 3 | refused: the `error` says why; do not retry the same thing |
| 4 | not found: a wrong run ID, or a run that is not this scientist's |

```bash
ssh mhp-gateway mhp-gw help                  # what this gateway can do; newer gateways list more verbs
ssh mhp-gateway mhp-gw open                  # a new run; answers its ID and where to copy files
ssh mhp-gateway mhp-gw list                  # this scientist's runs
ssh mhp-gateway mhp-gw status R-2611-0042    # one run
```

Run `help` first when you are unsure. If it lists verbs this skill does not describe, use them as
`help` explains.

## Handing over skills, scripts and data

Use rsync. The trailing slashes matter: `<folder>/` copies the folder's contents.

```bash
rsync -a ~/projects/electrolyte-bo/ mhp-gateway:runs/R-2611-0042/in/electrolyte-bo/
```

- Files go only into a run's `in/` folder. Anything else is refused.
- Bring only what the run needs: scripts, skills (folders with a SKILL.md), small data, a
  `requirements.txt`. Leave out virtual environments, caches and secrets.
- `scp` works only in its classic mode (`scp -O`). Prefer rsync.

## Bringing results home

```bash
rsync -a mhp-gateway:runs/R-2611-0042/out/ ~/openmhp-runs/R-2611-0042/
```

Results come only from a run's `out/` folder, and previews from its `preview/` folder.

## Messages from the gateway

When an answer carries `show_to_scientist`, show that text to the scientist as given, with the
run ID. It is how the lab tells them, for example, that a physical experiment may need them in the
lab, or how long results are kept. Do not shorten it or leave it out.

## What to tell the scientist

- The run ID, whenever one is created or mentioned. They use it to ask about the run later.
- What was copied, in a sentence, and anything that was refused, with the reason.
- The state of a run in plain words. Do not paste JSON unless they ask for it.
