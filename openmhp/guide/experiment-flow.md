<!-- generated from https://openmhp.com/experiment-flow by scripts/build_guide.py; edit the website, not this file -->

# Experiment flow

A scientist asks for an experiment in plain English, from their own agent, on their own laptop. The lab gateway plans it with them, shows them what it will do and what the data will look like, and once they approve, runs the whole closed loop on the lab's instruments: one agent session that thinks like their colleague, using their own models and optimizer to choose each next experiment. The results come home to their machine, checked.

## The story

Alice is an analytical chemist. Her solvent mix of acetone, ethanol, isopropanol and toluene needs a GC method: ethanol and isopropanol keep co-eluting, and she wants the shortest run that still separates every neighbouring peak. She has the pieces of a good answer already. A **mechanistic model** of the separation predicts retention and plate height from carrier flow and oven ramp, and a **Bayesian optimization skill** picks the next condition from the results so far. What she does not have is time to stand at the chromatograph.

So she tells her agent, in her own words:

> "I need GC conditions that separate ethanol from isopropanol, resolution at least 1.5 between every neighbouring peak, with the shortest run time you can get. The lab may vary the carrier flow from 0.5 to 5 mL/min and the oven ramp from 2 to 40 °C/min; keep injections at 1 µL and use at most 10. Use my retention model to rule out conditions that cannot work, and my BO skill to pick each next one. Can you get the lab gateway to run this?"

That is the last thing she has to phrase carefully. Everything after it is a conversation: her agent asks the gateway, the gateway's planner asks her what only she can say, she reads the plan, and she says yes.

## Who is involved

[Figure: Three machines. On the left, Alice's laptop: Alice talks in plain English to her agent, which has the openmhp-lab-gateway skill. The agent reaches the gateway over SSH with mhp-gw commands, and copies her model, BO skill and data into her run folder with rsync. In the middle, the lab gateway: Alice's folder with the run, the planner, and the run's one agent session with the mhp tools and her skills, all watched by the supervisor; every instrument call passes the charter check. On the right, behind the lab firewall, the lab PC runs mhp node and serves the gas chromatograph; it dials out to the gateway's relay. Results go back from the run folder to Alice's laptop.]

*Alice only ever talks to her own agent. Her agent only ever runs plain commands on the gateway. The gateway's agent only ever reaches the chromatograph through mhp, and every call it makes is checked against what Alice approved.*

- **Alice's laptop** has her agent (Claude Code, Codex, or any harness that can run a shell command) and the `openmhp-lab-gateway` skill, installed when the laptop paired with the gateway. The skill makes the agent her go-between: it turns what she says into gateway commands, and everything the gateway answers back into plain English. Every answer carries a `say` line written by the gateway, so she hears the same thing whichever agent she uses.

- **The lab gateway** keeps one folder per scientist, reached over SSH, where the only thing a key can do is run `mhp-gw` and copy files into a run's `in/` folder and out of its `preview/` and `out/`. Its admin installed the agent harness there and signed it in; for each run the gateway starts a new session of it, as installed.

- **The lab PC** next to the chromatograph runs `mhp node`, exactly as on the [gateway and relay](https://openmhp.com/gateway) page: it dials out, takes requests, and enforces the instrument's own limits, interlocks and e-stop beside the hardware.

## How the experiment flows

[Figure: A timeline in three lanes: Alice and her agent, the gateway, and the chromatograph. 1, ask: Alice's request goes to the gateway with her model and BO skill. 2, plan: the planner reads them, rehearses an injection as a dry run, and asks Alice what only she can answer. 3, propose: a charter in plain English and a preview of the data. 4, approve: Alice says yes; the gateway leases the chromatograph for the run and gives her the run ID. 5, the loop: the run's session starts an injection; the chromatograph runs it; the finished job wakes the session; it updates her model with the result, asks her BO skill for the next condition, and starts the next injection, until a stop condition holds. Every call passes the charter check. 6, finish: the results go to out/ with a manifest; Alice's machine brings them home, checks them and acknowledges; the gateway deletes its copy.]

*Nothing moves on the instrument before step 4. From step 5 on, the run's session works on its own, inside the charter, and comes back to Alice only when it needs her.*

1. **Ask.** Alice's agent opens a run (`mhp-gw open` gives it an ID), copies her retention model, her BO skill and a `requirements.txt` into the run's `in/` folder with rsync, and sends her request as she wrote it.

2. **Plan.** A planner session on the gateway reads the request and her files, finds the chromatograph, and rehearses an injection as a dry run. It can look at every instrument and rehearse anything, but nothing it sends moves one. It asks Alice, through her agent, what only she can answer: is the sample exactly those four, may it use 10 µL in all, does anyone need to be in the lab.

3. **Propose.** It writes the charter, the plan in a form code can enforce, and a preview of the data she will get: the same files, filled with values her model predicts. Her agent reads her the charter in plain words and shows her the preview.

4. **Approve.** Alice says yes. Her agent approves that exact charter by its digest, never another. The gateway leases every instrument the run needs, all together, and gives her the run ID, with a message to keep an eye on this conversation: physical experiments get stuck, and a question may need someone in the lab.

5. **The loop.** The run's session starts an injection and goes quiet. When the chromatograph finishes, the job's end wakes it. It fits her retention model to the new chromatogram, asks her BO skill for the next condition, checks it against the model, and starts the next injection. It keeps a notebook and reports progress as it goes. When the BO skill finds nothing faster that still resolves every peak, or the budget is spent, it cleans up as the charter says and finishes.

6. **Results home.** Everything it produced goes to the run's `out/` folder with a checksum manifest. Alice's machine copies it home, checks every file, and acknowledges; the gateway then deletes its copy. Results nobody fetches are deleted 7 days after the run ended.

## One session, thinking between experiments

The run's agent is **one session for the whole run**, not a script and not a new conversation per injection. It is started when Alice approves and kept open until the run ends, and every piece of news reaches it as a message in the same conversation: a job finished, a background script ended, Alice answered or changed her mind, a scheduled check came due. Between messages it simply waits.

- **Her tools stay with it.** Her skills are installed in the session, her scripts run in a Python environment built from her `requirements.txt`, and the mhp tools (`mhp_find`, `mhp_read`, `mhp_invoke`, `mhp_job`, `mhp_run` ...) stay up for the whole run, so a fixed sequence can run in the background while it thinks.

- **It does more than run experiments.** Between injections it can read the literature on alcohol separations, refit and question the mechanistic model, and decide that the next experiment is a different one than the optimizer suggested, as long as it is inside the charter.

- **It survives hiccups.** If the session's process dies, the next message starts it again on the same conversation, with its notebook and everything it has learned. If the gateway itself restarts, the run is marked `interrupted`: its instruments were released and their watchdogs acted, so nothing carries on unwatched. Alice resumes it, and its agent checks every instrument and its notebook first, or she stops it.

## Where a run is, and what Alice can do

A run is always in one of these states. Every answer from `mhp-gw` about a run says which, who it is waiting on, and the exact commands that make sense now, each with what it does, so Alice's agent never has to guess the next step.

| State | Waiting on | What she can do |
|---|---|---|
| `open` | Alice | hand over files, then `request`; or `stop` it unused |
| `planning` | the gateway | `wait` for the planner's questions and plan; `message` it; `stop` |
| `waiting_approval` | Alice | `show` the plan, then `approve` it or `message` changes; or `stop` |
| `queued` | the gateway | `wait`: it starts when its instruments are free; a `message` is held for the agent |
| `running` | the gateway | `wait` for news, `message` the agent, `stop` (the agent cleans up first) |
| `waiting_scientist` | Alice | `answer` its question; the run goes on |
| `interrupted` | Alice | the gateway restarted mid-run: `resume` it or `stop` it |
| `finished`, `stopped`, `failed` | nobody | bring the results home, then `ack`; for `failed`, `status` says why it could not run |

A run ends once: a `finish` and a `stop` that race each other cannot both happen. A request the gateway is still acting on when `mhp-gw` stops waiting is answered `pending`, and its answer comes with her next command for that run.

## What the gateway enforces

The charter is what Alice approved, and the gateway, not the agent, enforces it on every instrument call, before the lab PC sees it:

- **Only the run's instruments**, under the run's own identity (`alice/run-R-2611-0001`), so leases and records name the person and the run.

- **Only the actions the plan needs, inside her ranges**, including ranges inside structured parameters: "ramp_c_min in each oven_program entry 2 to 40" checks every step of every oven program.

- **Budgets and consumables**: at most 10 injections and 10 µL of sample. A dry run counts for nothing.

- **Things that always go back to her**, such as a bake-out or a reset after an e-stop, and approvals the agent can never give itself.

And it watches the session. A question the agent cannot settle goes to Alice through her agent, marked when someone has to go to the lab. A session that stops with nothing running and nothing asked is reminded once, and then Alice is asked. Instrument news waits while the run is waiting for her answer.

> Alice never types a command. Her agent tells her, in plain English, what the lab asks, what it plans, what it is doing and what it found; the gateway decides what the run may do, and the lab PC beside the chromatograph decides what the chromatograph may do.

## What becomes possible

Once the lab answers in plain English and runs your own methods for you, the way you plan experiments can change. A few of the things that are now one sentence away:

- **Bring your own brain.** Hand over whatever makes your work yours: a Bayesian optimization routine, a mechanistic or kinetic model, an analysis script, a skill that says how you judge a result, last month's data. The run's session installs them and uses them on every iteration, so the lab optimizes the way you would.

- **Closed loops overnight and over the weekend.** Ask on Friday afternoon; the session keeps going between experiments, reading, modelling and choosing, and reaches you only when it needs a decision or a person in the lab. You answer from wherever your agent is.

- **A colleague between experiments, not a script.** The session can search the literature for a better starting point, question your model when the data disagree with it, and propose an experiment your optimizer would not have, as long as it stays inside what you approved.

- **Experiments across instruments.** A run can name several instruments, say a liquid handler, a potentiostat and a chromatograph. They are leased together, all or none, so a run never holds half a workcell, and it waits its turn when they are busy.

- **See it before it moves.** Every plan is rehearsed as a dry run and comes with a preview of the data, so you can change the plan in words before a single sample is used.

- **Limits you can read, enforced on every call.** Ranges, including inside an oven program or a pipetting step; how many experiments; how much of each consumable; a deadline; steps that always come back to you; routine steps you approve once in advance.

- **Change your mind mid-run.** "Stop after the next three", "keep it at 30 °C overnight": tell your agent, and the run hears it. Anything outside the approved plan comes back to you as a revised plan to approve.

- **One lab, many scientists.** Each scientist has their own folder, their own runs and their own key; runs that need the same instrument queue for it, and nobody can see or touch another's work.

- **Results that come home on their own.** A small watcher on your machine hears when a run ends, brings the data, notebook and report home, checks them, and tells you what the run suggests doing next.

## Try it

The whole story runs on one machine, in a temporary folder, from the [closed-loop example](https://github.com/kushalsinha/openmhp/tree/main/examples/gateway_closed_loop):

```
python examples/gateway_closed_loop/demo.py                        # a scripted agent
python examples/gateway_closed_loop/demo.py --harness claude-code  # Claude Code as planner and run agent

python examples/gateway_closed_loop/playground.py                  # a gateway with a live feed, for a second terminal
export PATH="<the bin folder it prints>:$PATH"                      # ... which is then Alice's machine
ssh mhp-gateway mhp-gw open
```

## On a real gateway

The operator sets up the gateway with experiments turned on (`mhp gateway ssh` and the agent harness installed there), then pairs each scientist; every step is on the [quickstart](https://openmhp.com/quickstart#gateway). The one command for a scientist, on the gateway:

```
mhp gateway pair-agent alice
```

Alice then joins once from her laptop with the code, as on the [quickstart](https://openmhp.com/quickstart#scientist):

```
mhp agent --join https://gw.office:8443 <code>
```

From then on she simply asks her agent; the `openmhp-lab-gateway` skill runs the commands below for her.

## The same, by hand

Every command runs over SSH on the gateway, in her own folder. In order:

1. Open a run. It answers with the run's ID:

```
ssh mhp-gateway mhp-gw open
```

2. Hand over your skills, scripts and data:

```
rsync -a ./my-run/ mhp-gateway:runs/<run id>/in/
```

3. Say what you need in plain English; a planner starts:

```
ssh mhp-gateway mhp-gw request <run id> < request.md
```

4. Wait for its questions and its plan:

```
ssh mhp-gateway mhp-gw wait <run id>
```

5. Read the plan (its charter) and the preview of the data:

```
ssh mhp-gateway mhp-gw show <run id>
```

6. Approve exactly that plan, using the digest `show` printed:

```
ssh mhp-gateway mhp-gw approve <run id> --charter-digest <digest>
```

7. Bring the results home when it ends:

```
rsync -a mhp-gateway:runs/<run id>/out/ ./results/
```

8. After checking them, let the gateway delete its copy:

```
ssh mhp-gateway mhp-gw ack <run id>
```

While it runs, the answer to every command lists what makes sense now: `answer <run id> <question id> <text>` a question, `message <run id> <text>` the agent, `stop <run id>`, or `resume <run id>` after a gateway restart. To see all her runs:

```
ssh mhp-gateway mhp-gw list
```

To hear about her runs even when no agent is open:

```
mhp agent watch --install-service
```

## Next

[**Gateway and relay**How bench PCs dial out and agents reach every instrument through one gateway.](https://openmhp.com/gateway) [**Lab nodes**The bench PC side: serve a folder of device packages and keep it running.](https://openmhp.com/lab-nodes) [**Recipes**The reusable scripts a run's session can call with `mhp_run`.](https://openmhp.com/recipes) [**Architecture**Where the gateway, the nodes and the agents sit.](https://openmhp.com/architecture)
