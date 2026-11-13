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


def test_runs_get_the_gateways_llm_key_and_no_other_credential():
    from openmhp import harness as H
    keep = {k: os.environ.get(k) for k in ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")}
    os.environ.update(ANTHROPIC_AUTH_TOKEN="operator-login", ANTHROPIC_API_KEY="operator-key", CLAUDE_CODE_OAUTH_TOKEN="x")
    try:
        env = H.run_environment({"ANTHROPIC_API_KEY": "gateway-runs-key", "OPENMHP_RUN_ID": "R-1"})
        assert env["ANTHROPIC_API_KEY"] == "gateway-runs-key" and "ANTHROPIC_AUTH_TOKEN" not in env
        assert "CLAUDE_CODE_OAUTH_TOKEN" not in env and env["OPENMHP_RUN_ID"] == "R-1" and env.get("PATH")
        assert "ANTHROPIC_API_KEY" not in H.run_environment({})
    finally:
        for k, v in keep.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    f = Path(tempfile.mkdtemp()) / "llm.env"
    f.write_text("# runs\nANTHROPIC_API_KEY = sk-test\n\nbad line\n")
    assert H.llm_env(f) == {"ANTHROPIC_API_KEY": "sk-test"} and H.llm_env(f.with_name("none")) == {}

    # a Claude Code run cannot be proposed on a gateway without a key for runs
    from openmhp import gateway as G

    class FakeGW:
        state, allocated, supervisor = {}, {}, None
    sup = SV.Supervisor(FakeGW(), lab_root=S.lab_root(), runs_dir=Path(tempfile.mkdtemp()) / "runs")
    S.create("kim")
    rid = S.open_run("kim")["id"]
    ch = {"version": 1, "run": rid, "owner": "kim", "objective": "x", "instruments": {"tc": "bench/thermocycler-01"},
          "envelope": {"tc": {"actions": {}, "settings": {}}}}
    with raises(ValueError) as e:
        sup.propose(rid, "kim", ch, harness="claude-code")
    assert "mhp gateway llm-key" in str(e.value)
    (sup.runs_dir.parent / "llm.env").write_text("ANTHROPIC_API_KEY=sk-test\n")
    assert sup.propose(rid, "kim", ch, harness="claude-code").startswith("sha256:")


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


AGENT = """
import json, os, ssl, sys, urllib.request
# A stand-in run agent. It reads the run's MCP configuration the supervisor wrote, as a real harness would, and
# drives the gateway with the run token: an instrument setting, a report, a question, then finish when answered.
args = sys.argv[1:]
session, work, prompt = args[args.index("--session") + 1], args[args.index("--workdir") + 1], args[-1]
env = json.load(open(os.path.join(work, ".mcp-run.json")))["mcpServers"]["run"]["env"]
ctx = ssl.create_default_context(cafile=env["SSL_CERT_FILE"]); ctx.check_hostname = False
def post(path, body):
    req = urllib.request.Request(env["OPENMHP_GATEWAY"] + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": "Bearer " + env["OPENMHP_RUN_TOKEN"], "Content-Type": "application/json"})
    with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
        return json.loads(r.read())
charter = json.load(open(os.path.join(work, "..", "charter.json")))
with open(os.path.join(work, "turns.log"), "a") as f:
    f.write(prompt.replace("\\n", " | ") + "\\n")
if "] start:" in prompt:
    rpc = {"jsonrpc": "2.0", "id": 1, "method": "settings/write", "params": {"name": "target_temperature", "value": 30}}
    print(post("/bench/thermocycler-01/rpc", rpc), file=sys.stderr)
    open(os.path.join(work, "out", "data.csv"), "w").write("cell,retention\\n1,0.94\\n")
    open(os.path.join(work, "notebook.md"), "a").write("set block to 30 C\\n")
    post("/runs/report", {"text": "block at 30 C"})
    if "ask" in charter["objective"]:
        post("/runs/ask_scientist", {"question": "Cell 4 lost 40 % in 30 cycles: real, or re-make it?",
                                     "meanwhile": "wait", "needs_lab": True})
if "] answer:" in prompt:
    post("/runs/finish", {"summary": "best: 1.4 M with 2 % additive", "outcome": "objective met",
                          "next_experiments": ["narrow additive to 1.5-2.5 %"]})
if "] stop:" in prompt:
    open(os.path.join(work, "out", "cleanup.txt"), "w").write("block to 4 C, lid closed\\n")
print(json.dumps({"ok": True, "session": session, "text": "done", "cost_usd": 0.02, "tokens": 50}))
"""


def wait_until(pred, timeout=30, what="condition"):
    import time
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return
        time.sleep(0.1)
    raise TimeoutError(what)


def test_supervised_run_from_approval_to_results():
    import io
    from openmhp import gateway as G, gw_shell as GW, harness as H
    from tests.gw_lab import start_lab
    lab = start_lab()
    if lab is None:
        print("skip: openssl is needed for the gateway's certificate")
        return
    gw, drivers, rpc, get, node, base, ctx = lab
    agent = Path(tempfile.mkdtemp(prefix="agent-")) / "agent.py"
    agent.write_text(AGENT)
    sup = SV.Supervisor(gw, lab_root=S.lab_root(), runs_dir=G.RUNS_DIR,
                        adapters={"stand-in": H.Command([sys.executable, str(agent)])}, poll_s=0.1)
    sup.start()

    def gw_cmd(command, stdin=""):
        out = io.StringIO()
        code = GW.Shell("alice", out=out, env={"SSH_ORIGINAL_COMMAND": command}, stdin=io.StringIO(stdin), wait_s=30).run()
        return code, json.loads(out.getvalue())

    def charter(rid, objective):
        return {"version": 1, "run": rid, "owner": "alice", "objective": objective, "autonomy": "act",
                "instruments": {"tc": "bench/thermocycler-01"},
                "envelope": {"tc": {"settings": {"target_temperature": {"min": 4, "max": 99}}, "actions": {}}},
                "cleanup": "block to 4 C"}

    # ---- run 1: approve, the agent works and asks, the scientist answers, the agent finishes ----------
    code, ans = gw_cmd("mhp-gw open")
    rid = ans["run"]
    skill = S.run_folder("alice", rid) / "in" / "bo" / "cycling-analysis"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: cycling-analysis\n---\n")
    with raises(ValueError):
        sup.propose(rid, "alice", charter(rid, "x"), harness="no-such-harness")
    digest = sup.propose(rid, "alice", charter(rid, "find the best electrolyte; ask about odd cells"), harness="stand-in")
    code, ans = gw_cmd(f"mhp-gw show {rid}")
    assert code == GW.OK and ans["charter_digest"] == digest and "find the best electrolyte" in ans["charter"]
    assert ans["run"]["state"] == "waiting_approval"
    code, ans = gw_cmd(f"mhp-gw approve {rid} --charter-digest sha256:wrong")
    assert code == GW.REFUSED and "not the charter on record" in ans["error"]
    code, ans = gw_cmd(f"mhp-gw approve {rid} --charter-digest {digest}")
    assert code == GW.OK and ans["run"] == rid and "7 days" in ans["show_to_scientist"] and "go to the lab" in ans["show_to_scientist"]

    wait_until(lambda: sup.record(rid).state == "waiting_scientist", what="the agent's question")
    turn = next(e for e in sup.record(rid).events() if e["kind"] == "turn")
    assert turn["ok"] is True and turn["cost_usd"] == 0.02
    assert drivers["thermocycler-01"]._lease_holder() == f"alice/run-{rid}"
    work = S.run_folder("alice", rid) / "work"
    assert (work / ".claude" / "skills" / "cycling-analysis" / "SKILL.md").is_file()
    code, ans = gw_cmd(f"mhp-gw status {rid}")
    q = ans["run"]["open_questions"]
    assert list(q) == ["q1"] and q["q1"]["needs_lab"] is True and "Cell 4" in q["q1"]["question"]
    kinds = [json.loads(l)["kind"] for l in (S.run_folder("alice", rid) / "events.jsonl").read_text().splitlines()]
    assert "report" in kinds and "question" in kinds and "turn" in kinds
    code, ans = gw_cmd(f"mhp-gw answer {rid} q9 nope")
    assert code == GW.NOT_FOUND
    code, ans = gw_cmd(f"mhp-gw answer {rid} q1", stdin="real result: keep it, note it in the report")
    assert code == GW.OK and ans["answered"] == "q1"

    wait_until(lambda: sup.record(rid).state == "finished", what="the agent to finish")
    out = S.run_folder("alice", rid) / "out"
    assert "best: 1.4 M" in (out / "report.md").read_text() and "narrow additive" in (out / "report.md").read_text()
    assert (out / "data.csv").is_file() and "set block to 30 C" in (out / "notebook.md").read_text()
    assert drivers["thermocycler-01"]._lease_holder() is None and rid not in gw.allocated
    assert gw.gate_for("Bearer x") is None and not any(e["run"] == rid for e in gw.state.get("run_tokens", {}).values())
    turns = (work / "turns.log").read_text().splitlines()
    assert "] start:" in turns[0] and "answered your question q1" in turns[-1]

    # ---- run 2: instrument news wakes the agent; the scientist stops the run; cleanup runs first ---------
    code, ans = gw_cmd("mhp-gw open")
    rid2 = ans["run"]
    d2 = sup.propose(rid2, "alice", charter(rid2, "hold the block"), harness="stand-in")
    assert gw_cmd(f"mhp-gw approve {rid2} --charter-digest {d2}")[0] == GW.OK
    wait_until(lambda: sup.record(rid2).state == "running" and any(e["kind"] == "turn" for e in sup.record(rid2).events()),
               what="first turn of run 2")
    gw.events(gw.nodes["bench"], {"events": [{"device": "thermocycler-01",
                                              "event": {"method": "notifications/jobs/finished", "params": {"job": {"id": "j1"}}}}]})
    work2 = S.run_folder("alice", rid2) / "work"
    wait_until(lambda: "instrument:" in (work2 / "turns.log").read_text(), what="a wake on instrument news")
    code, ans = gw_cmd(f"mhp-gw message {rid2} keep it at 30 C overnight")
    assert code == GW.OK
    code, ans = gw_cmd(f"mhp-gw stop {rid2}")
    assert code == GW.OK and ans["state"] == "stopped"
    assert (S.run_folder("alice", rid2) / "out" / "cleanup.txt").is_file()
    assert drivers["thermocycler-01"]._lease_holder() is None
    code, ans = gw_cmd(f"mhp-gw message {rid2} hello?")
    assert code == GW.REFUSED and "stopped" in ans["error"]
    sup.stop_event.set()
    node.close()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok ", name)
