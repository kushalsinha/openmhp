"""The gateway's supervisor for runs: plain code that owns a run's state, its record, its instruments and
its agent session, and never decides science.

This module starts with the run record. The authoritative state and event log live in the gateway's own
folder (`<gateway>/runs/<id>/`), where a run cannot edit them. A copy is mirrored into the scientist's run
folder (`meta.json`, `events.jsonl`) for them and their agent to read.

    open -> planning -> waiting_approval -> queued -> running <-> waiting_scientist -> finished
                                                         |                               stopped
                                                         +-> interrupted (gateway restart)  failed
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from . import scientists as S

TRANSITIONS = {
    "open": {"planning", "waiting_approval", "stopped"},
    "planning": {"waiting_approval", "stopped", "failed"},
    "waiting_approval": {"planning", "queued", "running", "stopped"},
    "queued": {"running", "stopped", "failed"},
    "running": {"waiting_scientist", "finished", "stopped", "failed", "interrupted"},
    "waiting_scientist": {"running", "finished", "stopped", "failed", "interrupted"},
    "interrupted": {"queued", "running", "stopped"},
    "finished": set(), "stopped": set(), "failed": set(),
}
ENDED = {"finished", "stopped", "failed"}
LIVE = {"queued", "running", "waiting_scientist"}


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


class RunRecord:
    """One run's state and events, kept by the gateway and mirrored to the scientist's folder."""

    def __init__(self, private: Path, run_id: str, owner: str, lab_root: Path | None = None):
        self.private, self.id, self.owner, self.lab_root = Path(private), S.check_run_id(run_id), S.check_name(owner), lab_root
        self.lock = threading.RLock()
        self.private.mkdir(parents=True, exist_ok=True)
        self.doc = self._load() or {"id": self.id, "owner": self.owner, "state": "open", "created": now(), "history": []}

    # ---- files -----------------------------------------------------------------------------
    def _load(self) -> dict | None:
        try:
            return json.loads((self.private / "state.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _write(self, path: Path, obj: dict) -> None:
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(obj, indent=1, default=str), encoding="utf-8")
        os.replace(tmp, path)

    def public_folder(self) -> Path:
        return S.run_folder(self.owner, self.id, self.lab_root)

    def _mirror(self, event: dict | None = None) -> None:
        """What the scientist sees. Never read back: the gateway's copy is the truth."""
        d = self.public_folder()
        if not d.is_dir():
            return
        meta = {k: v for k, v in self.doc.items() if k != "history"}
        meta["updated"] = now()
        try:
            self._write(d / "meta.json", meta)
            if event is not None:
                with open(d / "events.jsonl", "a", encoding="utf-8") as f:
                    f.write(json.dumps(event, default=str) + "\n")
        except OSError:
            pass                                    # the scientist's folder is a view; the record stands without it

    # ---- state -----------------------------------------------------------------------------
    @property
    def state(self) -> str:
        return self.doc["state"]

    def set(self, **fields) -> None:
        """Facts about the run that are not a state change: its charter digest, harness, session, step."""
        with self.lock:
            self.doc.update(fields)
            self._write(self.private / "state.json", self.doc)
            self._mirror()

    def to(self, state: str, why: str = "", **fields) -> dict:
        with self.lock:
            cur = self.doc["state"]
            if state not in TRANSITIONS.get(cur, set()):
                raise ValueError(f"run {self.id} cannot go from {cur} to {state}")
            self.doc["state"] = state
            self.doc.update(fields)
            self.doc["history"].append({"state": state, "at": now(), "why": why})
            self._write(self.private / "state.json", self.doc)
        return self.event("state", state=state, previous=cur, why=why)

    def event(self, kind: str, **fields) -> dict:
        ev = {"at": now(), "ts": time.time(), "run": self.id, "kind": kind, **fields}
        with self.lock:
            with open(self.private / "events.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(ev, default=str) + "\n")
            self._mirror(ev)
        return ev

    def events(self, since: float = 0.0) -> list[dict]:
        try:
            lines = (self.private / "events.jsonl").read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out = []
        for line in lines:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("ts", 0) > since:
                out.append(ev)
        return out


def recover(runs_dir: Path, lab_root: Path | None = None) -> list[str]:
    """After a gateway restart: live runs lost their leases and their session, and the bench may have moved.
    Mark them interrupted; nothing resumes on its own."""
    out = []
    if not Path(runs_dir).is_dir():
        return out
    for d in sorted(Path(runs_dir).iterdir()):
        try:
            doc = json.loads((d / "state.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if doc.get("state") in LIVE:
            rec = RunRecord(d, doc["id"], doc["owner"], lab_root)
            rec.to("interrupted", "the gateway restarted; leases lapsed and instrument watchdogs acted. Check the bench "
                   "before resuming.")
            out.append(doc["id"])
    return out


# ================================================================================================
# The supervisor: starts a run's agent when the scientist approves, wakes it when something needs a
# decision, carries questions and answers, stops and ends runs. It runs inside `mhp gateway serve`.
# ================================================================================================
import queue as _queue
import shutil as _shutil
import sys as _sys

WAKE_EVENTS = ("jobs/finished", "safety/estop", "safety/fault", "safety/watchdog", "operator/instruction", "jobs/paused")
STUCK_AFTER_FAILED_TURNS = 3

RUN_RULES = """You are the agent for run {run} of scientist {owner}, working on an OpenMHP gateway.

The charter below is what {owner} approved. The gateway enforces its structured part on every instrument
call: anything outside it is refused, and some actions come back as "ask the scientist". Do not try to
work around a refusal. When you need a decision outside the charter, a judgement on a strange result,
or someone in the lab, call ask_scientist and say what you tried.

How to work:
- Your instruments are reached through the openmhp tools (mhp_find, mhp_describe, mhp_read, mhp_invoke,
  mhp_job, mhp_run ...). Rehearse multi-step work with mhp_run plan=true before running it.
- The scientist's skills, scripts and data are in this folder (copied from what they handed over). Use them
  for analysis and for choosing the next experiment.
- Keep notebook.md up to date: what you did, what you learned, what you plan next. You are woken many times;
  the notebook is how you remember.
- Put results the scientist should receive in out/ (data, plots, a report), as you go.
- Call report now and then with a short progress note.
- Long fixed sequences: write them as a script and run them with mhp_run background=true; you are woken
  when instrument jobs finish.
- When the objective is met, a stop condition holds, or the budget is spent: do the cleanup the charter
  describes, then call finish with a summary and suggested next experiments.

{summary}
"""


class RunCtl:
    def __init__(self, record: RunRecord):
        self.record = record
        self.triggers: _queue.Queue = _queue.Queue()
        self.thread: threading.Thread | None = None
        self.failures = 0
        self.spent_usd = 0.0
        self.question_seq = 0
        self.last_report = time.time()


class Supervisor:
    def __init__(self, gateway, *, lab_root: Path, runs_dir: Path, adapters: dict | None = None,
                 run_as_users: bool = False, poll_s: float = 0.5):
        from .harness import ADAPTERS
        self.gw, self.lab_root, self.runs_dir = gateway, Path(lab_root), Path(runs_dir)
        self.adapters = adapters if adapters is not None else ADAPTERS
        self.run_as_users, self.poll_s = run_as_users, poll_s
        self.ctl: dict[str, RunCtl] = {}
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        gateway.supervisor = self

    # ---- records -----------------------------------------------------------------------------
    def record(self, run_id: str, owner: str | None = None) -> RunRecord:
        with self.lock:
            c = self.ctl.get(run_id)
            if c is None:
                if owner is None:
                    doc = json.loads((self.runs_dir / run_id / "state.json").read_text(encoding="utf-8"))
                    owner = doc["owner"]
                c = self.ctl[run_id] = RunCtl(RunRecord(self.runs_dir / run_id, run_id, owner, self.lab_root))
            return c.record

    def charter(self, run_id: str) -> dict:
        return json.loads((self.runs_dir / run_id / "charter.json").read_text(encoding="utf-8"))

    # ---- proposal and approval ---------------------------------------------------------------
    def propose(self, run_id: str, owner: str, charter: dict, harness: str = "claude-code") -> str:
        """A charter for the scientist to approve (written by the planner). Returns its digest."""
        from . import charter as C
        problems = C.problems(charter)
        if problems:
            raise ValueError("; ".join(problems))
        if charter.get("run") != run_id or charter.get("owner") != owner:
            raise ValueError("the charter names another run or scientist")
        if harness not in self.adapters:
            raise ValueError(f"no harness {harness!r} on this gateway (available: {', '.join(sorted(self.adapters))})")
        rec = self.record(run_id, owner)
        (self.runs_dir / run_id).mkdir(parents=True, exist_ok=True)
        (self.runs_dir / run_id / "charter.json").write_text(json.dumps(charter, indent=1), encoding="utf-8")
        d = C.digest(charter)
        pub = rec.public_folder()
        if pub.is_dir():
            (pub / "charter.md").write_text(C.summary(charter), encoding="utf-8")
            (pub / "charter.json").write_text(json.dumps(charter, indent=1), encoding="utf-8")
        if rec.state in ("open", "planning"):
            rec.to("waiting_approval", "charter ready for the scientist", charter_digest=d, harness=harness)
        else:
            rec.set(charter_digest=d, harness=harness)
        return d

    def approve(self, run_id: str, digest: str, by: str) -> dict:
        from . import charter as C
        rec = self.record(run_id)
        if rec.state != "waiting_approval":
            raise ValueError(f"run {run_id} is {rec.state}, not waiting for approval")
        if by != rec.owner:
            raise PermissionError("only the scientist who owns the run approves it")
        charter = self.charter(run_id)
        if C.digest(charter) != digest:
            raise ValueError("that is not the charter on record (it changed, or the digest is wrong): look again with "
                             "`mhp-gw show` and approve what it shows")
        charter.update(approved_by=by, approved_at=now())
        (self.runs_dir / run_id / "charter.json").write_text(json.dumps(charter, indent=1), encoding="utf-8")
        with open(self.runs_dir / run_id / "approvals.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"at": now(), "by": by, "digest": digest}) + "\n")
        self.gw.issue_run_token(charter)
        rec.to("queued", f"approved by {by}")
        got = self.gw.allocate(run_id)
        if got["state"] == "allocated":
            self._start(run_id)
        else:
            rec.event("waiting_for_instruments", detail=got)
        return {"run": run_id, "state": rec.state, "show_to_scientist": self.start_message(run_id)}

    @staticmethod
    def start_message(run_id: str) -> str:
        return (f"Run {run_id} has started. Physical experiments can get stuck. Please keep watching this conversation "
                "and your desktop notifications for questions, or for requests that may need you to go to the lab. When "
                "the run ends, its results stay on the gateway for 7 days, or until your machine downloads them. "
                "Connect this machine within 7 days of the end, or the results are deleted.")

    # ---- starting the agent ------------------------------------------------------------------
    def _token(self, run_id: str) -> str:
        for t, e in self.gw.state.get("run_tokens", {}).items():
            if e["run"] == run_id:
                return t
        raise LookupError(f"run {run_id} has no token")

    def public_cert(self) -> Path:
        """The gateway's certificate where every scientist's run can read it (the gateway's own folder is private)."""
        dest = self.lab_root / "gateway-cert.pem"
        src = Path(self.gw.state["cert"])
        if not dest.is_file() or dest.read_bytes() != src.read_bytes():
            self.lab_root.mkdir(parents=True, exist_ok=True)
            _shutil.copyfile(src, dest)
            os.chmod(dest, 0o644)
        return dest

    def prepare(self, run_id: str) -> dict:
        """The run's working folder: the scientist's files, their skills where the harness finds them, the MCP
        servers holding the run token, and the instructions. Everything the session needs, nothing else."""
        from . import charter as C
        from .gateway import agent_url
        from .harness import install_skills
        rec = self.record(run_id)
        pub = rec.public_folder()
        work = pub / "work"
        if not work.exists():
            _shutil.copytree(pub / "in", work, symlinks=False)
        (work / "out").mkdir(exist_ok=True)
        skills = install_skills(pub / "in", work)
        token, cert, gateway = self._token(run_id), self.public_cert(), agent_url(self.gw.state).rstrip("/")
        common = {"SSL_CERT_FILE": str(cert), "OPENMHP_NO_UPDATE_CHECK": "1"}
        mcp = {"mcpServers": {
            "openmhp": {"command": _sys.executable, "args": ["-m", "openmhp.mcp_bridge", "--directory", gateway + "/directory/"],
                        "env": {**common, "OPENMHP_DEVICE_TOKEN": token, "OPENMHP_RUN_SCOPE": "1",
                                "OPENMHP_HOME": str(work / ".openmhp")}},
            "run": {"command": _sys.executable, "args": ["-m", "openmhp.run_tools"],
                    "env": {**common, "OPENMHP_RUN_TOKEN": token, "OPENMHP_GATEWAY": gateway}}}}
        (work / ".mcp-run.json").write_text(json.dumps(mcp, indent=1), encoding="utf-8")
        os.chmod(work / ".mcp-run.json", 0o600)
        charter = self.charter(run_id)
        (work / ".run-instructions.md").write_text(RUN_RULES.format(run=run_id, owner=rec.owner, summary=C.summary(charter)),
                                                   encoding="utf-8")
        if not (work / "notebook.md").exists():
            (work / "notebook.md").write_text(f"# Lab notebook for {run_id}\n\n", encoding="utf-8")
        rec.event("prepared", skills=skills)
        return {"work": work, "token": token, "gateway": gateway, "cert": cert}

    def _start(self, run_id: str) -> None:
        rec = self.record(run_id)
        self.prepare(run_id)
        rec.to("running", "all instruments allocated")
        self.wake(run_id, "start", "The run has started. Read the charter in your instructions and notebook.md, plan, "
                  "rehearse, then begin.")

    # ---- wake-ups ----------------------------------------------------------------------------
    def wake(self, run_id: str, kind: str, text: str) -> None:
        c = self.ctl.get(run_id) or (self.record(run_id) and self.ctl[run_id])
        c.triggers.put({"kind": kind, "text": text, "at": now()})
        with self.lock:
            if c.thread is None or not c.thread.is_alive():
                c.thread = threading.Thread(target=self._worker, args=(run_id,), name=f"mhp-run-{run_id}", daemon=True)
                c.thread.start()

    def _worker(self, run_id: str) -> None:
        from .harness import Turn, run_turn
        c = self.ctl[run_id]
        while not self.stop_event.is_set():
            try:
                first = c.triggers.get(timeout=0.2)
            except _queue.Empty:
                return
            batch = [first]
            while True:
                try:
                    batch.append(c.triggers.get_nowait())
                except _queue.Empty:
                    break
            rec = c.record
            if rec.state in ENDED:
                return
            if rec.state == "waiting_scientist" and not any(t["kind"] in ("answer", "message", "stop") for t in batch):
                continue                              # waiting on a person: instrument news waits for the answer
            charter = self.charter(run_id)
            prompt = "\n".join(f"[{t['at']}] {t['kind']}: {t['text']}" for t in batch)
            work = rec.public_folder() / "work"
            adapter = self.adapters[rec.doc.get("harness", "claude-code")]
            env = {"OPENMHP_RUN_ID": run_id}
            budget = (charter.get("budgets") or {}).get("agent_usd")
            left = None if budget is None else max(0.0, float(budget) - c.spent_usd)
            if left is not None and left <= 0:
                self.ask(run_id, "The agent budget for this run is spent. Raise it, or should the run stop?",
                         tried="", meanwhile="wait", by_supervisor=True)
                continue
            rec.event("wake", triggers=[t["kind"] for t in batch])
            result = run_turn(adapter, Turn(prompt=prompt, workdir=work, session=rec.doc.get("session"),
                                            mcp_config=work / ".mcp-run.json", instructions=work / ".run-instructions.md",
                                            max_budget_usd=left, env=env,
                                            run_as=f"mhp-{rec.owner}" if self.run_as_users else None))
            c.spent_usd += result.cost_usd
            rec.set(session=result.session or rec.doc.get("session"), spent_usd=round(c.spent_usd, 4))
            rec.event("turn", ok=result.ok, reason=result.reason, cost_usd=result.cost_usd, tokens=result.tokens,
                      said=(result.text or "")[:2000])
            if result.ok:
                c.failures = 0
            else:
                c.failures += 1
                if c.failures >= STUCK_AFTER_FAILED_TURNS and c.record.state == "running":
                    self.ask(run_id, f"The run's agent failed {c.failures} turns in a row ({result.reason}: "
                             f"{(result.text or '')[:300]}). Should it keep trying, or stop?", tried="", meanwhile="wait",
                             by_supervisor=True)

    def on_device_event(self, path: str, event: dict) -> None:
        """Called by the gateway for every event a lab PC pushes."""
        method = (event or {}).get("method", "").replace("notifications/", "")
        if method not in WAKE_EVENTS:
            return
        for run_id, devices in list(self.gw.allocated.items()):
            if path in devices:
                rec = self.record(run_id)
                if rec.state in ("running", "waiting_scientist"):
                    self.wake(run_id, "instrument", f"{path}: {method} {json.dumps(event.get('params') or {})[:600]}")

    # ---- the run agent's tools ---------------------------------------------------------------
    def ask(self, run_id: str, question: str, *, tried: str = "", meanwhile: str = "wait", needs_lab: bool = False,
            by_supervisor: bool = False) -> dict:
        c = self.ctl.get(run_id) or (self.record(run_id) and self.ctl[run_id])
        c.question_seq += 1
        qid = f"q{c.question_seq}"
        ev = c.record.event("question", id=qid, question=question, tried=tried, meanwhile=meanwhile, needs_lab=needs_lab,
                            by="supervisor" if by_supervisor else "agent")
        open_q = dict(c.record.doc.get("open_questions") or {})
        open_q[qid] = {"question": question, "needs_lab": needs_lab, "asked": ev["at"]}
        c.record.set(open_questions=open_q)
        if meanwhile == "wait" and c.record.state == "running":
            c.record.to("waiting_scientist", f"asked {qid}")
        return {"ok": True, "question": qid, "note": "the scientist's answer will come as a later turn"}

    def answer(self, run_id: str, qid: str, text: str, by: str) -> dict:
        rec = self.record(run_id)
        if by != rec.owner:
            raise PermissionError("only the run's scientist answers its questions")
        open_q = dict(rec.doc.get("open_questions") or {})
        if qid not in open_q:
            raise LookupError(f"no open question {qid} on run {run_id}")
        q = open_q.pop(qid)
        rec.set(open_questions=open_q)
        rec.event("answer", id=qid, by=by, text=text)
        if rec.state == "waiting_scientist" and not open_q:
            rec.to("running", f"{by} answered {qid}")
        self.wake(run_id, "answer", f"{by} answered your question {qid} ({q['question'][:200]}): {text}")
        return {"run": run_id, "answered": qid, "state": rec.state}

    def report(self, run_id: str, text: str) -> dict:
        self.record(run_id).event("report", text=text)
        return {"ok": True}

    def finish(self, run_id: str, summary: str, outcome: str, next_experiments: list | None = None) -> dict:
        rec = self.record(run_id)
        pub = rec.public_folder()
        out = pub / "out"
        lines = [f"# Run {run_id}: {outcome}", "", summary, ""]
        if next_experiments:
            lines += ["## Suggested next experiments", ""] + [f"- {x}" for x in next_experiments] + [""]
        work = pub / "work"
        if (work / "out").is_dir():
            _shutil.copytree(work / "out", out, dirs_exist_ok=True)
        if (work / "notebook.md").is_file():
            _shutil.copyfile(work / "notebook.md", out / "notebook.md")
        (out / "report.md").write_text("\n".join(lines), encoding="utf-8")
        rec.event("finish", outcome=outcome, summary=summary, next_experiments=next_experiments or [])
        self.gw.end_run(run_id)
        rec.to("finished", outcome, ended=now())
        return {"ok": True, "state": "finished"}

    # ---- the scientist's requests ------------------------------------------------------------
    def message(self, run_id: str, text: str, by: str) -> dict:
        rec = self.record(run_id)
        if by != rec.owner:
            raise PermissionError("only the run's scientist messages it")
        if rec.state not in ("running", "waiting_scientist", "queued"):
            raise ValueError(f"run {run_id} is {rec.state}")
        rec.event("message", by=by, text=text)
        self.wake(run_id, "message", f"{by} says: {text}. (If this asks for something outside the charter, the gateway will "
                  "refuse it: tell them it needs a changed charter, through ask_scientist.)")
        return {"run": run_id, "delivered": True}

    def stop(self, run_id: str, by: str, cleanup_timeout_s: float = 600) -> dict:
        """Stop now: the agent gets one turn to clean up as the charter says, then the instruments are released."""
        from .harness import Turn, run_turn
        rec = self.record(run_id)
        if by != rec.owner and by != "supervisor":
            raise PermissionError("only the run's scientist stops it")
        if rec.state in ENDED:
            return {"run": run_id, "state": rec.state}
        rec.event("stop", by=by)
        if rec.state in ("running", "waiting_scientist") and rec.doc.get("session"):
            work = rec.public_folder() / "work"
            adapter = self.adapters[rec.doc.get("harness", "claude-code")]
            r = run_turn(adapter, Turn(prompt=f"[{now()}] stop: {by} stopped the run. Do the charter's cleanup now, write what "
                                       "you have to out/ and notebook.md, and do not start anything new.",
                                       workdir=work, session=rec.doc.get("session"), mcp_config=work / ".mcp-run.json",
                                       max_turns=15, timeout_s=cleanup_timeout_s, env={"OPENMHP_RUN_ID": run_id},
                                       run_as=f"mhp-{rec.owner}" if self.run_as_users else None))
            rec.event("turn", ok=r.ok, reason=r.reason, cost_usd=r.cost_usd, said=(r.text or "")[:2000], cleanup=True)
        self.gw.end_run(run_id)
        pub = rec.public_folder()
        if (pub / "work" / "out").is_dir():
            _shutil.copytree(pub / "work" / "out", pub / "out", dirs_exist_ok=True)
        rec.to("stopped", f"stopped by {by}", ended=now())
        return {"run": run_id, "state": "stopped"}

    # ---- the loop ----------------------------------------------------------------------------
    def tick(self) -> None:
        """Start runs whose instruments came free, act on requests the scientists dropped in their inboxes, and
        wake runs that are due a scheduled check."""
        for run_id in list(self.gw.allocated):
            rec = self.record(run_id) if (self.runs_dir / run_id / "state.json").is_file() else None
            if rec is not None and rec.state == "queued":
                self._start(run_id)
        self.process_inboxes()
        for run_id, c in list(self.ctl.items()):
            if c.record.state != "running":
                continue
            every = ((self.charter(run_id).get("reporting") or {}).get("every_hours"))
            if every and time.time() - c.last_report > float(every) * 3600:
                c.last_report = time.time()
                self.wake(run_id, "scheduled", "Scheduled check: look at the instruments and your notebook, then report.")

    def process_inboxes(self) -> None:
        base = self.lab_root / "scientists"
        if not base.is_dir():
            return
        for inbox in sorted(base.glob("*/runs/*/inbox")):
            owner, run_id = inbox.parent.parent.parent.name, inbox.parent.name
            for req in sorted(inbox.glob("*.json")):
                if req.name.endswith(".done.json"):
                    continue
                try:
                    body = json.loads(req.read_text(encoding="utf-8"))
                    kind = body.get("kind")
                    if kind == "approve":
                        ans = self.approve(run_id, body.get("digest", ""), owner)
                    elif kind == "message":
                        ans = self.message(run_id, body.get("text", ""), owner)
                    elif kind == "answer":
                        ans = self.answer(run_id, body.get("question", ""), body.get("text", ""), owner)
                    elif kind == "stop":
                        ans = self.stop(run_id, owner)
                    else:
                        raise ValueError(f"unknown request {kind!r}")
                    result = {"ok": True, **ans}
                except (ValueError, LookupError, PermissionError, OSError) as e:
                    result = {"ok": False, "error": str(e), "not_found": isinstance(e, LookupError)}
                done = req.with_name(req.stem + ".done.json")
                done.write_text(json.dumps(result, default=str), encoding="utf-8")
                req.unlink()

    def loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.tick()
            except Exception as e:                       # noqa: BLE001  a bad request must not stop supervision
                print(f"supervisor: {type(e).__name__}: {e}", file=_sys.stderr)
            self.stop_event.wait(self.poll_s)

    def start(self) -> threading.Thread:
        recover(self.runs_dir, self.lab_root)
        t = threading.Thread(target=self.loop, name="mhp-supervisor", daemon=True)
        t.start()
        return t
