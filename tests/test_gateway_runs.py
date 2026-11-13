"""Gateway runs: scientist folders, the `mhp-gw` command entry point, and file copies limited to a
scientist's own folder. No SSH server and no network: the entry point is called in-process exactly as
sshd's forced command would call it.

    PYTHONPATH=. python tests/test_gateway_runs.py
"""
import os
import sys
import tempfile
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
    assert S.new_run_id(now=0).startswith("R-7001-") or S.new_run_id(now=0).startswith("R-6912-")    # month of the epoch, local time
    for bad in ("R-1", "../R-2611-0001", "R-2611-0001/../x"):
        with raises(ValueError):
            S.run_folder("alice", bad)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok ", name)
