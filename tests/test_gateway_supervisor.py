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


STAND_IN = """
import json, sys
# A stand-in agent harness: remembers its session in the working folder and answers like an adapter expects.
args = sys.argv[1:]
session = args[args.index("--session") + 1]
workdir = args[args.index("--workdir") + 1]
prompt = args[-1]
with open(workdir + "/turns.log", "a") as f:
    f.write(session + " " + prompt + "\\n")
print(json.dumps({"ok": "fail" not in prompt, "session": session, "text": "did: " + prompt, "cost_usd": 0.01, "tokens": 100}))
sys.exit(1 if "fail" in prompt else 0)
"""


def test_harness_adapters():
    from openmhp import harness as H
    work = Path(tempfile.mkdtemp(prefix="run-work-"))
    turn = H.Turn(prompt="start the run", workdir=work, mcp_config=work / "mcp.json", instructions=work / "charter.md",
                  max_turns=30, max_budget_usd=2.5, model="opus")
    cc = H.ClaudeCode()
    first = cc.command(turn, "11111111-2222-3333-4444-555555555555", first=True)
    assert first[:3] == ["claude", "-p", "start the run"] and first[first.index("--output-format") + 1] == "json"
    assert first[first.index("--permission-mode") + 1] == "dontAsk"
    assert first[first.index("--session-id") + 1].startswith("1111") and "--resume" not in first
    assert "--strict-mcp-config" in first and first[first.index("--append-system-prompt-file") + 1].endswith("charter.md")
    assert first[first.index("--max-budget-usd") + 1] == "2.50" and first[first.index("--model") + 1] == "opus"
    allowed = first[first.index("--allowedTools") + 1].split(",")
    assert "Bash" in allowed and "mcp__openmhp__mhp_invoke" in allowed and "mcp__run__ask_scientist" in allowed
    assert "mcp__openmhp__mhp_lab" not in allowed                       # a run never adds or scans instruments
    later = cc.command(turn, "11111111-2222-3333-4444-555555555555", first=False)
    assert later[later.index("--resume") + 1].startswith("1111") and "--session-id" not in later
    assert "--append-system-prompt-file" not in later                  # kept with the session

    ok = cc.parse(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "done",
                              "session_id": "abc", "total_cost_usd": 0.42,
                              "usage": {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 100}}), "", 0, "x")
    assert ok.ok and ok.session == "abc" and ok.text == "done" and ok.cost_usd == 0.42 and ok.tokens == 115
    capped = cc.parse(json.dumps({"subtype": "error_max_turns", "is_error": True, "session_id": "abc"}), "", 1, "x")
    assert not capped.ok and capped.reason == "max_turns"
    assert cc.parse("", "Invalid API key", 1, "x").reason == "error"

    # skills the scientist handed over land where the harness finds them
    handed = work / "in"
    (handed / "bo" / "cycling-analysis").mkdir(parents=True)
    (handed / "bo" / "cycling-analysis" / "SKILL.md").write_text("---\nname: cycling-analysis\n---\n")
    (handed / "bo" / "notes.txt").write_text("not a skill")
    assert H.install_skills(handed, work) == ["cycling-analysis"]
    assert (work / ".claude" / "skills" / "cycling-analysis" / "SKILL.md").is_file()

    # a real turn through a stand-in harness: a session is assigned, then resumed
    stand = work / "stand_in.py"
    stand.write_text(STAND_IN)
    ad = H.Command([sys.executable, str(stand)])
    r1 = H.run_turn(ad, H.Turn(prompt="start", workdir=work))
    r2 = H.run_turn(ad, H.Turn(prompt="job finished", workdir=work, session=r1.session))
    assert r1.ok and r2.ok and r1.session == r2.session and r2.text == "did: job finished" and r2.cost_usd == 0.01
    log = (work / "turns.log").read_text().splitlines()
    assert [l.split(" ", 1)[0] for l in log] == [r1.session, r1.session]
    bad = H.run_turn(ad, H.Turn(prompt="fail please", workdir=work, session=r1.session))
    assert not bad.ok and bad.reason == "error"
    missing = H.run_turn(H.Command(["no-such-harness-here"]), H.Turn(prompt="x", workdir=work))
    assert not missing.ok and missing.reason == "not installed"


def test_a_run_scoped_bridge_cannot_add_or_scan_instruments():
    from openmhp.fleet import Fleet
    from openmhp.mcp_bridge import Bridge
    os.environ["OPENMHP_RUN_SCOPE"] = "1"
    try:
        b = Bridge(fleet=Fleet(os.path.join(os.environ["OPENMHP_HOME"], "fleet.json")))
        names = [t["name"] for t in b.tools()]
        assert "mhp_lab" not in names and "mhp_invoke" in names
        with raises(PermissionError):
            b.call_tool("mhp_lab", {"op": "scan"})
    finally:
        del os.environ["OPENMHP_RUN_SCOPE"]
    assert "mhp_lab" in [t["name"] for t in Bridge(fleet=Fleet(os.path.join(os.environ["OPENMHP_HOME"], "fleet2.json"))).tools()]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok ", name)
