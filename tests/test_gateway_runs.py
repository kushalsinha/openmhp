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


def copy(scientist, command):
    """A file copy as sshd hands it over: returns (exit code, the program and arguments that would run, answer)."""
    from openmhp.gw_shell import Shell
    ran, out, err = [], io.StringIO(), io.StringIO()
    cwd = os.getcwd()
    try:
        code = Shell(scientist, out=out, err=err, env={"SSH_ORIGINAL_COMMAND": command},
                     execvp=lambda prog, argv: ran.append((prog, argv, os.getcwd()))).run()
    finally:
        os.chdir(cwd)
    if out.getvalue():                         # a verb answered on stdout
        return code, (ran[0] if ran else None), json.loads(out.getvalue())
    return code, (ran[0] if ran else None), ({"ok": False, "error": err.getvalue()} if err.getvalue() else None)


def test_file_copies_stay_inside_the_scientists_own_run_folders():
    from openmhp import gw_shell as G
    S.create("dave")
    rid = S.open_run("dave")["id"]
    home = S.folder("dave").resolve()

    # copies in: rsync and classic scp, into in/ only, run from the scientist's folder, links that point outside ignored
    code, ran, _ = copy("dave", f"rsync --server -logDtpre.iLsfxCIvu --partial . runs/{rid}/in/")
    assert code == G.OK and ran[0] == "rsync" and Path(ran[2]).resolve() == home
    assert ran[1] == ["rsync", "--server", "-logDtpre.iLsfxCIvu", "--partial", "--safe-links", ".", f"runs/{rid}/in/"]
    code, ran, _ = copy("dave", f"scp -r -t -- runs/{rid}/in/bo-skill")
    assert code == G.OK and ran[1] == ["scp", "-r", "-t", "--", f"runs/{rid}/in/bo-skill"]
    code, ran, _ = copy("dave", f"rsync --server -vlogDtpre.iLsfxCIvu . ~/runs/{rid}/in/")      # ~/ is the folder
    assert code == G.OK and ran[1][-1] == f"runs/{rid}/in/"
    code, ran, _ = copy("dave", f"rsync --server -g -l -o -p -D -r -t --dirs . runs/{rid}/in/bo/")   # macOS openrsync's shape
    assert code == G.OK and ran[1][-1] == f"runs/{rid}/in/bo/"
    if os.name != "nt":
        code, ran, _ = copy("dave", f"rsync --server -logDtpre.iLsfxCIvu . {home}/runs/{rid}/in/")   # absolute, own folder
        assert code == G.OK and ran[1][-1] == f"runs/{rid}/in/"

    # copies out: from preview/ and out/ only, never with --safe-links added
    code, ran, _ = copy("dave", f"rsync --server --sender -logDtpre.iLsfxCIvu . runs/{rid}/out/ runs/{rid}/preview/")
    assert code == G.OK and "--safe-links" not in ran[1] and ran[1][-2:] == [f"runs/{rid}/out/", f"runs/{rid}/preview/"]
    code, ran, _ = copy("dave", f"scp -r -f runs/{rid}/out")
    assert code == G.OK and ran[1] == ["scp", "-r", "-f", "--", f"runs/{rid}/out"]

    # everything else is refused before anything runs
    alice_run = S.open_run("alice")["id"]
    refused = [
        f"rsync --server --sender -logDtpre.iLsfxCIvu . runs/{rid}/in/",         # reading in/ back: not a results folder
        f"rsync --server -logDtpre.iLsfxCIvu . runs/{rid}/out/",                 # writing into out/
        f"rsync --server -logDtpre.iLsfxCIvu . runs/{rid}/",                     # the run folder itself
        f"rsync --server -logDtpre.iLsfxCIvu . runs/{rid}/in/../../../profile.json",
        "rsync --server -logDtpre.iLsfxCIvu . ../alice/runs/x/in/",
        "rsync --server --sender -logDtpre.iLsfxCIvu . /etc/passwd",
        f"rsync --server --remove-source-files -logDtpre.iLsfxCIvu . runs/{rid}/in/",
        f"rsync --server --log-file=/tmp/x -logDtpre.iLsfxCIvu . runs/{rid}/in/",
        f"rsync -logDtpre.iLsfxCIvu . runs/{rid}/in/",                           # not as the far end of a copy
        f"rsync --server -logDtpre.iLsfxCIvu runs/{rid}/in/",                    # no '.' separator
        f"scp -t runs/{rid}/out/x",
        f"scp -t runs/{rid}/in/a runs/{rid}/in/b",
        f"scp -S /bin/sh -t runs/{rid}/in/",
        f"scp -f /etc/passwd",
        f"scp -t runs/R-9999-9999/in/",                                          # no such run: not found
        f"scp -t runs/{alice_run}/in/",                                          # alice's run is not dave's
        "/usr/lib/openssh/sftp-server",
        "internal-sftp",
    ]
    for cmd in refused:
        code, ran, ans = copy("dave", cmd)
        assert ran is None and code in (G.REFUSED, G.NOT_FOUND) and not ans["ok"], (cmd, code, ans)
        assert ans["error"].startswith("mhp-gw: ") or cmd == "", cmd          # on stderr: the copy's stdout is its protocol
    assert "rsync -a" in copy("dave", "internal-sftp")[2]["error"]
    assert "rsync -a" in copy("dave", "")[2]["error"]                            # an empty command: likely modern scp


def test_ssh_keys_come_only_from_profiles_and_are_bound_to_mhp_gw():
    from openmhp import ssh_access as SA
    key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl"
    assert SA.check_key(key + " frank@laptop") == key
    for bad in ('no-pty ' + key, 'command="sh" ' + key, key + "\n" + key, "-----BEGIN OPENSSH PRIVATE KEY-----",
                "ssh-ed25519 not base64!", ""):
        with raises(ValueError):
            SA.check_key(bad)
    S.create("frank", ssh_key=key)
    S.create("grace")                                                     # no key yet: never listed
    single = {"mode": "single", "login": "mhp", "lab_root": str(S.lab_root()), "python": "/opt/py/bin/python"}
    lines = SA.keys_for("mhp", single)
    frank = [l for l in lines if l.endswith("openmhp:frank")]
    assert len(frank) == 1 and not any("openmhp:grace" in l for l in lines)
    assert frank[0].startswith('command="/opt/py/bin/python -m openmhp.gw_shell --scientist frank --root ')
    assert ",restrict " + key + " " in frank[0]
    assert SA.keys_for("root", single) == [] and SA.keys_for("mhp-frank", single) == []
    users = {**single, "mode": "users"}
    assert [l.endswith("openmhp:frank") for l in SA.keys_for("mhp-frank", users)] == [True]
    assert SA.keys_for("mhp", users) == [] and SA.keys_for("mhp-nobody", users) == [] and SA.keys_for("mhp-Bad!", users) == []
    assert SA.login_for("frank", users) == "mhp-frank" and SA.login_for("frank", single) == "mhp"
    snip = SA.sshd_snippet(single)
    assert "Match User mhp" in snip and "AuthorizedKeysFile none" in snip and "PasswordAuthentication no" in snip
    assert "Match Group mhp-scientists" in SA.sshd_snippet(users)
    assert SA.known_hosts_line("gw.lab", 22, key) == "gw.lab " + key and SA.known_hosts_line("gw.lab", 2222, key).startswith("[gw.lab]:2222 ")
    out = io.StringIO()
    sys.stdout, real = out, sys.stdout
    try:
        assert SA.main(["keys", "mhp"]) == 0 and SA.main(["nonsense"]) == 2      # no gateway state here: prints nothing
    finally:
        sys.stdout = real
    assert out.getvalue() == ""


FAKE_SSH = """#!{python}
# Stands in for ssh: skips ssh's options, finds the host, and hands the rest to mhp-gw as sshd's forced command would.
import os, sys
args, i = sys.argv[1:], 0
while i < len(args) and args[i].startswith("-"):
    i += 2 if args[i] in ("-l", "-p", "-i", "-o", "-F", "-J", "-c", "-m", "-b", "-e") else 1
env = dict(os.environ, SSH_ORIGINAL_COMMAND=" ".join(args[i + 1:]))
os.execve({python!r}, [{python!r}, "-m", "openmhp.gw_shell", "--scientist", "erin", "--root", {root!r}], env)
"""


def test_real_rsync_and_scp_through_the_forced_command():
    """The real clients, end to end, with a stand-in for ssh. Skipped where rsync or scp is missing."""
    import shutil
    import subprocess
    if os.name == "nt" or not (shutil.which("rsync") and shutil.which("scp")):
        print("skip: needs rsync and scp")
        return
    work = Path(tempfile.mkdtemp(prefix="gw-copy-"))
    fake = work / "fakessh"
    fake.write_text(FAKE_SSH.format(python=sys.executable, root=str(S.lab_root())))
    fake.chmod(0o755)
    S.create("erin")
    rid = S.open_run("erin")["id"]
    src = work / "bo"
    src.mkdir()
    (src / "run.py").write_text("print('next point')\n")
    os.symlink("/etc/passwd", src / "outside")
    env = dict(os.environ, PYTHONPATH=os.getcwd())
    run = lambda *cmd: subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=60)

    r = run("rsync", "-a", "-e", str(fake), f"{src}/", f"gw:runs/{rid}/in/bo/")
    got = S.run_folder("erin", rid) / "in" / "bo"
    assert r.returncode == 0 and (got / "run.py").is_file() and not (got / "outside").exists(), r.stderr
    r = run("scp", "-O", "-r", "-S", str(fake), str(src / "run.py"), f"gw:runs/{rid}/in/again.py")
    assert r.returncode == 0 and (S.run_folder("erin", rid) / "in" / "again.py").is_file(), r.stderr

    (S.run_folder("erin", rid) / "out" / "summary.csv").write_text("cell,retention\n1,0.94\n")
    back = work / "back"
    r = run("rsync", "-a", "-e", str(fake), f"gw:runs/{rid}/out/", f"{back}/")
    assert r.returncode == 0 and (back / "summary.csv").is_file(), r.stderr
    r = run("scp", "-O", "-r", "-S", str(fake), f"gw:runs/{rid}/out", str(work / "back2"))
    assert r.returncode == 0 and (work / "back2" / "summary.csv").is_file(), r.stderr

    r = run("rsync", "-a", "-e", str(fake), f"{src}/", f"gw:runs/{rid}/out/")
    assert r.returncode != 0 and "files can only be copied into" in r.stderr
    r = run("scp", "-O", "-S", str(fake), str(src / "run.py"), "gw:profile.json")
    assert r.returncode != 0 and "files can only be copied into" in r.stderr
    r = run("scp", "-S", str(fake), str(src / "run.py"), f"gw:runs/{rid}/in/x.py")          # modern scp: SFTP
    assert r.returncode != 0 and ("rsync -a" in r.stderr or not (S.run_folder("erin", rid) / "in" / "x.py").exists())


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok ", name)
