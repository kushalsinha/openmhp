"""The scientist's machine hears about its runs and brings results home: `mhp-gw watch` streamed through a
stand-in for ssh, the inbox, real rsync of the results with a checked manifest, the acknowledgement, and the
gateway deleting its copy (on acknowledgement, or after 7 days).

    PYTHONPATH=. python tests/test_gateway_watcher.py
"""
import io
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, ".")
os.environ["OPENMHP_HOME"] = tempfile.mkdtemp(prefix="openmhp-watch-")
os.environ["OPENMHP_LAB_ROOT"] = str(Path(os.environ["OPENMHP_HOME"]) / "lab")
os.environ["OPENMHP_RESULTS"] = str(Path(os.environ["OPENMHP_HOME"]) / "results")
os.environ["OPENMHP_NO_UPDATE_CHECK"] = "1"
os.environ["OPENMHP_NO_NOTIFY"] = "1"

from openmhp import scientists as S, supervisor as SV                       # noqa: E402

FAKE_SSH = """#!{python}
import os, sys
args, i = sys.argv[1:], 0
while i < len(args) and args[i].startswith("-"):
    i += 2 if args[i] in ("-l", "-p", "-i", "-o", "-F", "-J", "-c", "-m", "-b", "-e") else 1
env = dict(os.environ, SSH_ORIGINAL_COMMAND=" ".join(args[i + 1:]), PYTHONPATH={cwd!r})
os.execve({python!r}, [{python!r}, "-m", "openmhp.gw_shell", "--scientist", "mo", "--root", {root!r}], env)
"""

AGENT = r'''
import json, os, ssl, sys, urllib.request
args = sys.argv[1:]
session, work, prompt = args[args.index("--session") + 1], args[args.index("--workdir") + 1], args[-1]
env = json.load(open(os.path.join(work, ".mcp-run.json")))["mcpServers"]["run"]["env"]
ctx = ssl.create_default_context(cafile=env["SSL_CERT_FILE"]); ctx.check_hostname = False
def post(path, body):
    req = urllib.request.Request(env["OPENMHP_GATEWAY"] + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": "Bearer " + env["OPENMHP_RUN_TOKEN"], "Content-Type": "application/json"})
    with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
        return json.loads(r.read())
if "] start:" in prompt:
    os.makedirs(os.path.join(work, "out", "cells"), exist_ok=True)
    open(os.path.join(work, "out", "cells", "cell1.csv"), "w").write("cycle,capacity\n1,1.00\n50,0.94\n")
    post("/runs/ask_scientist", {"question": "Cell 4 looks unseated. Can someone re-seat it?", "meanwhile": "wait", "needs_lab": True})
if "] answer:" in prompt:
    post("/runs/finish", {"summary": "retention 94 % at 50 cycles", "outcome": "objective met"})
print(json.dumps({"ok": True, "session": session, "text": "done", "cost_usd": 0.0, "tokens": 0}))
'''


def wait_until(pred, timeout=40, what="condition", tick=None):
    end = time.time() + timeout
    while time.time() < end:
        if tick:
            tick()
        if pred():
            return
        time.sleep(0.1)
    raise TimeoutError(what)


def test_news_reaches_the_inbox_and_results_come_home():
    if os.name == "nt" or not shutil.which("rsync"):
        print("skip: needs rsync")
        return
    from openmhp import gateway as G, gw_shell as GW, harness as H, watcher as W
    from openmhp.mcp_bridge import inbox_notice
    from tests.gw_lab import start_lab
    lab = start_lab()
    if lab is None:
        print("skip: openssl is needed for the gateway's certificate")
        return
    gw, drivers, rpc, get, node, base, ctx = lab
    tmp = Path(tempfile.mkdtemp(prefix="watch-"))
    (tmp / "agent.py").write_text(AGENT)
    fake = tmp / "fakessh"
    fake.write_text(FAKE_SSH.format(python=sys.executable, root=str(S.lab_root()), cwd=os.getcwd()))
    fake.chmod(0o755)
    sup = SV.Supervisor(gw, lab_root=S.lab_root(), runs_dir=G.RUNS_DIR,
                        adapters={"stand-in": H.Command([sys.executable, str(tmp / "agent.py")])}, poll_s=0.1)
    sup.start()
    S.create("mo")
    w = W.Watcher(ssh=[str(fake)], host="gw")
    listen = lambda: w.run_once(for_s=1)

    rid = S.open_run("mo")["id"]
    charter = {"version": 1, "run": rid, "owner": "mo", "objective": "cycle cells", "instruments": {"tc": "bench/thermocycler-01"},
               "envelope": {"tc": {"actions": {}, "settings": {}}}}
    d = sup.propose(rid, "mo", charter, harness="stand-in")
    listen()
    assert any(n["kind"] == "charter_proposed" for n in W.unread())
    sup.approve(rid, d, "mo")

    # the run's question reaches the inbox, flagged as needing someone in the lab; the MCP server mentions it
    wait_until(lambda: any(n["kind"] == "question" for n in W.unread()), what="the question in the inbox", tick=listen)
    q = next(n for n in W.unread() if n["kind"] == "question")
    assert q["needs_lab"] is True and q["question"] == "q1" and "re-seat" in q["text"]
    assert any(n["kind"] == "started" for n in W.unread())
    assert "needing someone in the lab" in inbox_notice()
    seen = len(list(W.INBOX.glob("*.json")))
    listen()
    assert len(list(W.INBOX.glob("*.json"))) == seen                   # the cursor means nothing is told twice
    W.mark_read(W.unread())
    assert W.unread() == [] and inbox_notice() is None

    # answered: the run finishes, the results come home intact, and the gateway deletes its copy
    out = io.StringIO()
    assert GW.Shell("mo", out=out, env={"SSH_ORIGINAL_COMMAND": f"mhp-gw answer {rid} q1"},
                    stdin=io.StringIO("re-seated, carry on"), wait_s=30).run() == GW.OK
    home = W.results_root() / rid
    wait_until(lambda: (home / "report.md").is_file() and any(n["kind"] == "results" for n in W.unread()),
               what="results at home", tick=listen)
    assert (home / "cells" / "cell1.csv").read_text().endswith("50,0.94\n") and W.verify(home) == []
    wait_until(lambda: sup.record(rid).doc.get("purged"), what="the gateway deleting its copy")
    pub = S.run_folder("mo", rid)
    assert sorted(p.name for p in pub.iterdir() if p.name != "inbox") == ["events.jsonl", "meta.json"]
    kinds = [e["kind"] for e in sup.record(rid).events()]
    assert kinds.index("results_ready") < kinds.index("results_received") < kinds.index("results_deleted")

    # a damaged copy is noticed, never acknowledged
    (home / "cells" / "cell1.csv").write_text("tampered\n")
    assert W.verify(home) == ["cells/cell1.csv: changed"]

    # results nobody fetched are deleted 7 days after the run ended, not before
    rid2 = S.open_run("mo")["id"]
    d2 = sup.propose(rid2, "mo", {**charter, "run": rid2}, harness="stand-in")
    sup.approve(rid2, d2, "mo")
    wait_until(lambda: sup.record(rid2).state == "waiting_scientist", what="run 2 asking")
    sup.stop(rid2, "mo")
    ended = sup.record(rid2).doc["ended_ts"]
    assert rid2 not in sup.retention(now_ts=ended + 6 * 86400)
    assert rid2 in sup.retention(now_ts=ended + 8 * 86400)
    assert "not received" in [e for e in sup.record(rid2).events() if e["kind"] == "results_deleted"][0]["why"]
    sup.stop_event.set()
    node.close()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok ", name)
