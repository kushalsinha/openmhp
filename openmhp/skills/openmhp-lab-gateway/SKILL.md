---
name: openmhp-lab-gateway
description: Be the scientist's go-between with an OpenMHP lab gateway. The scientist speaks plain English; you turn what they say into gateway commands over SSH, and turn everything the gateway sends back into plain English for them. Use when the scientist talks about running an experiment on the lab gateway, a run ID such as R-2611-0042, handing code or data to the lab, the lab's questions or plans, or getting lab results back, and this machine has joined a gateway (`mhp agent` shows it).
license: Apache-2.0
compatibility: Needs a shell with ssh and rsync, and a machine paired with `mhp agent --join` on a gateway that has SSH access turned on. Works in any harness that can run shell commands.
metadata:
  author: openmhp
  version: "0.2"
---

# Being the scientist's go-between with the lab gateway

The scientist talks to you in plain English and should never see a command, a flag, JSON or an
exit code unless they ask for one. The gateway talks in commands and JSON. You stand between them,
in both directions:

```
scientist  --plain English-->  you  --mhp-gw command / rsync-->  gateway
scientist  <--plain English--  you  <--JSON with a "say" line---  gateway
```

## From the scientist to the gateway

1. **Listen for the whole request.** What do they want to find out or make? Which instruments or
   samples? Limits (amounts, temperatures, number of runs, money, deadline)? Their own code to use
   (skills, scripts, an optimizer, a model, data)? Whether someone can be in the lab?
2. **Package it faithfully.** Write their request to a file in their own words, tidied but not
   changed: keep every number, unit, limit and name they gave. Do not add limits or choices they
   did not make; if something important is missing or ambiguous, ask them first, in one short
   question, rather than guess. The gateway's planner will ask about the rest.
3. **Say what you are about to send, in a sentence,** for example: "I'll ask the lab for up to 10
   GC injections to separate ethanol from isopropanol, using your optimizer in gc-loop. OK?" Send it
   once they agree, or straight away if they already told you to go ahead.
4. **Run the commands yourself** (below). Never ask the scientist to type them.

The same goes for everything later: an answer to the lab's question, a change of mind ("cap it at
60 C", "stop after the next cell"), approval. Send their words as they meant them; do not
paraphrase a number or a condition.

## From the gateway to the scientist

Every gateway answer is one JSON object. It has a **`say`** field: the news in plain English, written
by the gateway. Show the scientist the `say` text, or retell it in your own words, without losing
anything in it. Use the rest of the JSON for your own next step (run IDs, digests, `since`).

- **`show_to_scientist`**: show it exactly as given, with the run ID. Never shorten or skip it.
  It is how the lab tells them, for example, that a run may need someone in the lab, or how long
  results are kept.
- **A question from the lab** (`open_questions`, or a `question` event): read it to them as asked,
  say which run it is from, and say plainly when someone has to go to the lab (`needs_lab`).
  Send their reply with `answer`.
- **A plan to approve** (state `waiting_approval`): run `show`, then go through the charter with
  them in plain words: what the run may do, on which instruments, its limits, when it stops, how it
  cleans up, and what the planner adds in `plan_notes`. Offer the files in `preview/` (copy them
  home with rsync). Ask whether to approve it exactly as written. If they want changes, pass them
  on with `message`; a revised plan comes back.
- **Progress, end of run, results**: tell them in a sentence or two. When a run ends, say where the
  results are on their machine and what the run suggests doing next.
- **Refusals** (exit code 3, or `"ok": false`): say what was refused and why, from `say`, and what
  they can do about it. Do not retry the same thing.
- **Waiting** (exit code 2): the gateway has it but has not acted yet. Say so, and check again a
  little later.

| Exit code | Meaning | What you tell the scientist |
|---|---|---|
| 0 | done | the `say` text |
| 2 | waiting for a person, or not acted on yet | what is being waited for |
| 3 | refused | what was refused and why; do not retry it unchanged |
| 4 | not found | a wrong run ID, or a run that is not theirs |

## Is this machine connected?

```bash
mhp agent
```

It names the gateway and, when SSH access is set up, the scientist name this machine works as.
Pairing added a host called `mhp-gateway` to the SSH configuration, so no address, user or key is
ever needed. If the machine is not paired, the scientist needs a code from whoever runs the
gateway (`mhp gateway pair-agent` there), and then you run `mhp agent --join https://<gateway> <code>`.

## The commands

Every gateway command is `ssh mhp-gateway mhp-gw <verb> ...`.

```bash
ssh mhp-gateway mhp-gw help                  # what this gateway can do, and the skill version it expects
ssh mhp-gateway mhp-gw list                  # this scientist's runs
ssh mhp-gateway mhp-gw status R-2611-0042    # one run
```

### Asking the lab for an experiment

```bash
ssh mhp-gateway mhp-gw open                                            # a new run ID
rsync -a ~/projects/electrolyte-bo/ mhp-gateway:runs/R-2611-0042/in/electrolyte-bo/
ssh mhp-gateway mhp-gw request R-2611-0042 --harness claude-code < request.md
ssh mhp-gateway mhp-gw wait R-2611-0042 --timeout 300                  # blocks until there is news
ssh mhp-gateway mhp-gw wait R-2611-0042 --since <since from the last wait> --timeout 300
```

A planner on the gateway works the experiment out. It can look at every instrument and rehearse,
but nothing moves until the scientist approves. Keep calling `wait` with the `since` it gave you;
it returns questions, the plan, its notes and state changes, each with a `say` line.

### Approving, following and changing a run

```bash
ssh mhp-gateway mhp-gw show R-2611-0042                     # the plan (charter), its digest, notes, preview, questions
ssh mhp-gateway mhp-gw approve R-2611-0042 --charter-digest sha256:...
ssh mhp-gateway mhp-gw answer R-2611-0042 q1 "re-make cell 4 in the next batch"
ssh mhp-gateway mhp-gw message R-2611-0042 "stop after 10 more cells"
ssh mhp-gateway mhp-gw stop R-2611-0042
```

- Approve only after the scientist says yes to the plan they were shown, and pass the digest
  exactly as `show` gave it. Never approve on their behalf.
- After `approve`, give them the run ID and the `show_to_scientist` message. They use the run ID
  to ask about the run later ("how is R-2611-0042 doing?").
- A request outside the approved plan cannot be granted by the run; it will say so, and a changed
  plan needs their approval again.

### Handing over skills, scripts and data

Use rsync. The trailing slashes matter: `<folder>/` copies the folder's contents.

```bash
rsync -a ~/projects/electrolyte-bo/ mhp-gateway:runs/R-2611-0042/in/electrolyte-bo/
```

- Files go only into a run's `in/` folder. Anything else is refused.
- Bring only what the run needs: scripts, skills (folders with a SKILL.md), small data, a
  `requirements.txt`. Leave out virtual environments, caches and secrets.
- `scp` works only in its classic mode (`scp -O`). Prefer rsync.

### Bringing results home

```bash
rsync -a mhp-gateway:runs/R-2611-0042/out/ ~/openmhp-runs/R-2611-0042/
ssh mhp-gateway mhp-gw ack R-2611-0042
```

Results come only from a run's `out/` folder, and previews from its `preview/` folder. Check the
files against `manifest.sha256` before `ack`; the gateway deletes its copy after `ack`, and
results nobody fetched are deleted 7 days after the run ended.

## Hearing about runs when no agent is open

A background watcher keeps one connection to the gateway (`mhp-gw watch`), so news arrives even
when the scientist is not talking to you. Offer to install it once, after pairing:

```bash
mhp agent watch --install-service
mhp agent inbox                      # unread news, already in plain English
```

When the scientist asks about the lab or a run, read `mhp agent inbox` first and tell them what is
new. When a run ends, the watcher copies its results into `~/openmhp-runs/<run id>/`, checks them
and acknowledges them for you.

## Keeping this skill current

This skill comes with OpenMHP and is updated with it: a newer OpenMHP replaces this file by itself
the next time an agent or the watcher starts. `mhp-gw help` says which version of this skill the
gateway expects (`skill.version`). If it is newer than the `version` at the top of this file, tell
the scientist in one sentence that the lab gateway is newer than their OpenMHP, and offer to update
it (`npx -y openmhp-cli@latest update`, or `pip install -U "openmhp[all]"`). Until then, run
`mhp-gw help` and use the verbs it lists as it explains them.
