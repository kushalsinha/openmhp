"""Planning a run on the gateway: the scientist's request in plain English, a planner that can look and rehearse
but not move anything, questions both ways, a preview, a charter proposed and revised, approval, and the run.
A stand-in plays the planner and the run agent; no real harness is started.

    PYTHONPATH=. python tests/test_gateway_planner.py
"""
import io
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, ".")
os.environ["OPENMHP_HOME"] = tempfile.mkdtemp(prefix="openmhp-plan-")
os.environ["OPENMHP_LAB_ROOT"] = str(Path(os.environ["OPENMHP_HOME"]) / "lab")
os.environ["OPENMHP_NO_UPDATE_CHECK"] = "1"

from openmhp import scientists as S, supervisor as SV                       # noqa: E402

AGENT = r'''
import json, os, ssl, sys, urllib.request, urllib.error
args = sys.argv[1:]
session, work, prompt = args[args.index("--session") + 1], args[args.index("--workdir") + 1], args[-1]
env = json.load(open(os.path.join(work, ".mcp-run.json")))["mcpServers"]["run"]["env"]
ctx = ssl.create_default_context(cafile=env["SSL_CERT_FILE"]); ctx.check_hostname = False
def post(path, body):
    req = urllib.request.Request(env["OPENMHP_GATEWAY"] + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": "Bearer " + env["OPENMHP_RUN_TOKEN"], "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")
def rpc(path, method, params):
    return post(path + "/rpc", {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})[1]
log = open(os.path.join(work, "agent.log"), "a")
def note(**kw):
    log.write(json.dumps(kw) + "\n"); log.flush()
TC = "/bench/thermocycler-01"
def charter(top):
    return {"objective": "hold the block warm for the assay", "autonomy": "act",
            "instruments": {"tc": "bench/thermocycler-01"},
            "envelope": {"tc": {"settings": {"target_temperature": {"min": 4, "max": top}}, "actions": {}}},
            "cleanup": "block to 4 C"}
planning = os.path.basename(work.rstrip("/")) == "plan"
note(phase="plan" if planning else "run", prompt=prompt.split("\n")[0][:80], venv=os.environ.get("VIRTUAL_ENV"))
if planning and "] plan:" in prompt:
    found = post("/directory/rpc", {"jsonrpc": "2.0", "id": 1, "method": "directory/search", "params": {"query": "robot arm"}})[1]
    note(sees_arm=any(r["id"] == "bench/arm-01" for r in found["result"]["results"]))
    note(dry=rpc(TC, "settings/write", {"name": "target_temperature", "value": 30, "dryRun": True}))
    note(real=rpc(TC, "settings/write", {"name": "target_temperature", "value": 30}))
    note(lease=rpc(TC, "session/acquire", {"ttl": 30}))
    note(ask=post("/runs/ask_scientist", {"question": "Which temperature, and for how long?", "meanwhile": "wait"}))
elif planning and ("] answer:" in prompt or "] message:" in prompt):
    os.makedirs(os.path.join(work, "preview"), exist_ok=True)
    open(os.path.join(work, "preview", "sample.csv"), "w").write("t_s,block_c\n0,22\n60,30\n")
    open(os.path.join(work, "preview", "README.md"), "w").write("Synthetic values within the descriptor's limits.\n")
    top = 60 if "60" in prompt else 99
    note(propose=post("/runs/propose_charter", {"charter": charter(top), "notes": f"warms the block; max {top} C"}))
    note(finish_as_planner=post("/runs/finish", {"summary": "x", "outcome": "objective met"})[0])
elif not planning and "] start:" in prompt:
    note(set=rpc(TC, "settings/write", {"name": "target_temperature", "value": 30}))
    note(too_hot=rpc(TC, "settings/write", {"name": "target_temperature", "value": 70}))
    note(propose_as_run=post("/runs/propose_charter", {"charter": charter(99), "notes": "x"})[0])
    os.makedirs(os.path.join(work, "out"), exist_ok=True)
    open(os.path.join(work, "out", "temps.csv"), "w").write("t_s,block_c\n0,30\n")
    post("/runs/finish", {"summary": "block held at 30 C", "outcome": "objective met"})
print(json.dumps({"ok": True, "session": session, "text": "done", "cost_usd": 0.01, "tokens": 10}))
'''


def wait_until(pred, timeout=40, what="condition"):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return
        time.sleep(0.1)
    raise TimeoutError(what)


def lines(path):
    return [json.loads(l) for l in Path(path).read_text().splitlines()] if Path(path).is_file() else []


def test_from_a_plain_english_request_to_a_finished_run():
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
    S.create("lee")

    def gw_cmd(command, stdin=""):
        out = io.StringIO()
        code = GW.Shell("lee", out=out, env={"SSH_ORIGINAL_COMMAND": command}, stdin=io.StringIO(stdin), wait_s=60).run()
        return code, json.loads(out.getvalue())

    code, ans = gw_cmd("mhp-gw open")
    rid = ans["run"]
    pub = S.run_folder("lee", rid)
    (pub / "in" / "analysis").mkdir(parents=True)
    (pub / "in" / "analysis" / "requirements.txt").write_text("# nothing to install for this test\n")
    assert gw_cmd(f"mhp-gw request {rid} --harness nope", "warm the block")[0] == GW.REFUSED
    code, ans = gw_cmd(f"mhp-gw request {rid} --harness stand-in", "Keep the thermocycler block warm for my assay.")
    assert code == GW.OK and ans["state"] == "planning", ans
    assert gw_cmd(f"mhp-gw request {rid} --harness stand-in", "again")[0] == GW.REFUSED      # one request per run

    # the planner's question reaches the scientist
    since, ans = 0, {}
    for _ in range(10):                                  # as an agent does: wait again from the last news it saw
        code, ans = gw_cmd(f"mhp-gw wait {rid} --since {since} --timeout 40")
        assert code == GW.OK, ans
        since = ans["since"]
        if "q1" in ans["open_questions"]:
            break
    assert "q1" in ans["open_questions"] and any(e["kind"] == "question" for e in ans["events"]), ans
    log = lines(pub / "plan" / "agent.log")
    first = {k: v for e in log for k, v in e.items()}
    assert first["phase"] == "plan" and first["venv"] and Path(first["venv"]).is_dir()      # the run's own environment
    assert first["sees_arm"] is True                                    # a planner looks at everything
    assert "result" in first["dry"]                                     # and rehearses
    assert first["real"]["error"]["data"]["charter"] == "planning"      # but nothing moves
    assert first["lease"]["error"]["data"]["charter"] == "planning"
    assert drivers["thermocycler-01"]._lease_holder() is None

    # the answer goes back; a charter and a preview come out
    assert gw_cmd(f"mhp-gw answer {rid} q1", "30 C for an hour")[0] == GW.OK
    code, ans = gw_cmd(f"mhp-gw wait {rid} --since {since} --timeout 40")
    wait_until(lambda: sup.record(rid).state == "waiting_approval", what="the charter")
    assert (pub / "preview" / "sample.csv").is_file() and "Synthetic" in (pub / "preview" / "README.md").read_text()
    assert "max 99 C" in (pub / "plan-notes.md").read_text()
    log = lines(pub / "plan" / "agent.log")
    assert any(e.get("finish_as_planner") == 403 for e in log)          # a planner cannot end a run
    code, ans = gw_cmd(f"mhp-gw show {rid}")
    first_digest = ans["charter_digest"]
    assert "4 to 99" in ans["charter"]

    # the scientist asks for a change: the planner revises
    assert gw_cmd(f"mhp-gw message {rid} please cap it at 60 C")[0] == GW.OK
    wait_until(lambda: sup.record(rid).state == "waiting_approval" and sup.record(rid).doc.get("charter_digest") != first_digest,
               what="a revised charter")
    code, ans = gw_cmd(f"mhp-gw show {rid}")
    assert "4 to 60" in ans["charter"]
    assert gw_cmd(f"mhp-gw approve {rid} --charter-digest {first_digest}")[0] == GW.REFUSED   # not the one on record
    code, ans = gw_cmd(f"mhp-gw approve {rid} --charter-digest {ans['charter_digest']}")
    assert code == GW.OK and rid in ans["show_to_scientist"], ans

    # the run works inside the revised charter and finishes
    wait_until(lambda: sup.record(rid).state == "finished", what="the run")
    run_log = [e for e in lines(pub / "work" / "agent.log")]
    got = {k: v for e in run_log for k, v in e.items()}
    assert got["phase"] == "run" and "result" in got["set"]
    assert got["too_hot"]["error"]["data"]["bounds"] == {"min": 4, "max": 60}
    assert got["propose_as_run"] == 403
    assert (pub / "out" / "temps.csv").is_file() and "block held at 30 C" in (pub / "out" / "report.md").read_text()
    assert drivers["thermocycler-01"]._lease_holder() is None
    assert not any(e["run"] == rid for e in gw.state.get("run_tokens", {}).values())

    # a planner that ends its turn with nothing proposed and nothing asked: what it said reaches the scientist
    quiet = agent.parent / "quiet.py"
    quiet.write_text("import json, sys\nargs = sys.argv[1:]\nprint(json.dumps({'ok': True, 'session': "
                     "args[args.index('--session') + 1], 'text': 'I could not submit the charter: the tool was denied.', "
                     "'cost_usd': 0.0, 'tokens': 1}))\n")
    sup.adapters["quiet"] = H.Command([sys.executable, str(quiet)])
    rid3 = gw_cmd("mhp-gw open")[1]["run"]
    assert gw_cmd(f"mhp-gw request {rid3} --harness quiet", "Warm the block.")[0] == GW.OK
    wait_until(lambda: sup.record(rid3).doc.get("open_questions"), what="the stalled planner's question")
    q = next(iter(sup.record(rid3).doc["open_questions"].values()))["question"]
    assert "without proposing" in q and "tool was denied" in q, q
    sup.stop_event.set()
    node.close()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok ", name)
