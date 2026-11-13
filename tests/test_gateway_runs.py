"""Gateway runs: scientist folders, the `mhp-gw` command entry point, and file copies limited to a
scientist's own folder. No SSH server and no network: the entry point is called in-process exactly as
sshd's forced command would call it.

    PYTHONPATH=. python tests/test_gateway_runs.py
"""
import io
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, ".")
os.environ["OPENMHP_HOME"] = tempfile.mkdtemp(prefix="openmhp-gwruns-")
os.environ["OPENMHP_LAB_ROOT"] = str(Path(os.environ["OPENMHP_HOME"]) / "lab")

from openmhp import scientists as S                                         # noqa: E402


class raises:
    def __init__(self, exc):
        self.exc, self.value = exc, None
    def __enter__(self):
        return self
    def __exit__(self, et, ev, tb):
        assert et is not None and issubclass(et, self.exc), f"expected {self.exc.__name__}, got {et}: {ev}"
        self.value = ev
        return True


def test_scientist_folders_profiles_and_run_ids():
    for bad in ("Alice", "1alice", "al ice", "../x", "a" * 32, "", "alice/x"):
        with raises(ValueError):
            S.check_name(bad)
    prof = S.create("alice", ssh_key="ssh-ed25519 AAAA alice@laptop\n", agent="alice-laptop")
    assert prof["ssh_key"] == "ssh-ed25519 AAAA alice@laptop" and S.load_profile("alice")["agent"] == "alice-laptop"
    S.create("alice")                                                       # again: keeps what it knew
    assert S.load_profile("alice")["ssh_key"].startswith("ssh-ed25519") and S.names() == ["alice"]
    with raises(LookupError):
        S.open_run("bob")                                                   # not a scientist here

    a = S.open_run("alice")
    b = S.open_run("alice")
    assert a["id"] != b["id"] and S.RUN_ID.match(a["id"]) and a["state"] == "open" and a["owner"] == "alice"
    d = S.run_folder("alice", a["id"])
    assert d.parent.parent == S.folder("alice") and all((d / p).is_dir() for p in ("in", "preview", "out"))
    assert [r["id"] for r in S.runs("alice")] == sorted([a["id"], b["id"]])
    S.create("bob")
    c = S.open_run("bob")
    assert c["id"] not in (a["id"], b["id"]) and S.runs("bob")[0]["id"] == c["id"]   # IDs unique across scientists
    assert S.new_run_id(now=0)[2:6] == time.strftime("%y%m", time.localtime(0))                       # the month it was opened
    for bad in ("R-1", "../R-2611-0001", "R-2611-0001/../x"):
        with raises(ValueError):
            S.run_folder("alice", bad)


def gw(scientist, command, root=None):
    """Call mhp-gw as sshd's forced command would: the scientist is fixed, the command is what they asked."""
    from openmhp.gw_shell import Shell
    out = io.StringIO()
    code = Shell(scientist, root, out=out, env={"SSH_ORIGINAL_COMMAND": command}).run()
    return code, json.loads(out.getvalue())


def test_mhp_gw_answers_only_its_verbs_for_one_scientist():
    from openmhp import gw_shell as G
    S.create("carol")
    code, ans = gw("carol", "mhp-gw open")
    assert code == G.OK and ans["ok"] and S.RUN_ID.match(ans["run"]) and ans["upload"] == f"runs/{ans['run']}/in/"
    rid = ans["run"]
    code, ans = gw("carol", "open")                                         # the program name is optional
    assert code == G.OK and ans["run"] != rid
    code, ans = gw("carol", "mhp-gw list")
    assert code == G.OK and [r["id"] for r in ans["runs"]][0] == rid
    code, ans = gw("carol", f"mhp-gw status {rid}")
    assert code == G.OK and ans["run"]["owner"] == "carol" and ans["run"]["state"] == "open"
    code, ans = gw("carol", "mhp-gw help")
    assert code == G.OK and "open" in ans["verbs"]

    # another scientist's run is not found, never shown
    alice_run = S.open_run("alice")["id"]
    code, ans = gw("carol", f"mhp-gw status {alice_run}")
    assert code == G.NOT_FOUND and not ans["ok"] and "alice" not in json.dumps(ans)
    # no shell, no other programs, no path tricks
    for cmd in ("", "bash", "sh -c id", "mhp-gw rm -rf /", "cat /etc/passwd", "mhp-gw status ../alice", "mhp-gw status",
                "mhp-gw status 'unterminated"):
        code, ans = gw("carol", cmd)
        assert code == G.REFUSED and not ans["ok"] and ans["error"], (cmd, ans)
    # the forced command itself must name a scientist
    assert G.main([]) == G.REFUSED and G.main(["--scientist", "Not Valid"]) == G.REFUSED


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok ", name)
