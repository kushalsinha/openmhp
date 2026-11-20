"""A run's state machine on the lab gateway, declared once (openmhp/states.py) and checked where it moves: every
state has its words for the scientist and its next steps, a run ends once, nothing is answered after it ends,
question numbers and spend survive a restart, an interrupted run resumes, a run the gateway cannot start fails
with a reason, and an answer that came too late for `mhp-gw` is delivered with the next command.

    PYTHONPATH=. python tests/test_gateway_run_states.py
"""
import io
import json
import os
import sys
import tempfile
import time
import types
from pathlib import Path

sys.path.insert(0, ".")
os.environ["OPENMHP_HOME"] = tempfile.mkdtemp(prefix="openmhp-runstates-")
os.environ["OPENMHP_LAB_ROOT"] = str(Path(os.environ["OPENMHP_HOME"]) / "lab")
os.environ["OPENMHP_NO_UPDATE_CHECK"] = "1"

from openmhp import gw_shell as GW, gw_words as W, scientists as S, states as ST, supervisor as SV   # noqa: E402

PRIVATE = Path(os.environ["OPENMHP_HOME"]) / "gateway" / "runs"


class raises:
    def __init__(self, exc):
        self.exc, self.value = exc, None
    def __enter__(self):
        return self
    def __exit__(self, et, ev, tb):
        assert et is not None and issubclass(et, self.exc), f"expected {self.exc.__name__}, got {et}: {ev}"
        self.value = ev
        return True


class FakeGateway:
    """What the supervisor asks of a gateway, recorded instead of done."""
    def __init__(self):
        self.allocated, self.state, self.calls = {}, {"run_tokens": {}}, []
    def issue_run_token(self, charter):
        self.calls.append(("token", charter["run"]))
    def allocate(self, run_id):
        self.calls.append(("allocate", run_id))
        return {"state": "queued"}
    def end_run(self, run_id):
        self.calls.append(("end", run_id))


def supervisor():
    gw = FakeGateway()
    return SV.Supervisor(gw, lab_root=S.lab_root(), runs_dir=PRIVATE, adapters={}, poll_s=0.1), gw


def new_run(state_path=("planning", "waiting_approval")):
    rid = S.open_run("alice")["id"]
    rec = SV.RunRecord(PRIVATE / rid, rid, "alice", S.lab_root())
    for st in state_path:
        rec.to(st, "test")
    return rid, rec


def shell(command, stdin="", wait_s=5):
    out = io.StringIO()
    code = GW.Shell("alice", out=out, env={"SSH_ORIGINAL_COMMAND": command}, stdin=io.StringIO(stdin), wait_s=wait_s).run()
    return code, json.loads(out.getvalue())


def test_every_state_is_declared_once_and_described_everywhere():
    assert SV.ENDED is ST.RUN_ENDED and SV.TRANSITIONS is ST.RUN_TRANSITIONS and W.ENDED is ST.RUN_ENDED
    for state in ST.RUN_STATES:
        assert state in W.STATES and state in W.SHORT, state                 # words for the scientist
        assert state in ST.RUN_WAITING_ON and state in ST.RUN_NEXT, state     # who it waits on, what can be done
        for target in ST.RUN_TRANSITIONS[state]:
            assert target in ST.RUN_TRANSITIONS, (state, target)
        if state not in ST.RUN_ENDED:
            assert ST.RUN_TRANSITIONS[state], f"{state} is a dead end"
        verbs = {c.split()[0] for c, _ in ST.RUN_NEXT[state]}
        assert verbs <= set(GW.VERBS) | {"rsync"}, (state, verbs - set(GW.VERBS))
    assert "interrupted" not in ST.RUN_ENDED and ST.RUN_TRANSITIONS["interrupted"] == {"queued", "stopped"}
    reachable = {t for ts in ST.RUN_TRANSITIONS.values() for t in ts} | {"open"}
    assert reachable == set(ST.RUN_STATES)
    with raises(ValueError) as e:
        ST.check_run_move("R-1", "finished", "running")
    assert "what it can do now: rsync, ack" in str(e.value)


def test_question_numbers_and_spend_survive_a_restart():
    sup, _ = supervisor()
    rid, rec = new_run()
    assert sup.ask(rid, "first?")["question"] == "q1"
    sup.record(rid).set(spent_usd=1.25)
    again, _ = supervisor()                                                   # a gateway restart: nothing in memory
    assert again.ask(rid, "second?")["question"] == "q2"
    assert set(again.record(rid).doc["open_questions"]) == {"q1", "q2"}       # q1 is not overwritten
    assert again.ctl[rid].spent_usd == 1.25


def test_a_run_ends_once_and_its_questions_close_with_it():
    sup, gw = supervisor()
    rid, rec = new_run(("planning", "waiting_approval", "queued", "running"))
    sup.ask(rid, "keep cell 4?")
    with raises(LookupError):
        sup.finish(rid + "x", "", "")                                         # unknown run: nothing written
    with raises(ValueError) as e:
        sup.ask(new_run(("planning", "waiting_approval", "queued", "running", "finished"))[0], "too late?")
    assert "has ended" in str(e.value)
    r = sup.stop(rid, "alice")
    assert r["state"] == "stopped" and gw.calls.count(("end", rid)) == 1
    assert sup.record(rid).doc["open_questions"] == {}
    assert any(e["kind"] == "questions_closed" and e["ids"] == ["q1"] for e in sup.record(rid).events())
    assert sup.stop(rid, "alice")["note"] == "it had already stopped"          # a second stop does nothing
    with raises(ValueError) as e:
        sup.finish(rid, "done", "objective met")                              # a finish after the stop writes nothing
    assert "finish ends a run that is running" in str(e.value)
    assert not (S.run_folder("alice", rid) / "out" / "report.md").exists()
    with raises(ValueError) as e:
        sup.answer(rid, "q1", "yes", "alice")
    assert "closed with it" in str(e.value)
    assert gw.calls.count(("end", rid)) == 1


def test_a_finish_and_a_stop_racing_do_not_both_end_the_run():
    sup, gw = supervisor()
    rid, rec = new_run(("planning", "waiting_approval", "queued", "running"))
    assert sup._claim_end(rec, "stop by alice")                               # the stop got there first
    with raises(ValueError) as e:
        sup.finish(rid, "done", "objective met")
    assert "already ending" in str(e.value)
    assert sup.stop(rid, "alice")["note"] == "it is already ending" and rec.state == "running"


def test_an_interrupted_run_resumes_and_holds_messages_until_it_starts():
    sup, gw = supervisor()
    rid, rec = new_run(("planning", "waiting_approval", "queued", "running"))
    (PRIVATE / rid / "charter.json").write_text(json.dumps({"run": rid, "owner": "alice"}))
    assert rid in SV.recover(PRIVATE, S.lab_root())                          # other tests leave live runs too
    sup = SV.Supervisor(gw, lab_root=S.lab_root(), runs_dir=PRIVATE, adapters={}, poll_s=0.1)
    meta = S.load_run("alice", rid)
    assert meta["state"] == "interrupted" and "resume it or stop it" in W.run_state(meta)
    assert [n["command"] for n in ST.run_next(meta)] == [f"resume {rid}", f"stop {rid}"]
    assert sup.message(rid, "check the lid first", "alice") == {"run": rid, "state": "interrupted", "delivered": False,
                                                                "held": True}
    r = sup.resume(rid, "alice")
    assert r["state"] == "queued" and ("token", rid) in gw.calls and ("allocate", rid) in gw.calls
    held = sup.record(rid).doc["pending_messages"]
    assert len(held) == 1 and "check the lid first" in held[0]["text"]
    with raises(ValueError):
        sup.resume(rid, "alice")                                              # only an interrupted run resumes
    with raises(PermissionError):
        sup.resume(rid, "bob")


def test_a_run_the_gateway_cannot_prepare_fails_with_its_reason():
    sup, gw = supervisor()
    rid, rec = new_run(("planning", "waiting_approval", "queued"))
    sup.prepare = lambda run_id: (_ for _ in ()).throw(RuntimeError("no Python 3.10 for the run's environment"))
    sup._start(rid)
    meta = S.load_run("alice", rid)
    assert meta["state"] == "failed" and "no Python 3.10" in meta["failed_because"] and ("end", rid) in gw.calls
    said = W.run_state(meta)
    assert "could not run" in said and "Why: the gateway could not prepare" in said and "ack" in said


def test_every_answer_about_a_run_says_who_it_waits_on_and_what_comes_next():
    rid, rec = new_run()
    code, ans = shell(f"mhp-gw status {rid}")
    assert code == GW.OK and ans["state"] == "waiting_approval" and ans["waiting_on"] == "scientist"
    assert [n["command"].split()[0] for n in ans["next"]] == ["show", "approve", "message", "stop"]
    assert "What you can do now:" in ans["say"] and "approve exactly that plan" in ans["say"]
    rid2, _ = new_run(("planning", "waiting_approval", "queued", "running", "finished"))
    code, ans = shell(f"mhp-gw status {rid2}")
    assert ans["waiting_on"] == "nobody" and [n["command"].split()[0] for n in ans["next"]] == ["rsync", "ack"]


def test_an_answer_that_came_too_late_is_delivered_with_the_next_command():
    rid, rec = new_run()
    inbox = S.run_folder("alice", rid) / "inbox"
    inbox.mkdir(exist_ok=True)
    old = time.strftime("%Y%m%dT%H%M%S", time.localtime(time.time() - 600))
    (inbox / f"{old}-1-abcd1234-stop.done.json").write_text(json.dumps({"ok": True, "state": "stopped"}))
    fresh = time.strftime("%Y%m%dT%H%M%S")
    (inbox / f"{fresh}-2-ef567890-message.done.json").write_text(json.dumps({"ok": True}))   # its requester still waits
    code, ans = shell(f"mhp-gw status {rid}")
    assert ans["earlier"] == [{"request": "stop", "ok": True, "state": "stopped"}], ans
    assert "your earlier stop was done" in ans["say"]
    assert not (inbox / f"{old}-1-abcd1234-stop.done.json").exists()
    assert (inbox / f"{fresh}-2-ef567890-message.done.json").exists()
    assert "earlier" not in shell(f"mhp-gw status {rid}")[1]                  # delivered once


def test_results_that_could_not_come_home_are_tried_again():
    from openmhp import watcher as WA
    w = WA.Watcher.__new__(WA.Watcher)
    tries = []
    w.pull = lambda run: tries.append(run) or {"ok": len(tries) > 1, "folder": "/tmp/x", "error": "connection reset"}
    w.handle({"kind": "results_ready", "run": "R-1"})
    assert w.pending() == ["R-1"]
    w.retry_pending()
    assert tries == ["R-1", "R-1"] and w.pending() == []
    w.handle({"kind": "results_ready", "run": "R-2"})
    w.handle({"kind": "results_deleted", "run": "R-2"})
    assert w.pending() == []



def test_run_files_are_replaced_while_windows_readers_hold_them():
    """Windows refuses to move a file onto one somebody has open ("Access is denied"). A scientist's stop once
    failed that way on Windows while mhp-gw read the run's state: writers and readers now wait the moment out."""
    from openmhp import atomic
    d = Path(tempfile.mkdtemp())
    target = d / "state.json"
    target.write_text('{"state": "running"}', encoding="utf-8")
    real_replace, refusals = atomic.os.replace, [3]
    def held(src, dst):
        if refusals[0]:
            refusals[0] -= 1
            raise PermissionError(5, "Access is denied", str(dst))
        real_replace(src, dst)
    atomic.os.replace = held
    try:
        atomic.write_text(target, '{"state": "stopped"}')
    finally:
        atomic.os.replace = real_replace
    assert json.loads(atomic.read_text(target)) == {"state": "stopped"} and refusals == [0]
    assert [p.name for p in d.iterdir()] == ["state.json"]                    # no side file left behind

if __name__ == "__main__":
    S.create("alice")
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok ", name)
