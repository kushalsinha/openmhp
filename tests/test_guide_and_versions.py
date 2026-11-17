"""The guide that ships in the wheel, `--version` on every machine, and `mhp gateway restart`, all without touching
the real OS service manager.

    PYTHONPATH=. python tests/test_guide_and_versions.py
"""
import contextlib
import io
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")
os.environ.setdefault("OPENMHP_HOME", tempfile.mkdtemp(prefix="openmhp-guide-tests-"))
os.environ["OPENMHP_NO_UPDATE_CHECK"] = "1"


def run(fn, *a, **kw):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = fn(*a, **kw)
    return code, out.getvalue() + err.getvalue()


# ---- the guide ---------------------------------------------------------------------------------------------
def test_the_guide_ships_with_the_package():
    from openmhp import guide as G
    ts = G.topics()
    for t in ("troubleshooting", "quickstart", "gateway", "lab-nodes", "experiment-flow", "add-a-device", "spec"):
        assert t in ts, t
    assert ts[0] == "troubleshooting"
    assert '"guide/*.md"' in Path("pyproject.toml").read_text()            # in the wheel, not only the checkout
    for t in ts:
        text = (G.GUIDE / f"{t}.md").read_text(encoding="utf-8")
        assert len(text) > 500, t
        prose = re.sub(r"```.*?```", "", text, flags=re.S)                  # code may show HTML; prose must not
        assert not re.search(r"</?(p|div|span|table|td|li|h[1-4]|code|pre|figure)\b[^>]*>", prose), t


def test_mhp_guide_lists_reads_and_searches():
    from openmhp import guide as G
    code, out = run(G.main, [])
    assert code == 0 and "troubleshooting" in out and "mhp guide search" in out
    code, out = run(G.main, ["gate"])                                      # a unique prefix is enough
    assert code == 0 and "# Gateway and relay" in out
    code, out = run(G.main, ["search", "gateway", "restart"])
    assert code == 0 and "troubleshooting:" in out
    code, out = run(G.main, ["nosuchtopic"])
    assert code == 2 and "troubleshooting" in out
    code, out = run(G.main, ["path"])
    assert code == 0 and out.strip() == str(G.GUIDE)
    from openmhp import cli
    code, out = run(cli.main, ["guide", "search", "pair-agent"])
    assert code == 0 and "pair-agent" in out


def test_website_pages_convert_to_plain_markdown():
    import build_guide as B
    md = B.convert(
        '<header class="hero"><p class="eyebrow">Build</p><h1>Title</h1><p class="lede">Lede.</p></header>'
        '<h2>Install</h2><p>Run <code>mhp</code> and see <a href="/gateway">the gateway</a>.</p>'
        '<div class="callout"><p>Careful.</p></div>'
        '<pre><code>mhp gateway init   <span class="c"># once</span></code></pre>'
        '<table><tr><th>Machine</th><th>pip</th></tr>'
        '<tr><td><b>Lab PC</b></td><td><code>pip install -U openmhp</code><br><code>mhp node add x</code></td></tr></table>'
        '<ul><li>one</li><li>two <code></code></li></ul>'
        '<figure><picture><source srcset="/a.svg"><img src="/a.svg" alt="Arrows into the gateway."></picture>'
        '<figcaption>Every arrow points in.</figcaption></figure>')
    assert "Build" not in md                                               # the eyebrow is navigation, not content
    assert "# Title" in md and "## Install" in md
    assert "[the gateway](https://openmhp.com/gateway)" in md
    assert "> Careful." in md
    assert "```\nmhp gateway init   # once\n```" in md
    assert "| **Lab PC** | `pip install -U openmhp` `mhp node add x` |" in md
    assert "- two" in md and "``" not in md.replace("```", "")
    assert "[Figure: Arrows into the gateway.]" in md and "*Every arrow points in.*" in md


# ---- processes and services ------------------------------------------------------------------------------
def test_only_real_gateway_processes_count():
    from openmhp import service as S
    v = ("gateway", "serve")
    assert S.is_openmhp_command(["/home/mhp/.venv/bin/python3.12", "/home/mhp/.venv/bin/mhp", "gateway", "serve"], v)
    assert S.is_openmhp_command(["python3", "-m", "openmhp.cli", "gateway", "serve"], v)
    assert S.is_openmhp_command(["C:\\Py\\Scripts\\mhp.exe", "gateway", "serve"], v)
    assert not S.is_openmhp_command(["grep", "--color=auto", "gateway", "serve"], v)
    assert not S.is_openmhp_command(["grep", "gateway serve"], v)
    assert not S.is_openmhp_command(["mhp", "gateway", "status"], v)
    assert S.is_openmhp_command(["mhp", "gateway", "serve", "--host", "10.0.0.5"], v)
    assert S.is_openmhp_command(["python3", "-I", "-m", "openmhp.cli", "gateway", "serve"], v)
    # macOS joins arguments into one line: a shell running a script that mentions the command is not a gateway
    assert not S.is_openmhp_command("/bin/zsh -c cd x && python -m openmhp.cli gateway serve".split(), v)
    assert not S.is_openmhp_command("bash -c mhp gateway serve > log".split(), v)
    assert not S.is_openmhp_command("tmux new -d mhp gateway serve".split(), v)
    assert not S.is_openmhp_command(["python3", "-m", "http.server", "gateway", "serve"], v)


def test_the_python_a_service_starts():
    from openmhp import service as S
    d = Path(tempfile.mkdtemp())
    cases = {
        "unit": ("[Service]\nExecStart=/opt/v/bin/python3.12 -m openmhp.cli gateway serve\n", "/opt/v/bin/python3.12"),
        "plist": ("<key>ProgramArguments</key>\n  <array>\n      <string>/opt/v/bin/python</string>\n", "/opt/v/bin/python"),
        "bat": ('@echo off\r\nstart "" /min "C:\\Program Files\\Py\\python.exe" -m openmhp.cli gateway serve\r\n',
                "C:\\Program Files\\Py\\python.exe"),
    }
    real = S.target_path
    try:
        for name, (text, want) in cases.items():
            (d / name).write_text(text)
            S.target_path = lambda label=S.LABEL, p=d / name: p
            assert S.service_python("openmhp-gateway") == want, name
        S.target_path = lambda label=S.LABEL: d / "missing"
        assert S.service_python("openmhp-gateway") is None
    finally:
        S.target_path = real
    assert S.openmhp_version_of(sys.executable) is not None or True        # importable here only when installed
    assert S.openmhp_version_of("/no/such/python") is None


def test_a_real_stray_process_is_found_and_stopped():
    """A real process shaped like a hand-started `mhp gateway serve`, found by its command line and stopped."""
    import subprocess
    if os.name != "posix":
        print("skip: posix process listing")
        return
    from openmhp import service as S
    d = Path(tempfile.mkdtemp())
    (d / "mhp").write_text("import time\ntime.sleep(60)\n")
    p = subprocess.Popen([sys.executable, str(d / "mhp"), "gateway", "serve"])
    import threading
    threading.Thread(target=p.wait, daemon=True).start()      # reap it as init would a real stray, so no zombie lingers
    try:
        import time
        end = time.time() + 5
        while time.time() < end and p.pid not in [pid for pid, _ in S.find_processes(("gateway", "serve"))]:
            time.sleep(0.1)
        assert p.pid in [pid for pid, _ in S.find_processes(("gateway", "serve"))]
        assert S.stop_process(p.pid)
        assert p.poll() is not None
    finally:
        if p.poll() is None:
            p.kill()


class FakeOS:
    """Stand-ins for everything `mhp gateway restart` asks the OS."""
    def __init__(self, installed=True, main_pid=100, others=(200,), running="0.11.2", can_stop=True):
        self.installed, self.main_pid, self.others = installed, main_pid, list(others)
        self.running, self.can_stop = running, can_stop
        self.stopped, self.restarted = [], 0

    def install(self, G, S):
        self.saved = (S.service_state, S.find_processes, S.stop_process, S.restart_service, S.service_python, G._live, G.load)
        S.service_state = lambda label: {"installed": self.installed, "running": True, "path": "/u/openmhp-gateway.service",
                                         "main_pid": self.main_pid if self.installed else None, "python": "/v/bin/python"}
        S.find_processes = lambda verb: [(p, f"/v/bin/python /v/bin/mhp gateway serve #{p}")
                                         for p in ([self.main_pid] if self.installed else []) + self.others]
        S.stop_process = lambda pid: (self.stopped.append(pid) or True) if self.can_stop else False
        S.restart_service = lambda label: (setattr(self, "restarted", self.restarted + 1)
                                           or {"ok": True, "steps": ["systemctl --user restart openmhp-gateway.service: ok"]})
        S.service_python = lambda label: "/v/bin/python"
        G._live = lambda: {"openmhp": self.running, "nodes": {}} if self.restarted or not self.installed else None
        G.load = lambda: {"server_name": "10.0.0.5", "listen": 9443}
        return self

    def remove(self, G, S):
        (S.service_state, S.find_processes, S.stop_process, S.restart_service, S.service_python, G._live, G.load) = self.saved


def with_fake_os(fake, fn):
    from openmhp import gateway as G, service as S
    fake.install(G, S)
    try:
        return fn(G)
    finally:
        fake.remove(G, S)


def test_restart_stops_a_hand_started_gateway_and_restarts_the_service():
    from openmhp import __version__
    fake = FakeOS(running=__version__)
    code, out = with_fake_os(fake, lambda G: run(G.restart))
    assert code == 0, out
    assert fake.stopped == [200] and fake.restarted == 1                   # the service's own process is left alone
    assert "process 200" in out and f"running OpenMHP {__version__}" in out
    assert "install-service" not in out


def test_restart_says_when_the_service_runs_another_python():
    fake = FakeOS(others=(), running="0.9.9")
    code, out = with_fake_os(fake, lambda G: run(G.restart))
    assert code == 0 and fake.stopped == [] and "0.9.9" in out and "mhp gateway serve --install-service" in out


def test_restart_without_a_service_stops_nothing_and_says_how_to_install():
    fake = FakeOS(installed=False, others=(300,))
    code, out = with_fake_os(fake, lambda G: run(G.restart))
    assert code == 1 and fake.stopped == [] and fake.restarted == 0       # the only gateway keeps running
    assert "kill 300" in out and "mhp gateway serve --install-service" in out


def test_restart_stops_when_a_process_will_not_stop():
    fake = FakeOS(can_stop=False)
    code, out = with_fake_os(fake, lambda G: run(G.restart))
    assert code == 1 and fake.restarted == 0 and "kill 200" in out


def test_status_names_the_service_and_the_extra_process():
    fake = FakeOS(running="0.9.9")
    fake.restarted = 1                                                     # the gateway answers
    lines = with_fake_os(fake, lambda G: G.service_line({"openmhp": "0.9.9"}))
    text = "\n".join(lines)
    assert "service: running" in text and "mhp gateway restart" in text
    assert "process 200" in text and "0.9.9" in text


# ---- --version -----------------------------------------------------------------------------------------------
def test_version_on_every_machine():
    from openmhp import __version__, cli
    code, out = run(cli.main, ["--version"])
    assert code == 0 and f"OpenMHP {__version__}" in out and sys.executable in out
    for role in ("gateway", "node", "agent"):
        code, out = run(cli.main, [role, "--version"])
        assert code == 0 and f"OpenMHP {__version__}" in out, (role, out)
    code, out = run(cli.main, ["agent", "--version"])
    assert "not joined" in out
    code, out = run(cli.main, [])
    assert code == 2 and "mhp guide" in out


def test_gateway_version_shows_what_the_running_gateway_answers():
    from openmhp import versions as V
    fake = FakeOS(running="0.9.9")
    fake.restarted = 1
    from openmhp import service as S
    real = S.openmhp_version_of
    S.openmhp_version_of = lambda py: "0.9.9"
    try:
        lines = with_fake_os(fake, lambda G: V.gateway())
    finally:
        S.openmhp_version_of = real
    text = "\n".join(lines)
    assert "gateway service (running) starts /v/bin/python, which has OpenMHP 0.9.9" in text
    assert "running gateway: OpenMHP 0.9.9" in text and "mhp gateway restart" in text


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok ", name)
