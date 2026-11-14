"""A lab gateway to talk to from another terminal, with a live feed of everything that reaches it.

    python examples/gateway_closed_loop/playground.py            the gateway's agents are scripted (free)
    python examples/gateway_closed_loop/playground.py --claude   runs asking for --harness claude-code use
                                                                 Claude Code with this machine's sign-in (costs money)

It starts a gateway, a lab PC 'bench' serving a simulated chromatograph (gc-01), and the run supervisor, makes
the scientist 'alice', and prints, as they happen:

    scientist   every command and file copy from alice's machine
    state/asks  each run's state changes and questions; answers, reports, the end of a run
    agent       the gateway's agent waking up and finishing a turn (cost, and what it said)
    instrument  every call to an instrument; dry runs and refusals are marked

In a second terminal, be alice's machine:

    export PATH="<printed bin folder>:$PATH"
    ssh mhp-gateway mhp-gw open
    rsync -a examples/gateway_closed_loop/handover/gc-separation-loop/ mhp-gateway:runs/<run id>/in/gc-separation-loop/
    ssh mhp-gateway mhp-gw request <run id> < examples/gateway_closed_loop/request.md

or let a real agent be alice's (scientist_agent.py). `ssh` and `rsync` in that folder are stand-ins: they reach
this gateway on this machine as the gateway's SSH server would, running mhp-gw as alice's forced command.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import shutil
import socket
import stat
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
COLOR = {"scientist": "\033[1;36m", "asks": "\033[1;33m", "answer": "\033[1;32m", "state": "\033[1;35m",
         "dim": "\033[2m", "end": "\033[0m"}

SSH = """#!/usr/bin/env bash
# Stands in for ssh to the lab gateway: its SSH server runs mhp-gw as this scientist's forced command, with the
# words after the host joined by spaces in SSH_ORIGINAL_COMMAND, exactly as here.
while [[ "$1" == -* ]]; do case "$1" in -[lpioFJcmbe]) shift 2;; *) shift;; esac; done
host="$1"; shift
if [[ "$host" != "mhp-gateway" ]]; then echo "ssh: this playground knows only the host mhp-gateway" >&2; exit 255; fi
[[ "$1" == "mhp-gw" ]] && shift
exec "$(dirname "$0")/mhp-gw" "$@"
"""
MHP_GW = """#!/usr/bin/env bash
echo "$(date +%H:%M:%S) mhp-gw $*" >> {log}
export OPENMHP_HOME={home} OPENMHP_LAB_ROOT={lab} OPENMHP_NO_UPDATE_CHECK=1 PYTHONPATH={repo}
SSH_ORIGINAL_COMMAND="mhp-gw $*" exec {python} -m openmhp.gw_shell --scientist alice
"""
RSYNC = """#!/usr/bin/env bash
# Stands in for rsync to the lab gateway: mhp-gateway:<path> is <path> in alice's folder on the gateway.
# (The real gateway also limits copies to runs/<id>/in/, preview/ and out/; tests/test_gateway_runs.py covers it.)
args=(); remote=""
for a in "$@"; do
  if [[ "$a" == mhp-gateway:* ]]; then p="${{a#mhp-gateway:}}"; p="${{p#\\~/}}"; args+=({folder}/"$p"); remote="$p"
  else args+=("$a"); fi
done
if [[ -n "$remote" ]]; then
  echo "$(date +%H:%M:%S) rsync $*" >> {log}
  [[ "$remote" == runs/*/in/* ]] && mkdir -p "${{args[${{#args[@]}}-1]}}"      # bash 3.2 (macOS) has no [-1]
fi
exec {rsync} "${{args[@]}}"
"""
MHP = """#!/usr/bin/env bash
case "$1 $2" in
  "agent "|"agent status") echo "paired with the lab gateway (playground) as 'alice-laptop'"
     echo "SSH access: host mhp-gateway, working as scientist 'alice'  (try: ssh mhp-gateway mhp-gw help)";;
  "agent inbox") echo "no unread news from the lab gateway";;
  *) echo "mhp $*: not part of this playground" >&2; exit 2;;
esac
"""


def _q(p) -> str:
    return "'" + str(p).replace("'", "'\\''") + "'"


def write_bin(home: Path, folder: Path) -> Path:
    """The scientist machine's stand-ins for ssh, rsync and mhp, and mhp-gw itself."""
    b = home / "bin"
    b.mkdir(parents=True, exist_ok=True)
    real_rsync = shutil.which("rsync") or "rsync"
    files = {"ssh": SSH, "mhp": MHP,
             "mhp-gw": MHP_GW.format(log=_q(home / "commands.log"), home=_q(home), lab=_q(home / "lab"), repo=_q(REPO),
                                     python=_q(sys.executable)),
             "rsync": RSYNC.format(log=_q(home / "commands.log"), folder=_q(folder), rsync=_q(real_rsync))}
    for name, text in files.items():
        (b / name).write_text(text, encoding="utf-8")
        (b / name).chmod((b / name).stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return b


def start(home: Path | None = None, claude: bool = False, feed: bool = True):
    """Start the gateway, the lab PC and the supervisor. Returns (home, bin folder, stop)."""
    home = Path(home or tempfile.mkdtemp(prefix="openmhp-playground-"))
    os.environ["PYTHONPATH"] = os.pathsep.join([str(REPO)] + [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p])
    os.environ.update(OPENMHP_HOME=str(home), OPENMHP_LAB_ROOT=str(home / "lab"), OPENMHP_NO_UPDATE_CHECK="1",
                      OPENMHP_NO_NOTIFY="1", OPENMHP_SIM_TIME_SCALE=os.environ.get("OPENMHP_SIM_TIME_SCALE", "0.002"))
    sys.path.insert(0, str(REPO))
    from openmhp import gateway as G, harness as H, relay as R, scientists as S
    from openmhp.package import load_driver
    from openmhp.supervisor import Supervisor

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
    stand_in = H.Command([sys.executable, str(HERE / "scripted_agent.py")])
    sup = Supervisor(gw, lab_root=S.lab_root(), runs_dir=G.RUNS_DIR, poll_s=0.2, local_login=claude,
                     adapters={"scripted": stand_in, "claude-code": H.ClaudeCode() if claude else stand_in})
    sup.start()
    S.create("alice")
    (home / "commands.log").write_text("")
    b = write_bin(home, S.folder("alice"))
    stop = threading.Event()
    if feed:
        _watch_instruments(gw)
        threading.Thread(target=_feed, args=(home, G.RUNS_DIR, stop), daemon=True).start()

    def close():
        stop.set()
        sup.stop_event.set()
        node.close()
        srv.shutdown()
    return home, b, port, close


def show(tag: str, color: str, text: str) -> None:
    print(f"{time.strftime('%H:%M:%S')} {COLOR[color]}{tag:<10}{COLOR['end']} {text}", flush=True)


def _watch_instruments(gw) -> None:
    """Print every call the gateway relays to an instrument; repeated job polls are shown once."""
    relay, last = gw.relay, {}

    def logged(node, device, kind, body, client, timeout):
        status, out = relay(node, device, kind, body, client, timeout)
        if isinstance(body, dict) and body.get("method"):
            p = body.get("params") or {}
            err = (out.get("error") or {}).get("message") if isinstance(out, dict) else None
            line = f"{node.name}/{device} {body['method']} {p.get('name') or ''}{' (dry run)' if p.get('dryRun') else ''}"
            if body["method"] == "jobs/status" and not err and last.get(device) == line:
                return status, out
            last[device] = line
            show("instrument", "dim", line + (f" -> REFUSED: {err}" if err else " -> ok"))
        return status, out
    gw.relay = logged


def _feed(home: Path, runs_dir: Path, stop: threading.Event) -> None:
    log, pos, seen = home / "commands.log", 0, {}
    while not stop.is_set():
        text = log.read_text(encoding="utf-8") if log.is_file() else ""
        for line in text[pos:].splitlines():
            show("scientist", "scientist", line.split(" ", 1)[-1])
        pos = len(text)
        for f in sorted(runs_dir.glob("*/events.jsonl")) if runs_dir.is_dir() else []:
            lines = f.read_text(encoding="utf-8").splitlines()
            for raw in lines[seen.get(f, 0):]:
                try:
                    e = json.loads(raw)
                except ValueError:
                    continue
                k, rid = e.get("kind"), e.get("run", f.parent.name)
                if k == "state":
                    show("state", "state", f"{rid}: {e.get('previous')} -> {e['state']}  ({e.get('why', '')})")
                elif k == "question":
                    show("asks", "asks", f"{rid} {e['id']}: {e['question']}")
                elif k in ("answer", "message"):
                    show(k, "answer", f"{rid} {e.get('id', '')}: {e['text']}")
                elif k == "wake":
                    show("agent", "state", f"{rid}: woken by {', '.join(e['triggers'])}")
                elif k == "turn":
                    show("agent", "state", f"{rid}: turn done (${e.get('cost_usd', 0):.2f}) said: {(e.get('said') or '')[:300]}")
                elif k in ("report", "plan_notes"):
                    show(k, "answer", f"{rid}: {e.get('text') or e.get('notes', '')}")
                elif k == "finish":
                    show("finish", "answer", f"{rid} ({e.get('outcome')}): {e.get('summary')}")
                else:
                    rest = {a: b for a, b in e.items() if a not in ("at", "ts", "run", "kind")}
                    show(k, "dim", f"{rid}: {json.dumps(rest)[:300]}")
            seen[f] = len(lines)
        time.sleep(0.3)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--claude", action="store_true",
                    help="runs asking for --harness claude-code use Claude Code signed in on this machine (costs money)")
    a = ap.parse_args()
    home, b, port, close = start(claude=a.claude)
    (home / "playground.json").write_text(json.dumps({"bin": str(b), "port": port}))
    print(f"gateway up on https://127.0.0.1:{port}; lab PC 'bench' serves gc-01 (a simulated GC); scientist: alice")
    print("gateway agents: " + ("Claude Code for --harness claude-code (costs money), scripted otherwise" if a.claude
                                else "the scripted stand-in for every harness (free)"))
    print(f"\nin another terminal, be alice's machine:\n  export PATH=\"{b}:$PATH\"\n  ssh mhp-gateway mhp-gw help")
    print(f"\nor let a real agent be alice's (costs money):\n  python {HERE / 'scientist_agent.py'} {home}\n\nCtrl-C to stop.\n",
          flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        close()
        print("stopped")


if __name__ == "__main__":
    main()
