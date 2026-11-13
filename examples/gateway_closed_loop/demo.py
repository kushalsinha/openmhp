"""Closed-loop demo: a scientist asks a lab gateway, in plain English, to optimise a GC separation with their
own optimizer; the gateway plans, asks, rehearses, gets approval, runs the loop on a simulated chromatograph,
and the results come home. Everything runs on this machine, in a temporary folder:

    python examples/gateway_closed_loop/demo.py                       a scripted agent (free, no model)
    python examples/gateway_closed_loop/demo.py --harness claude-code Claude Code as the planner and run agent
                                                                      (needs ANTHROPIC_API_KEY; it costs money)

What is real: the gateway, its charter checks, the run token, the supervisor, the lab PC relaying a simulated
chromatograph, mhp-gw (called as the gateway's SSH forced command would call it), the manifest check and the
acknowledgement. What stands in: SSH itself (commands are handed to mhp-gw directly; files are copied rather than
sent with rsync), and, unless --harness claude-code, the agent.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent


def setup_env(home: Path) -> None:
    os.environ.update(OPENMHP_HOME=str(home), OPENMHP_LAB_ROOT=str(home / "lab"), OPENMHP_NO_UPDATE_CHECK="1",
                      OPENMHP_NO_NOTIFY="1", OPENMHP_SIM_TIME_SCALE=os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.002"))
    sys.path.insert(0, str(REPO))


def run(harness: str = "scripted", home: Path | None = None, quiet: bool = False) -> dict:
    home = Path(home or tempfile.mkdtemp(prefix="openmhp-demo-"))
    setup_env(home)
    from openmhp import gateway as G, gw_shell as GW, harness as H, relay as R, scientists as S, watcher as W
    from openmhp.package import load_driver
    from openmhp.supervisor import Supervisor

    def tell(who: str, text: str) -> None:
        if not quiet:
            print(f"{who:>10} | {text}", flush=True)

    # ---- the gateway, a lab PC with a simulated chromatograph, and the supervisor --------------------
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0))
        port = so.getsockname()[1]
    with contextlib.redirect_stderr(io.StringIO()):
        if G.init(server_name="127.0.0.1", listen=port) != 0:
            raise SystemExit("could not make the gateway (is openssl installed?)")
        G.pair()
    gw = G.Gateway(G.load())
    srv = G.make_server(gw, "127.0.0.1", port)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    gc = load_driver(str(REPO / "openmhp" / "devices" / "gc-01"))
    code = next(iter(G.load()["codes"]))
    with contextlib.redirect_stderr(io.StringIO()):
        node = R.RelayClient(R.join(f"https://127.0.0.1:{port}", code, {"gc-01": gc}, name="bench", quiet=True), {"gc-01": gc})
        node.start()
    end = time.time() + 15
    while time.time() < end and "gc-01" not in getattr(gw.nodes.get("bench"), "devices", {}):
        time.sleep(0.05)
    adapters = {"scripted": H.Command([sys.executable, str(HERE / "scripted_agent.py")]), "claude-code": H.ClaudeCode()}
    sup = Supervisor(gw, lab_root=S.lab_root(), runs_dir=G.RUNS_DIR, adapters=adapters, poll_s=0.1)
    if harness == "claude-code":
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise SystemExit("--harness claude-code needs ANTHROPIC_API_KEY (the gateway's key for runs)")
        (G.GW_DIR / "llm.env").write_text(f"ANTHROPIC_API_KEY={key}\n")
        os.chmod(G.GW_DIR / "llm.env", 0o600)
    sup.start()
    S.create("alice")
    tell("gateway", f"up on https://127.0.0.1:{port}; lab PC 'bench' serves a simulated chromatograph (gc-01)")

    # ---- the scientist's side: mhp-gw as the SSH forced command runs it --------------------------------
    def gw_cmd(command: str, stdin: str = "") -> dict:
        out = io.StringIO()
        GW.Shell("alice", out=out, env={"SSH_ORIGINAL_COMMAND": command}, stdin=io.StringIO(stdin), wait_s=120).run()
        return json.loads(out.getvalue())

    request = (HERE / "request.md").read_text()
    tell("scientist", request.replace("\n", " ").strip())
    rid = gw_cmd("mhp-gw open")["run"]
    shutil.copytree(HERE / "handover", S.run_folder("alice", rid) / "in", dirs_exist_ok=True)
    tell("agent", f"opened run {rid}, handed over gc-separation-loop, sent the request")
    gw_cmd(f"mhp-gw request {rid} --harness {harness}", request)

    since, digest, answered = 0.0, None, set()
    deadline = time.time() + 1800
    while digest is None and time.time() < deadline:
        ans = gw_cmd(f"mhp-gw wait {rid} --since {since} --timeout 60")
        since = ans.get("since", since)
        for qid, q in (ans.get("open_questions") or {}).items():
            if qid in answered:
                continue
            tell("gateway", f"asks: {q['question']}")
            reply = "Yes, exactly those four, and 10 uL in total is fine."
            tell("scientist", reply)
            gw_cmd(f"mhp-gw answer {rid} {qid}", reply)
            answered.add(qid)
        if ans.get("state") == "waiting_approval":
            shown = gw_cmd(f"mhp-gw show {rid}")
            digest = shown["charter_digest"]
            tell("agent", "the charter to approve:\n" + "\n".join("           | " + l for l in shown["charter"].splitlines()[:30]))
            preview = S.run_folder("alice", rid) / "preview"
            tell("agent", "preview files: " + ", ".join(sorted(p.name for p in preview.iterdir())) if preview.is_dir() else "no preview")
    if digest is None:
        raise SystemExit("the planner did not propose a charter in time")
    tell("scientist", "Approve.")
    started = gw_cmd(f"mhp-gw approve {rid} --charter-digest {digest}")
    tell("agent", started.get("show_to_scientist", json.dumps(started)))

    # ---- the run: watch until it ends, then bring the results home, check them, acknowledge ----------
    while time.time() < deadline:
        meta = S.load_run("alice", rid)
        if meta["state"] in ("finished", "stopped", "failed"):
            break
        for ev in gw_cmd(f"mhp-gw wait {rid} --since {since} --timeout 30").get("events", []):
            since = max(since, ev["ts"])
            if ev["kind"] == "report":
                tell("run", ev["text"])
    meta = S.load_run("alice", rid)
    home_dir = home / "results" / rid
    shutil.copytree(S.run_folder("alice", rid) / "out", home_dir, dirs_exist_ok=True)
    bad = W.verify(home_dir)
    ack = gw_cmd(f"mhp-gw ack {rid}") if not bad else {"ok": False, "error": bad}
    report = (home_dir / "report.md").read_text() if (home_dir / "report.md").is_file() else ""
    tell("agent", f"run {rid} {meta['state']}; results in {home_dir} ({'verified' if not bad else 'NOT intact: ' + str(bad)})")
    for line in report.splitlines():
        if line.strip():
            tell("report", line)
    history = json.loads((home_dir / "history.json").read_text()) if (home_dir / "history.json").is_file() else []
    best = json.loads((home_dir / "best.json").read_text()) if (home_dir / "best.json").is_file() else None
    end = time.time() + 10
    while time.time() < end and not (S.load_run("alice", rid) or {}).get("purged"):
        time.sleep(0.1)
    sup.stop_event.set()
    node.close()
    return {"run": rid, "state": meta["state"], "injections": len(history), "best": best, "verified": not bad,
            "acknowledged": bool(ack.get("ok")), "purged": bool((S.load_run("alice", rid) or {}).get("purged")),
            "lease_after": gc._lease_holder(), "spent_usd": meta.get("spent_usd", 0.0), "home": str(home)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--harness", default="scripted", choices=["scripted", "claude-code"])
    a = ap.parse_args()
    out = run(a.harness)
    print(json.dumps(out, indent=1))
