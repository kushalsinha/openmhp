"""OpenMHP's state machines, declared once.

Each machine lists its states, the moves between them, and, for the person and the agent, what can be done
next from each state. The code that moves a machine checks the move here before it does anything else, and
every answer that reports a state carries its next steps, so nobody has to infer them.

    RUN   an experiment run on a lab gateway (supervisor.py moves it; mhp-gw and gw_words report it)
    SETUP a machine's parts as `mhp status` reports them (install, gateway link, skills, service, gateway)
"""
from __future__ import annotations

# ---- a run on the lab gateway ------------------------------------------------------------------------------
#   open -> planning <-> waiting_approval -> queued -> running <-> waiting_scientist -> finished
#                                                   ^      |                            stopped
#                                    resume ------- interrupted (the gateway restarted)  failed (could not run)
RUN_TRANSITIONS: dict[str, set[str]] = {
    "open": {"planning", "waiting_approval", "stopped", "failed"},
    "planning": {"waiting_approval", "stopped", "failed"},
    "waiting_approval": {"planning", "queued", "stopped"},
    "queued": {"running", "stopped", "failed"},
    "running": {"waiting_scientist", "finished", "stopped", "failed", "interrupted"},
    "waiting_scientist": {"running", "finished", "stopped", "failed", "interrupted"},
    "interrupted": {"queued", "stopped"},
    "finished": set(), "stopped": set(), "failed": set(),
}
RUN_STATES = tuple(RUN_TRANSITIONS)
RUN_ENDED = frozenset({"finished", "stopped", "failed"})
RUN_LIVE = frozenset({"queued", "running", "waiting_scientist"})   # holds instruments, or is about to

# Who the run is waiting on in each state: the scientist, the gateway (its planner, agent or instruments), or
# nobody (it has ended).
RUN_WAITING_ON = {
    "open": "scientist", "planning": "gateway", "waiting_approval": "scientist", "queued": "gateway",
    "running": "gateway", "waiting_scientist": "scientist", "interrupted": "scientist",
    "finished": "nobody", "stopped": "nobody", "failed": "nobody",
}

# The scientist's next steps from each state: (mhp-gw command, what it does, in plain words). Placeholders in
# <angle brackets> are filled by whoever shows them; {run} is the run id.
RUN_NEXT: dict[str, list[tuple[str, str]]] = {
    "open": [("rsync -a <folder>/ mhp-gateway:runs/{run}/in/", "hand over your files (skills, scripts, data)"),
             ("request {run} < request.md", "say what you need, in plain English; a planner starts"),
             ("stop {run}", "close this run without starting it")],
    "planning": [("wait {run}", "wait for the planner's questions and its plan"),
                 ("message {run} <text>", "tell the planner something"),
                 ("stop {run}", "stop planning")],
    "waiting_approval": [("show {run}", "read the plan (its charter) and the preview of the data"),
                         ("approve {run} --charter-digest <digest from show>", "approve exactly that plan; the run starts"),
                         ("message {run} <text>", "ask for changes; the planner revises the plan"),
                         ("stop {run}", "do not run it")],
    "queued": [("wait {run}", "wait for its instruments to come free; it starts by itself"),
               ("message {run} <text>", "leave a note for the agent; it reads it when the run starts"),
               ("stop {run}", "cancel it before it starts")],
    "running": [("wait {run}", "wait for news: a question, progress, the end"),
                ("message {run} <text>", "tell the agent something"),
                ("stop {run}", "stop now; the agent cleans up as the plan says")],
    "waiting_scientist": [("answer {run} <question id> <text>", "answer its question; the run goes on"),
                          ("message {run} <text>", "tell the agent something else"),
                          ("stop {run}", "stop now; the agent cleans up as the plan says")],
    "interrupted": [("resume {run}", "carry on: it takes its instruments again, and its agent checks the bench first"),
                    ("stop {run}", "end it here; whatever results it had come home")],
    "finished": [("rsync -a mhp-gateway:runs/{run}/out/ <here>/", "bring the results home"),
                 ("ack {run}", "after checking them: the gateway deletes its copy")],
    "stopped": [("rsync -a mhp-gateway:runs/{run}/out/ <here>/", "bring whatever results it had home"),
                ("ack {run}", "after checking them: the gateway deletes its copy")],
    "failed": [("status {run}", "read why it could not run"),
               ("rsync -a mhp-gateway:runs/{run}/out/ <here>/", "bring home anything it produced"),
               ("ack {run}", "after checking them: the gateway deletes its copy")],
}


def run_next(meta: dict) -> list[dict]:
    """The scientist's next steps for one run, as {command, does}: open questions first, then the state's own."""
    rid, state = meta.get("id", "<run>"), meta.get("state", "")
    steps = [{"command": f"answer {rid} {qid} <text>", "does": "answer question " + qid}
             for qid in (meta.get("open_questions") or {}) if state not in RUN_ENDED]
    if state in RUN_ENDED and (meta.get("acked") or meta.get("purged")):
        return []                                            # results home or gone: nothing left to do
    for cmd, does in RUN_NEXT.get(state, []):
        if cmd.startswith("answer ") and steps:
            continue                                         # the questions above already say how
        steps.append({"command": cmd.format(run=rid), "does": does})
    return steps


def check_run_move(run_id: str, current: str, to: str) -> None:
    """Refuse a move the run's machine does not have, in words that say what can be done instead."""
    if to not in RUN_TRANSITIONS.get(current, set()):
        nxt = ", ".join(c.split()[0] for c, _ in RUN_NEXT.get(current, [])) or "nothing: it has ended"
        raise ValueError(f"run {run_id} is {current}; it cannot become {to} from there (what it can do now: {nxt})")


# ---- a machine's setup (`mhp status` reports it, part by part) ---------------------------------------------
# A setup part is not moved through transitions by one owner; it is observed. What is declared is every state a
# part can be reported in and what it means, so `mhp status`, the specification and the skills say the same thing.
# A state with a next step is one that needs something done; status.py names the step.

# the link from a lab PC or an agent machine to its gateway (relay.py writes it, mhp status reads it)
LINK_STATES = {
    "connected": "the gateway answers and accepts this machine",
    "unreachable": "the gateway did not answer: network, VPN, or the gateway is down",
    "unpaired": "the gateway answered but no longer accepts this machine's pairing: pair again",
    "certificate_changed": "something answers at the gateway's address with a certificate this machine did not pin",
    "error": "the gateway answered with an error this machine does not recognise",
    "unknown": "nothing tried the link yet (the node has not run since pairing)",
}

# an agent skill installed in a harness's skills folder (skills_install.py)
SKILL_STATES = {
    "current": "the installed copy is this OpenMHP's",
    "outdated": "an older copy, untouched since installed: `mhp skills install` updates it",
    "newer": "a newer copy than this OpenMHP has: left alone",
    "changed": "edited by hand since installed: left alone unless a person asks (then backed up first)",
    "missing": "not installed in that folder",
}

# every part `mhp status` reports, and the states it reports it in
STATUS_PARTS = {
    "install": {"current", "outdated"},
    "gateway link": set(LINK_STATES),
    "runs over SSH": {"set up", "not set up"},
    "agent skills": {"current", "needs update"},
    "instruments": {"ready", "not ready", "none"},
    "background service": {"running", "stopped", "installed", "not installed", "broken"},
    "gateway": {"running", "running old code", "not running"},
    "gateway service": {"not installed"},
}


def check_status_part(part: str, state: str) -> None:
    """`mhp status` reports only declared parts and states, so its words and the documentation cannot drift."""
    if state not in STATUS_PARTS.get(part, ()):
        raise ValueError(f"mhp status: {part!r} has no declared state {state!r} (openmhp/states.py STATUS_PARTS)")
