"""The gateway playground: a scientist's machine reaches it only through the ssh and rsync stand-ins it writes,
and a whole run (request, question, plan, approval, results home, ack) goes through them, free.

    PYTHONPATH=. python tests/test_gateway_playground.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, ".")
sys.path.insert(0, "examples/gateway_closed_loop")
EXAMPLE = Path("examples/gateway_closed_loop").resolve()


def test_a_whole_run_through_the_stand_ins():
    if not shutil.which("bash") or not shutil.which("rsync"):
        print("skip: needs bash and rsync")
        return
    import playground
    home, bin_dir, port, close = playground.start(Path(tempfile.mkdtemp(prefix="openmhp-pg-")), feed=False)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}

    def sh(cmd, stdin=None):
        r = subprocess.run(["bash", "-c", cmd], env=env, capture_output=True, text=True, input=stdin, timeout=120)
        return r.returncode, r.stdout, r.stderr

    def gw(cmd, stdin=None):
        code, out, err = sh(f"ssh mhp-gateway mhp-gw {cmd}", stdin)
        return code, json.loads(out.strip().splitlines()[-1])

    try:
        code, ans = gw("open")
        rid = ans["run"]
        assert code == 0 and rid in ans["say"]
        assert sh("ssh other-host mhp-gw open")[0] == 255                      # only the gateway's alias
        code, out, err = sh(f"rsync -a {EXAMPLE}/handover/gc-separation-loop/ mhp-gateway:runs/{rid}/in/gc-separation-loop/")
        assert code == 0, err
        lab_in = home / "lab" / "scientists" / "alice" / "runs" / rid / "in" / "gc-separation-loop" / "suggest.py"
        assert lab_in.is_file()
        code, ans = gw(f"request {rid}", (EXAMPLE / "request.md").read_text())
        assert code == 0 and "planner" in ans["say"]
        since, digest = 0, None
        for _ in range(20):
            code, ans = gw(f"wait {rid} --since {since} --timeout 20")
            since = ans["since"]
            if "q1" in ans["open_questions"]:
                assert "asks you (question q1)" in ans["say"]
                gw(f"answer {rid} q1 yes, exactly those four, up to 10 uL in total")
            if ans["state"] == "waiting_approval":
                break
        code, ans = gw(f"show {rid}")
        assert ans["plan_notes"] and "approve" in ans["say"]
        code, ans = gw(f"approve {rid} --charter-digest {ans['charter_digest']}")
        assert code == 0 and rid in ans["show_to_scientist"]
        end = time.time() + 60
        while time.time() < end and gw(f"status {rid}")[1]["run"]["state"] != "finished":
            time.sleep(0.3)
        code, ans = gw(f"status {rid}")
        assert ans["run"]["state"] == "finished" and "waiting on the gateway" in ans["say"]
        here = home / "results"
        code, out, err = sh(f"rsync -a mhp-gateway:runs/{rid}/out/ {here}/")
        assert code == 0 and (here / "report.md").is_file() and (here / "manifest.sha256").is_file(), err
        code, ans = gw(f"ack {rid}")
        assert code == 0 and "deletes its copy" in ans["say"]
        log = (home / "commands.log").read_text()
        assert f"mhp-gw approve {rid}" in log and f"rsync -a mhp-gateway:runs/{rid}/out/" in log    # the feed's source
    finally:
        close()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok ", name)
