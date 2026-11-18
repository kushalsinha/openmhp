"""OpenMHP's state machines, declared once.

Each machine lists its states, the moves between them, and, for the person and the agent, what can be done
next from each state. The code that moves a machine checks the move here before it does anything else, and
every answer that reports a state carries its next steps, so nobody has to infer them.

    RUN     an experiment run on a lab gateway (supervisor.py moves it; mhp-gw and gw_words report it)
    DEVICE  an instrument (driver.py moves it; ping, describe and every error report it, with next steps)
"""
from __future__ import annotations

# ---- a run on the lab gateway ------------------------------------------------------------------------------
#   open -> planning <-> waiting_approval -> queued -> running <-> waiting_scientist -> finished
#                                                   ^      |                            stopped
#                                    resume ------- interrupted (the gateway restarted)  failed (could not run)
RUN_TRANSITIONS: dict[str, set[str]] = {
    "open": {"planning", "waiting_approval", "stopped", "failed"},
    "planning": {"waiting_approval", "stopped", "failed"},
    "waiting_approval": {"planning", "queued", "running", "stopped"},
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


# ---- an instrument (driver.py moves it; ping, describe and every error report it) ----------------------------
#   idle <-> busy          a job starts / the last job ends
#   idle | busy -> fault   a job failed in a way that may have reached the instrument, or the driver latched one
#   any -> estop           safety/estop, the watchdog, an orderly shutdown that ran out of time, or the instrument's
#                          own physical stop (source: client | watchdog | hardware)
#   fault | estop -> idle  safety/reset, after a person has checked the instrument (approved: true)
DEVICE_TRANSITIONS: dict[str, set[str]] = {
    "idle": {"busy", "fault", "estop"},
    "busy": {"idle", "fault", "estop"},
    "fault": {"idle", "estop"},
    "estop": {"idle"},
}
DEVICE_STATES = tuple(DEVICE_TRANSITIONS)
# what a directory reports for a device that did not answer its ping: not a state the device is in, a fact about
# the path to it
DEVICE_UNREACHABLE = "unreachable"
DEVICE_LISTED_STATES = DEVICE_STATES + (DEVICE_UNREACHABLE,)


# who stopped it, in words (the `source` of a stop)
STOP_SOURCES = {"client": "on request (safety/estop, or a shutdown that ran out of time)",
                "watchdog": "by its watchdog: the session controlling it went silent",
                "hardware": "at the instrument (its own stop)", "fault": "after a fault"}


def _step(tool: str | None, method: str | None, does: str) -> dict:
    """One next step: the MCP tool an agent calls, the wire method a script calls, and what it does in words."""
    return {**({"tool": tool} if tool else {}), **({"method": method} if method else {}), "does": does}


def device_next(state: str, *, active_jobs: list | None = None, stop: dict | None = None,
                shutting_down: bool = False, fault_reason: str | None = None) -> list[dict]:
    """What can be done next with an instrument in `state`, most useful first. Every answer that reports the
    state carries this, so neither a person nor an agent has to infer it from the state's name."""
    jobs = list(active_jobs or [])
    if state == DEVICE_UNREACHABLE:
        return [_step(None, None, "check that its lab PC runs `mhp node` (mhp status there) and the network to it"),
                _step("mhp_find", "directory/search", "pick another idle device of the same class meanwhile")]
    if shutting_down:
        return [_step("mhp_describe", "ping", "wait: it is parking itself and accepts no new work until it has; "
                                              "if it does not settle in time it e-stops itself"),
                _step("mhp_estop", "safety/estop", "stop it at once if anything looks unsafe")]
    if state == "idle":
        return [_step("mhp_describe", "device/describe", "read its instructions, limits and approval levels first"),
                _step("mhp_invoke", "actions/invoke", "run an action (dryRun: true checks every gate without moving it)"),
                _step("mhp_write", "settings/write", "change a setting")]
    if state == "busy":
        follow = f"follow its running job(s) {', '.join(jobs)}" if jobs else "follow its running job"
        return [_step("mhp_job", "jobs/status", follow + "; new actions wait until it is idle"),
                _step("mhp_job", "jobs/cancel", "cancel a job you started, if the plan changed"),
                _step("mhp_estop", "safety/estop", "stop it at once if anything looks unsafe")]
    if state in ("fault", "estop"):
        steps = []
        if jobs:
            steps.append(_step("mhp_job", "jobs/cancel", f"cancel or wait for its jobs ({', '.join(jobs)}) first: a "
                                                          "reset is refused while any still run"))
        if state == "estop" and stop and stop.get("clearable") is False:
            steps.append(_step(None, None, "a person clears it at the instrument: "
                                           + (stop.get("clearance") or "the instrument's own stop is engaged")))
            steps.append(_step("mhp_reset", "safety/reset", "then reset it; the server asks the person to confirm "
                                                            "(and refuses while the driver sees the stop engaged)"))
            return steps
        what = f"it faulted: {fault_reason}" if state == "fault" and fault_reason else \
            "it is in a fault" if state == "fault" else \
            "it was emergency-stopped " + STOP_SOURCES.get((stop or {}).get("source"), "")
        steps.append(_step(None, None, f"tell the user {what}, and ask them to check the instrument"))
        steps.append(_step("mhp_reset", "safety/reset", "after they have checked it: reset it to idle; the server asks "
                                                        "them to confirm (you cannot confirm for them)"))
        return steps
    return []


# What to do about each refusal, by error code. The device's own state adds its next steps after these.
ERROR_NEXT: dict[int, list[dict]] = {
    -32010: [_step("mhp_describe", "safety/limits", "read the limits, then send a value inside them")],          # LimitViolation
    -32011: [_step("mhp_read", "signals/read", "read the interlock signal it names; a person closes it (a lid, a "
                                               "door), then try again")],                                         # InterlockOpen
    -32012: [_step(None, None, "this needs a person's yes: through MCP the server asks them itself; from a script, "
                               "ask them, then repeat the call with approved: true")],                            # ApprovalRequired
    -32013: [_step(None, None, "not open to agents on this device; tell the user what you needed it for")],      # Forbidden
    -32014: [_step("mhp_describe", "device/describe", "check the expected type, unit and resolution (select the "
                                                      "item), then send a valid value")],                         # InvalidValue
    -32015: [_step("mhp_method", "methods/find", "this action runs saved methods: find one, then invoke with it")],  # MethodRequired
    -32021: [_step("mhp_job", "jobs/status", "wait for the running job to end, then try again")],                # DeviceBusy
    -32030: [_step(None, "session/acquire", "another session holds it; wait for its lease to end, or ask the user "
                                            "who is using it")],                                                   # NotLeased
    -32040: [_step("mhp_describe", "device/describe", "check the names it has (the summary lists them)")],       # UnknownName
    -32041: [_step(None, "jobs/list", "list its jobs; finished jobs are kept for a while, then dropped")],      # JobNotFound
}


def error_next(code: int | None, state: str | None, **device) -> list[dict]:
    """Next steps after a refusal: what to do about this error, then what the device's state allows."""
    steps = list(ERROR_NEXT.get(code or 0, []))
    if state in ("fault", "estop") or device.get("shutting_down"):      # the state is why it refused: say how out
        steps += [s for s in device_next(state, **device) if s not in steps]
    return steps
