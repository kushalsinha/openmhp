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
