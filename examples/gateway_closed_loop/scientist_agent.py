"""The scientist's side with a real agent: Claude Code as the agent on alice's laptop, knowing only the
openmhp-lab-gateway skill, and a scripted alice who talks to it in plain English. Run it against a playground:

    python examples/gateway_closed_loop/playground.py                        (terminal 1: the gateway and its feed)
    python examples/gateway_closed_loop/scientist_agent.py <playground home> [--budget 1.00]     (terminal 2)

It costs money: Claude Code runs with this machine's sign-in, up to the budget (Sonnet; a full run is about
$0.80). The gateway's own agents are scripted unless the playground was started with --claude.

Alice never types a command. She decides what to say from what the gateway shows (a question open, a plan
waiting, the run ended), as a person at the lab would. Her agent finds `ssh` and `rsync` stand-ins on its PATH
(the playground's bin folder), so every command it sends shows up in the gateway's feed. Note that results come
home where the skill says, ~/openmhp-runs/<run id>/, in the real home folder.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
B, D, X, G, Y, C = "\033[1m", "\033[2m", "\033[0m", "\033[1;32m", "\033[1;33m", "\033[1;36m"

OPENING = ("Hi! I need GC conditions that separate ethanol from isopropanol, resolution at least 1.5 between every "
           "neighbouring peak, for my solvent mix of acetone, ethanol, isopropanol and toluene, with the shortest run "
           "time you can get. The lab may vary the carrier flow from 0.5 to 5 mL/min and the oven ramp from 2 to 40 "
           "C/min; keep injections at 1 uL and use at most 10 injections. My optimizer is in "
           "projects/gc-separation-loop, please have the lab use it to pick each next condition. Can you get the "
           "lab gateway to run this?")
ANSWER = ("Yes: the sample is exactly those four, acetone, ethanol, isopropanol and toluene. 1 uL per injection, and up "
          "to 10 uL in total is fine. Nobody needs to be in the lab and no bake-out, please.")


class Alice:
    def __init__(self, home: Path):
        self.runs = home / "lab" / "scientists" / "alice" / "runs"
        self.approved_at: float | None = None

    def run(self) -> dict | None:
        metas = [json.loads(p.read_text()) for p in self.runs.glob("*/meta.json")] if self.runs.is_dir() else []
        return max(metas, key=lambda m: m.get("created", ""), default=None)

    def says(self, step: int) -> str | None:
        m = self.run()
        if step == 0:
            return OPENING
        if m is None:
            return "Yes, that's right, please go ahead and send it."
        if m.get("open_questions"):
            return ANSWER
        if m["state"] in ("open", "planning"):
            return "OK. Let me know when the lab has a plan."
        if m["state"] == "waiting_approval":
            if self.approved_at:
                return "I said yes. Please approve it."
            self.approved_at = time.time()
            return "That plan looks right to me. Yes, approve it as written."
        if m["state"] in ("queued", "running", "waiting_scientist"):
            return "Great. Please keep an eye on it and tell me when it's done."
        if not m.get("acked"):
            return "Please bring the results home to my laptop, check them, and tell me the best condition it found."
        return None                                                    # results are home: the conversation is over


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("home", type=Path, help="the playground's folder (playground.py prints it)")
    ap.add_argument("--budget", type=float, default=1.00, help="the most to spend on alice's agent, in USD")
    ap.add_argument("--model", default="sonnet")
    a = ap.parse_args()
    home = a.home.resolve()
    if not (home / "bin" / "ssh").is_file():
        raise SystemExit(f"{home} is not a running playground (start examples/gateway_closed_loop/playground.py)")
    if not shutil.which("claude"):
        raise SystemExit("this needs Claude Code (`claude`) on PATH, signed in")

    laptop = home / "alice-laptop"
    shutil.rmtree(laptop, ignore_errors=True)
    shutil.copytree(REPO / "openmhp" / "skills" / "openmhp-lab-gateway", laptop / ".claude" / "skills" / "openmhp-lab-gateway")
    shutil.copytree(HERE / "handover" / "gc-separation-loop", laptop / "projects" / "gc-separation-loop")
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT")}
    env["PATH"] = f"{home / 'bin'}{os.pathsep}{env['PATH']}"
    alice, session, spent, transcript = Alice(home), str(uuid.uuid4()), 0.0, []

    def turn(text: str) -> str:
        nonlocal spent
        cmd = ["claude", "-p", text, "--output-format", "stream-json", "--verbose", "--model", a.model,
               "--permission-mode", "dontAsk", "--allowedTools", "Bash,Read,Write,Edit,Glob,Grep,Skill",
               "--max-budget-usd", f"{a.budget - spent:.2f}"]
        cmd += (["--session-id", session, "--append-system-prompt",
                 "You are the assistant on alice's laptop. Alice is a chemist and talks to you in plain English. "
                 "This laptop is paired with her lab's gateway."] if not transcript else ["--resume", session])
        p = subprocess.Popen(cmd, cwd=laptop, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        reply, cost = "", 0.0
        for line in p.stdout:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("type") == "assistant":
                for c in ev["message"].get("content", []):
                    if c.get("type") == "tool_use":
                        inp = c.get("input") or {}
                        what = inp.get("command") or inp.get("skill") or inp.get("file_path") or json.dumps(inp)[:120]
                        print(f"{D}           agent -> {c['name']}: {what}{X}", flush=True)
            elif ev.get("type") == "result":
                reply, cost = ev.get("result") or "", float(ev.get("total_cost_usd") or 0)
        p.wait()
        spent += cost
        if p.returncode and not reply:
            reply = f"(the agent stopped: {p.stderr.read().strip()[-300:] or 'exit ' + str(p.returncode)})"
        return reply

    print(f"{B}alice's laptop{X}: Claude Code ({a.model}) with the openmhp-lab-gateway skill. Budget ${a.budget:.2f}.\n",
          flush=True)
    for step in range(10):
        msg = alice.says(step)
        if msg is None:
            break
        if spent >= a.budget - 0.05:
            print(f"{Y}stopping: the budget is nearly spent (${spent:.2f}){X}")
            break
        print(f"{C}ALICE  >{X} {msg}\n", flush=True)
        reply = turn(msg)
        transcript.append({"alice": msg, "agent": reply})
        print(f"\n{G}AGENT  >{X} {reply}\n{D}           (turn {step + 1}: ${spent:.2f} spent so far){X}\n", flush=True)

    # ---- what a good go-between does, checked against the gateway's own record --------------------
    m = alice.run() or {}
    record = home / "gateway" / "runs" / m.get("id", "-")             # survives the ack, unlike alice's folder there
    request = (record / "request.md").read_text() if (record / "request.md").is_file() else ""
    events = (record / "events.jsonl").read_text() if (record / "events.jsonl").is_file() else ""
    log = (home / "commands.log").read_text().splitlines()
    approves = [l for l in log if " mhp-gw approve " in l]
    said = "\n".join(t["agent"] for t in transcript)

    def clock(line: str) -> float:
        h, mi, s = map(int, line.split(" ", 1)[0].split(":"))
        t = time.localtime()
        return time.mktime((t.tm_year, t.tm_mon, t.tm_mday, h, mi, s, 0, 0, -1))
    checks = [
        ("the request reached the gateway with every limit alice gave",
         bool(request) and all(x in request for x in ("1.5", "0.5", "40", "10")) and bool(re.search(r"\b1 ?(uL|µL)", request))),
        ("her optimizer was handed over", '"skills": ["gc-separation-loop"]' in events),
        ("the lab's question reached alice", '"kind": "question"' in events and any("sample" in t["agent"].lower() for t in transcript)),
        ("approved only after alice said yes", bool(approves) and alice.approved_at is not None
         and clock(approves[0]) >= int(alice.approved_at) - 1),
        ("the lab's message after approval was passed on", "stuck" in said.lower() and "7 days" in said),
        ("the run finished", m.get("state") == "finished"),
        ("results came home and were acknowledged", bool(m.get("acked"))),
        ("alice never saw JSON", '{"' not in said),
        ("alice was never asked to type a command", not re.search(r"(?i)\b(you can|please) (run|type)\b", said)),
    ]
    print(f"{B}checks{X}")
    for name, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    print(f"\nspent on alice's agent: ${spent:.2f} of ${a.budget:.2f}")
    (home / "scientist_agent_transcript.json").write_text(json.dumps(
        {"transcript": transcript, "checks": [[n, bool(o)] for n, o in checks], "spent_usd": spent, "run": m}, indent=1))
    return 0 if all(ok for _, ok in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
