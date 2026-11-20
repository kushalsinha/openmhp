"""Setting a machine up, as states with clear next steps: adding an instrument to a PC whose node already runs as a
service, a lab PC whose pairing the gateway no longer accepts, a pairing attempt that fails, skills that must not be
downgraded or lost, and `mhp status`, which says what this machine is and what to do next.

    PYTHONPATH=. python tests/test_setup_states.py
"""
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import types
import urllib.error
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.environ["OPENMHP_HOME"] = tempfile.mkdtemp(prefix="openmhp-setup-states-")
os.environ["OPENMHP_NO_UPDATE_CHECK"] = "1"
os.environ["OPENMHP_SERVICE_MANAGER"] = "none"          # nothing here installs a real background service
HOME = Path(os.environ["OPENMHP_HOME"])


def test_adding_an_instrument_to_a_pc_whose_service_holds_the_ports_restarts_it():
    from openmhp import node_add, node_setup as NS
    root = Path(tempfile.mkdtemp()) / "devices"
    node_add.add("ika-c-mag-hs7", root, source=str(REPO))
    held = socket.socket()
    held.bind(("127.0.0.1", 0))                                   # the running service holds the base port
    held.listen()
    base = held.getsockname()[1]
    restarts = []
    svc = types.SimpleNamespace(status=lambda: {"installed": True},
                                restart=lambda r, b: restarts.append((r, b)) or {"ok": True},
                                install=lambda r, b: {"ok": True})
    said = []
    try:
        answers = lambda prompt, *a, **k: "" if "gateway" in prompt else "y"   # no gateway; yes, restart it
        out = NS.finish(root, base, ask=answers, say=said.append, svc=svc, joiner=lambda *a, **k: None,
                        load=lambda f: {})
    finally:
        held.close()
    assert restarts == [(root, base)] and out["service"]["ok"], (out, said)
    assert not any("already in use" in s for s in said), said
    assert NS.preflight_problems(sorted(p.parent for p in root.glob("*/DEVICE.md")), "127.0.0.1", base) == []


def test_a_lab_pc_says_what_its_link_to_the_gateway_needs():
    from openmhp import relay as R
    refused = urllib.error.HTTPError("https://gw:8443/relay/register", 401, "Unauthorized", {}, None)
    assert R.link_problem(refused)[0] == "unpaired" and "Pair again" in R.link_problem(refused)[1]
    changed = urllib.error.URLError(ssl.SSLCertVerificationError("certificate verify failed"))
    assert R.link_problem(changed)[0] == "certificate_changed" and "pinned" in R.link_problem(changed)[1]
    assert R.link_problem(ConnectionRefusedError(61, "refused"))[0] == "unreachable"
    # the poll loop records what it saw, for `mhp status` and `--service-status`
    dead = socket.socket()
    dead.bind(("127.0.0.1", 0))
    port = dead.getsockname()[1]
    dead.close()
    c = R.RelayClient({"gateway": f"https://127.0.0.1:{port}", "token": "t", "name": "bench"}, {})
    import threading
    t = threading.Thread(target=c._poll_loop, daemon=True)
    t.start()
    for _ in range(100):
        if (R.load_link() or {}).get("state"):
            break
        import time
        time.sleep(0.05)
    c.stop.set()
    link = R.load_link()
    assert link["state"] == "unreachable" and link["gateway"] == f"https://127.0.0.1:{port}", link


def _cert() -> str | None:
    if not shutil.which("openssl"):
        return None
    d = Path(tempfile.mkdtemp())
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-subj", "/CN=test", "-days", "1",
                    "-keyout", str(d / "k.pem"), "-out", str(d / "c.pem")], capture_output=True, check=True)
    return (d / "c.pem").read_text()


def test_a_failed_pairing_keeps_the_working_one():
    from openmhp import relay as R
    pem = _cert()
    if pem is None:
        print("skip: openssl makes the test certificate")
        return
    R.PIN_FILE.parent.mkdir(parents=True, exist_ok=True)
    R.PIN_FILE.write_text("THE WORKING PIN")
    real_fetch, real_open = R.fetch_cert, R.urllib.request.urlopen
    R.fetch_cert = lambda url: pem
    def refuse(req, **kw):
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, None)
    R.urllib.request.urlopen = refuse
    try:
        R.join("https://other-gateway:8443", "dead-code", {}, quiet=True); assert False
    except SystemExit as e:
        assert "refused the code" in str(e)
    finally:
        R.fetch_cert, R.urllib.request.urlopen = real_fetch, real_open
    assert R.PIN_FILE.read_text() == "THE WORKING PIN"                       # the pairing that worked still works


def _skill_home():
    from openmhp import skills_install as SK
    d = Path(tempfile.mkdtemp()) / ".claude" / "skills"
    SK.install(d)
    return SK, d


def test_skills_are_never_downgraded_and_edits_are_never_lost():
    SK, d = _skill_home()
    name = "openmhp-operate"
    skill = d / name / "SKILL.md"
    assert {r["state"] for r in SK.status([d])} == {"current"}
    # a newer install put a newer version here: this older one leaves it alone, refresh or install
    text = skill.read_text()
    skill.write_text(text.replace(f'version: "{SK.bundled_version(name)}"', 'version: "9.9"', 1))
    mark = json.loads((d / name / SK.MARK).read_text())
    (d / name / SK.MARK).write_text(json.dumps({**mark, "digest": SK.digest(d / name)}))
    assert {r["name"]: r["state"] for r in SK.status([d])}[name] == "newer"
    SK.refresh([d], backup_root=Path(tempfile.mkdtemp()))
    skipped = []
    SK.install(d, skipped=skipped)
    assert 'version: "9.9"' in skill.read_text() and skipped[0]["why"] == "a newer version is installed"
    # a copy changed by hand: install leaves it unless a person asked, and then backs it up first
    skill.write_text(text + "\nmy own note\n")
    assert {r["name"]: r["state"] for r in SK.status([d])}[name] == "changed"
    skipped = []
    SK.install(d, skipped=skipped)
    assert "my own note" in skill.read_text() and "changed by hand" in skipped[0]["why"]
    SK.install(d, replace_changed=True)
    assert "my own note" not in skill.read_text()
    kept = list(SK.backup_root().rglob(f"{name}/SKILL.md"))
    assert any("my own note" in k.read_text() for k in kept), kept
    assert not list(d.glob(".*.installing"))                                  # nothing half-copied left behind


def test_mhp_status_says_what_this_machine_is_and_what_to_do_next():
    env = {**os.environ, "OPENMHP_HOME": tempfile.mkdtemp(), "PYTHONPATH": str(REPO), "HOME": tempfile.mkdtemp()}
    cli = [sys.executable, "-m", "openmhp.cli"]
    r = subprocess.run([*cli, "status"], capture_output=True, text=True, env=env)
    assert r.returncode == 1 and "not set up as anything yet" in r.stdout and "mhp gateway init" in r.stdout, r.stdout
    r = subprocess.run([*cli, "node", "add", "globalfia-flopro-sampler", "--from", str(REPO), "--no-setup"],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    r = subprocess.run([*cli, "status", "--json"], capture_output=True, text=True, env=env)
    doc = json.loads(r.stdout)
    assert r.returncode == 1 and "instrument PC" in doc["roles"], doc
    nexts = [p["next"] for p in doc["todo"]]
    assert "mhp node setup globalfia-flopro-sampler" in nexts and any("--install-service" in n for n in nexts), nexts
    r = subprocess.run([*cli, "status"], capture_output=True, text=True, env=env)
    assert "next: mhp node setup globalfia-flopro-sampler" in r.stdout and "thing(s) to do" in r.stdout, r.stdout


def test_documented_json_flags_are_accepted():
    for cmd in (["rubric", "supported-devices/ika-c-mag-hs7", "--json"], ["inclusion", "supported-devices/ika-c-mag-hs7", "--json"]):
        r = subprocess.run([sys.executable, "-m", "openmhp.cli", *cmd], capture_output=True, text=True, cwd=REPO,
                           env={**os.environ, "PYTHONPATH": str(REPO)})
        assert "unrecognized arguments" not in r.stderr and r.stdout.lstrip().startswith("{"), (cmd, r.stderr[:300])


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok ", name)
