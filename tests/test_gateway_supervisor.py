"""The run supervisor: run states and the run's record, the harness adapter, wake-ups, questions to the
scientist, messages and stop. No real agent harness is started: a stand-in plays the run agent.

    PYTHONPATH=. python tests/test_gateway_supervisor.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")
os.environ["OPENMHP_HOME"] = tempfile.mkdtemp(prefix="openmhp-sup-")
os.environ["OPENMHP_LAB_ROOT"] = str(Path(os.environ["OPENMHP_HOME"]) / "lab")
os.environ["OPENMHP_NO_UPDATE_CHECK"] = "1"

from openmhp import scientists as S, supervisor as SV                       # noqa: E402

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


def test_run_states_and_record():
    S.create("alice")
    rid = S.open_run("alice")["id"]
    rec = SV.RunRecord(PRIVATE / rid, rid, "alice")
    assert rec.state == "open"
    with raises(ValueError):
        rec.to("running")                                                   # not before approval
    rec.to("planning", "request received")
    rec.to("waiting_approval", "charter ready")
    rec.set(charter_digest="sha256:abc", harness="claude-code")
    rec.to("running", "approved by alice")
    rec.to("waiting_scientist", "asked about cell 4")
    rec.to("running", "answered")

    pub = S.run_folder("alice", rid)
    meta = json.loads((pub / "meta.json").read_text())
    assert meta["state"] == "running" and meta["harness"] == "claude-code" and "history" not in meta
    seen = [json.loads(l)["state"] for l in (pub / "events.jsonl").read_text().splitlines() if '"kind": "state"' in l]
    assert seen == ["planning", "waiting_approval", "running", "waiting_scientist", "running"]

    # the gateway's copy is the truth: editing the scientist's mirror changes nothing
    (pub / "meta.json").write_text(json.dumps({**meta, "state": "finished"}))
    again = SV.RunRecord(PRIVATE / rid, rid, "alice")
    assert again.state == "running" and [h["state"] for h in again.doc["history"]][-1] == "running"
    assert [e["kind"] for e in again.events()].count("state") == 5

    # a gateway restart interrupts live runs and leaves ended ones alone
    done = S.open_run("alice")["id"]
    d = SV.RunRecord(PRIVATE / done, done, "alice")
    d.to("stopped", "never started")
    assert SV.recover(PRIVATE) == [rid]
    assert SV.RunRecord(PRIVATE / rid, rid, "alice").state == "interrupted"
    assert SV.RunRecord(PRIVATE / done, done, "alice").state == "stopped"
    with raises(ValueError):
        SV.RunRecord(PRIVATE / done, done, "alice").to("running")          # ended is ended


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok ", name)
