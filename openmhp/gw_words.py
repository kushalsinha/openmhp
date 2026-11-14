"""What the gateway says, in plain English.

Every `mhp-gw` answer carries a `say` field built here: a few sentences a scientist's agent can show the
scientist as they are, or retell in its own words. The JSON next to it is for the agent; `say` is for the person.
The words come from the gateway, so a scientist hears the same thing whichever agent or harness they use.
"""
from __future__ import annotations

STATES = {
    "open": "is open. Nothing has been asked for yet: hand over your files and send the request.",
    "planning": "is being planned. The lab's planner is working the experiment out with you; nothing moves on the "
                "instruments while it plans, though it may rehearse with dry runs.",
    "waiting_approval": "has a plan ready for your approval. Nothing runs until you approve it.",
    "queued": "is approved and is waiting for its instruments to be free.",
    "running": "is running.",
    "waiting_scientist": "is paused, waiting for your answer before it goes on.",
    "finished": "has finished.",
    "stopped": "was stopped.",
    "failed": "failed.",
    "interrupted": "was interrupted: the gateway restarted while it ran.",
}
SHORT = {"open": "open, waiting for files and a request", "planning": "being planned",
         "waiting_approval": "waiting for your approval", "queued": "approved, waiting for instruments",
         "running": "running", "waiting_scientist": "waiting for your answer", "finished": "finished",
         "stopped": "stopped", "failed": "failed", "interrupted": "interrupted"}
ENDED = ("finished", "stopped", "failed", "interrupted")


def _q(qid: str, q: dict | str) -> str:
    text = q.get("question", "") if isinstance(q, dict) else str(q)
    lab = " Someone needs to go to the lab for this." if isinstance(q, dict) and q.get("needs_lab") else ""
    return f"Question {qid}: {text}{lab}"


def run_state(meta: dict) -> str:
    """One run, as a scientist would want to hear it."""
    rid, state = meta.get("id", "?"), meta.get("state", "?")
    out = [f"Run {rid} {STATES.get(state, 'is ' + state + '.')}"]
    qs = meta.get("open_questions") or {}
    if qs:
        out.append(f"It has {len(qs)} open question(s) for you:")
        out += [_q(k, v) for k, v in qs.items()]
    if state == "waiting_approval" and meta.get("charter_digest"):
        out.append("Ask me to show you the plan (its charter) before you decide.")
    if state in ENDED:
        if meta.get("purged"):
            out.append("Its results have been deleted from the gateway"
                       + (" after your machine received them." if meta.get("acked") else "."))
        elif meta.get("acked"):
            out.append("Your machine has received its results; the gateway is deleting its copy.")
        else:
            out.append("Its results are waiting on the gateway for your machine to bring them home (kept 7 days).")
    if meta.get("spent_usd"):
        out.append(f"The lab's agent has used ${meta['spent_usd']:.2f} of model time on it so far.")
    return " ".join(out)


def event(ev: dict) -> str | None:
    """One piece of news from a run, or None for bookkeeping the scientist need not hear."""
    k, rid = ev.get("kind"), ev.get("run", "the run")
    if k == "question":
        return f"{rid} asks you (question {ev.get('id')}): {ev.get('question')}" + (
            " Someone needs to go to the lab for this." if ev.get("needs_lab") else "")
    if k == "answer":
        return f"You answered question {ev.get('id')}: {ev.get('text')}"
    if k == "message":
        return f"You told {rid}: {ev.get('text')}"
    if k in ("charter_proposed", "charter_revised"):
        return f"{rid}: the planner has {'revised' if k == 'charter_revised' else 'proposed'} a plan for your approval."
    if k == "plan_notes":
        files = ev.get("preview") or []
        return (f"The planner's notes on {rid}: {ev.get('notes')}"
                + (f" It also left a preview of the data you will get ({', '.join(files)})." if files else ""))
    if k == "state":
        why = ev.get("why")
        return f"{rid} {STATES.get(ev.get('state'), 'is now ' + str(ev.get('state')) + '.')}" + (f" ({why})" if why else "")
    if k == "report":
        return f"Progress on {rid}: {ev.get('text')}"
    if k == "finish":
        nxt = ev.get("next_experiments") or []
        return (f"{rid} ended ({ev.get('outcome')}): {ev.get('summary')}"
                + (" Suggested next: " + "; ".join(nxt) + "." if nxt else ""))
    if k == "results_ready":
        return (f"{rid}'s results are ready on the gateway: {ev.get('files')} file(s), kept {ev.get('keep_days', 7)} days "
                "or until your machine brings them home.")
    if k == "results_received":
        return f"The gateway knows your machine has {rid}'s results."
    if k == "results_deleted":
        return f"The gateway deleted its copy of {rid}'s results ({ev.get('why')})."
    return None


def events(evs: list[dict]) -> str:
    lines = [t for t in (event(e) for e in evs) if t]
    return "\n".join(lines) if lines else "Nothing new."


def charter(rid: str, text: str | None, notes: str | None, preview: list[str]) -> str:
    if not text:
        return f"Run {rid} has no plan to approve yet."
    out = [f"Here is the plan for {rid}. It says what the run may do on which instruments, its limits, when it stops, "
           "and how it cleans up. Read it to the scientist and ask, in plain words, whether to approve it exactly as written."]
    if notes:
        out.append(f"The planner adds: {notes}")
    if preview:
        out.append(f"A preview of the data it will produce is in the run's preview/ folder: {', '.join(preview)}.")
    return " ".join(out)
