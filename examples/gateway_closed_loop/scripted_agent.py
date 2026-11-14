"""A scripted stand-in for an agent harness, so the closed-loop demo runs without a model (and in CI).

The supervisor starts it exactly as it would start a harness turn: in the planner's or the run's working
folder, with the turn's prompt as the last argument. It reads the run's MCP configuration for the token and
the gateway's address, as a real harness's tools would, and talks to the gateway over HTTPS:

- as the planner: finds the chromatograph, rehearses one injection as a dry run, asks the scientist one
  question, then proposes a charter and writes an expected-data preview;
- as the run: injects, reads the result, asks the scientist's optimizer (their skill) for the next
  conditions, and repeats until the optimizer is done or the charter's budget is spent; then reports.

A real harness makes these choices itself; this script makes the fixed ones a demo needs.
"""
import json
import os
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request

args = sys.argv[1:]
session, work, prompt = args[args.index("--session") + 1], args[args.index("--workdir") + 1], args[-1]
env = json.load(open(os.path.join(work, ".mcp-run.json"), encoding="utf-8"))["mcpServers"]["run"]["env"]
ctx = ssl.create_default_context(cafile=env["SSL_CERT_FILE"])
ctx.check_hostname = False
planning = os.path.basename(work.rstrip("/")) == "plan"
SAMPLE = "acetone ethanol isopropanol toluene"


def post(path, body):
    req = urllib.request.Request(env["OPENMHP_GATEWAY"] + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": "Bearer " + env["OPENMHP_RUN_TOKEN"], "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"ok": False, "status": e.code, "error": (e.read() or b"").decode(errors="replace")}


def rpc(device, method, params):
    return post(f"/{device}/rpc", {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})


def program(ramp):
    return [{"temp": 60, "hold_s": 30}, {"temp": 200, "ramp_c_min": ramp, "hold_s": 0}]


def say(text):
    with open(os.path.join(work, "notebook.md"), "a", encoding="utf-8") as f:
        f.write(text + "\n")


def done(text):
    print(json.dumps({"ok": True, "session": session, "text": text, "cost_usd": 0.0, "tokens": 0}))
    sys.exit(0)


def find_gc():
    found = post("/directory/rpc", {"jsonrpc": "2.0", "id": 1, "method": "directory/search",
                                    "params": {"query": "gas chromatograph separation", "limit": 3}})
    return found["result"]["results"][0]["id"]


if planning:
    if "] plan:" in prompt:
        gc = find_gc()
        rehearsal = rpc(gc, "actions/invoke", {"name": "run_method", "dryRun": True, "params": {
            "oven_program": program(20), "injection_volume_ul": 1, "carrier_flow_ml_min": 1.5, "sample": SAMPLE}})
        with open(os.path.join(work, "rehearsal.json"), "w") as f:
            json.dump({"instrument": gc, "dry_run": rehearsal}, f, indent=1)
        post("/runs/ask_scientist", {"question": f"I will use {gc}. Is the sample exactly acetone, ethanol, isopropanol "
                                     "and toluene, and may I use up to 10 uL of it in total?", "meanwhile": "wait"})
        done("asked the scientist")
    if "] answer:" in prompt or "] message:" in prompt:
        gc = json.load(open(os.path.join(work, "rehearsal.json")))["instrument"]
        os.makedirs(os.path.join(work, "preview"), exist_ok=True)
        with open(os.path.join(work, "preview", "history.csv"), "w") as f:
            f.write("injection,carrier_flow_ml_min,ramp_c_min,resolution_min,run_time_s\n1,1.5,20,1.2,480\n2,1.125,20,1.45,520\n")
        with open(os.path.join(work, "preview", "README.md"), "w") as f:
            f.write("Synthetic rows in the format the run writes to out/history.csv: one line per injection, with the "
                    "conditions the optimizer chose and what the chromatograph reported. Values are illustrative.\n")
        charter = {
            "objective": "Resolve every neighbouring peak (Rs >= 1.5) of acetone, ethanol, isopropanol and toluene in the "
                         "shortest run, by carrier flow and oven ramp, choosing each next condition with the scientist's "
                         "gc-separation-loop optimizer.",
            "autonomy": "act",
            "instruments": {"gc": gc},
            "envelope": {"gc": {"actions": {"run_method": {"carrier_flow_ml_min": {"min": 0.5, "max": 5},
                                                           "oven_program[].ramp_c_min": {"min": 2, "max": 40},
                                                           "injection_volume_ul": {"min": 1, "max": 1}}},
                                "settings": {}}},
            "consumables": {"sample_ul": {"limit": 10, "uses": [{"instrument": "gc", "action": "run_method",
                                                                 "param": "injection_volume_ul", "scale": 1}]}},
            "budgets": {"experiments": 10, "count": {"instrument": "gc", "action": "run_method"}},
            "stop_conditions": ["the optimizer says no faster resolved condition is left", "10 injections made"],
            "cleanup": "Leave the chromatograph idle; no bake-out (that needs a person).",
            "reporting": {"every_hours": 1},
        }
        post("/runs/propose_charter", {"charter": charter, "notes": "Up to 10 injections of 1 uL, a few minutes each. "
                                       "Nothing for you to do in the lab. The preview shows the history file you will get."})
        done("proposed the charter")
    done("nothing to do")

# ---- the run --------------------------------------------------------------------------------------
if "] start:" not in prompt:
    done("woken; the loop runs within the start turn")
charter = json.load(open(os.path.join(work, "..", "charter.json")))
gc = charter["instruments"]["gc"]
skill = os.path.join(work, ".claude", "skills", "gc-separation-loop", "suggest.py")
history_path = os.path.join(work, "out", "history.json")
os.makedirs(os.path.dirname(history_path), exist_ok=True)
history = []
say(f"# Run on {gc}\n")
while True:
    with open(history_path, "w") as f:
        json.dump(history, f, indent=1)
    nxt = json.loads(subprocess.run([sys.executable, skill, history_path], capture_output=True, text=True, check=True).stdout)
    if nxt.get("done"):
        say(f"optimizer: {nxt['why']}")
        best = nxt.get("best")
        break
    ans = rpc(gc, "actions/invoke", {"name": "run_method", "params": {
        "oven_program": program(nxt["ramp_c_min"]), "injection_volume_ul": 1,
        "carrier_flow_ml_min": nxt["carrier_flow_ml_min"], "sample": SAMPLE}})
    if "error" in ans:
        say(f"the gateway refused the next injection: {ans['error']['message']}")
        best = min((h for h in history if (h["resolution_min"] or 0) >= 1.5), key=lambda h: h["run_time_s"], default=None)
        break
    job_id = ans["result"].get("job", ans["result"]).get("id")
    while True:
        st = rpc(gc, "jobs/status", {"id": job_id})["result"]["job"]
        if st["state"] in ("done", "failed", "cancelled"):
            break
        time.sleep(0.1)
    r = st.get("result") or {}
    history.append({"carrier_flow_ml_min": nxt["carrier_flow_ml_min"], "ramp_c_min": nxt["ramp_c_min"],
                    "resolution_min": r.get("resolution_min"), "run_time_s": r.get("run_time_s")})
    say(f"injection {len(history)}: flow {nxt['carrier_flow_ml_min']}, ramp {nxt['ramp_c_min']} -> "
        f"Rs {r.get('resolution_min')}, {r.get('run_time_s')} s ({nxt['why']})")
    post("/runs/report", {"text": f"injection {len(history)}: Rs {r.get('resolution_min')} in {r.get('run_time_s')} s"})

with open(history_path, "w") as f:
    json.dump(history, f, indent=1)
with open(os.path.join(work, "out", "history.csv"), "w") as f:
    f.write("injection,carrier_flow_ml_min,ramp_c_min,resolution_min,run_time_s\n")
    for i, h in enumerate(history, 1):
        f.write(f"{i},{h['carrier_flow_ml_min']},{h['ramp_c_min']},{h['resolution_min']},{h['run_time_s']}\n")
with open(os.path.join(work, "out", "best.json"), "w") as f:
    json.dump(best, f, indent=1)
if best:
    summary = (f"Resolved every peak (Rs {best['resolution_min']}) in {best['run_time_s']} s at carrier flow "
               f"{best['carrier_flow_ml_min']} mL/min and ramp {best['ramp_c_min']} C/min, after {len(history)} injections.")
    nxt_exp = [f"confirm the best condition with three repeat injections",
               "try a two-step oven ramp to shorten the run further"]
    post("/runs/finish", {"summary": summary, "outcome": "objective met", "next_experiments": nxt_exp})
else:
    post("/runs/finish", {"summary": f"No condition resolved every peak in {len(history)} injections.",
                          "outcome": "budget spent", "next_experiments": ["widen the ramp range below 2 C/min"]})
done("finished the loop")
