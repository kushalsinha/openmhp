"""`mhp node setup`: the questions after `mhp node add`, answered through one `ask` callable, write config.json,
keep secrets in the keyring, prove the answers with the driver's probe, then pair with the gateway and install the
service. With no terminal (`--yes`, piped stdin) nothing is asked and what is missing is said."""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import types

HERE = pathlib.Path(__file__).resolve()
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))
_tmp_home = tempfile.mkdtemp()
os.environ["OPENMHP_HOME"] = _tmp_home                                  # relay/node.json and the default devices dir stay out of ~
from openmhp import node_setup as NS                                     # noqa: E402


class Script:
    """Answers in order; remembers every prompt so a test can say what was asked."""
    def __init__(self, *answers):
        self.answers, self.prompts, self.said = list(answers), [], []

    def ask(self, prompt, default=None, secret=False):
        self.prompts.append(prompt)
        if not self.answers:
            raise AssertionError(f"no answer scripted for: {prompt!r}")
        ans = self.answers.pop(0)
        return ans if ans.strip() or not default else default              # Enter keeps the default, like the real prompt

    def say(self, text):
        self.said.append(text)

    def asked(self, *words):
        return any(all(w in p for w in words) for p in self.prompts)

    def heard(self, *words):
        return any(all(w in s for w in words) for s in self.said)


def _fake_keyring(store: dict):
    mod = types.ModuleType("keyring")
    mod.set_password = lambda service, user, pw: store.__setitem__((service, user), pw)
    return mod


def _copy(name: str, dest: pathlib.Path) -> pathlib.Path:
    folder = dest / name
    shutil.copytree(REPO / "supported-devices" / name, folder, ignore=shutil.ignore_patterns("__pycache__", "config.json"))
    return folder


def test_schema_questions_write_config_and_keep_the_password_out_of_it(monkeypatch=None):
    with tempfile.TemporaryDirectory() as td:
        folder = _copy("waters-empower-hplc", pathlib.Path(td))
        store = {}
        saved = sys.modules.get("keyring"); sys.modules["keyring"] = _fake_keyring(store)
        real_discover = NS.discover
        NS.discover = lambda f, cfg, what, sim=False: {"nodes": ["HPLC-NODE-01", "LACE-2"], "systems": [("Arc_HPLC_1", "Arc HPLC")]}.get(what, [])
        try:
            qs = NS.questions_for(folder)
            assert [q.key for q in qs][:4] == ["address", "username", "password", "project"]
            s = Script("?", "emp01.acme.local:3076", "https://emp01.acme.local:3076",   # help, a bad URL, a good one
                       "svc_openmhp", "hunter2", "", "ProcessDev",                        # user, password, an empty required answer, project
                       "2", "1", "")                                                       # node by number, system by number, no export folder
            cfg, missing = NS.interview(folder, qs, s.ask, s.say)
        finally:
            NS.discover = real_discover
            if saved is not None:
                sys.modules["keyring"] = saved
            else:
                sys.modules.pop("keyring", None)
        assert missing == []
        assert s.heard("Web API") and s.heard("start with http")                 # ? printed the help; the bad URL was explained
        assert s.heard("this one is needed")
        assert cfg["address"] == "https://emp01.acme.local:3076" and cfg["username"] == "svc_openmhp"
        assert cfg["node"] == "LACE-2" and cfg["system"] == "Arc_HPLC_1" and cfg["export_dir"] is None
        assert "password" not in cfg and store == {("Empower", "svc_openmhp"): "hunter2"}
        assert s.heard("keyring", "Empower / svc_openmhp")
        assert cfg["verify_tls"] is True and cfg["max_lines"] == 96               # advanced and unlisted keys keep their example values
        assert s.asked("e.g. https://empower-api.lab.local:3076") and s.asked("(1) HPLC-NODE-01") and s.asked("Arc HPLC")
        NS.write_config(folder, cfg)
        on_disk = json.loads((folder / "config.json").read_text())
        assert on_disk["address"] == cfg["address"] and "password" not in on_disk
        assert not (folder / "config.json.bak").exists()
        # a second run: the saved values are the defaults (Enter keeps them) and the old file is kept as .bak
        s2 = Script(*[""] * 8)
        real_discover = NS.discover; NS.discover = lambda *a, **k: []
        try:
            cfg2, missing = NS.interview(folder, [q for q in qs if q.kind != "secret"], s2.ask, s2.say)
        finally:
            NS.discover = real_discover
        assert missing == [] and cfg2["address"] == cfg["address"] and cfg2["node"] == "LACE-2"
        assert not s2.asked("e.g. https://empower-api.lab.local")                 # on a re-run the saved value replaces the example hint
        cfg2["project"] = "QC"
        NS.write_config(folder, cfg2)
        assert json.loads((folder / "config.json.bak").read_text())["project"] == "ProcessDev"
        assert json.loads((folder / "config.json").read_text())["project"] == "QC"


def test_without_a_schema_the_example_strings_are_asked_with_setup_md_as_help():
    with tempfile.TemporaryDirectory() as td:
        folder = pathlib.Path(td) / "my-pump"
        (folder / "references").mkdir(parents=True)
        (folder / "DEVICE.md").write_text("---\nid: my-pump-01\nclass: pump\n---\nbody\n")
        (folder / "config.example.json").write_text(json.dumps({"port": "COM3", "label": "bench", "baud": 9600, "log_dir": "C:/lab/pump"}))
        (folder / "references" / "setup.md").write_text("# Setting up\n\n1. Set `port` to the pump's COM port from Device Manager.\n\n2. Other things.\n")
        qs = NS.fallback_schema(folder)
        assert [(q.key, q.kind) for q in qs] == [("port", "com_port"), ("label", "text"), ("log_dir", "path")]
        assert "Device Manager" in qs[0].help and qs[1].help == ""
        real_ports = NS.serial_ports; NS.serial_ports = lambda: ["COM3", "COM7"]
        try:
            log_dir = pathlib.Path(td) / "logs"
            s = Script("2", "bench 2", str(log_dir), "y")                            # a port by number, text, a folder that gets created
            cfg, missing = NS.interview(folder, qs, s.ask, s.say)
            assert missing == [] and cfg == {"port": "COM7", "label": "bench 2", "baud": 9600, "log_dir": str(log_dir)}
            assert log_dir.is_dir() and s.asked("(1) COM3") and s.asked("Create it?")
            s = Script("COM9", "n", "COM3", "x", str(log_dir))                      # a port off the list is questioned
            cfg, _ = NS.interview(folder, qs, s.ask, s.say)
            assert cfg["port"] == "COM3" and s.asked("COM9 is not in the list")
        finally:
            NS.serial_ports = real_ports
        # no terminal: defaults where they exist, the rest named, nothing written
        cfg, missing = NS.interview(folder, qs, NS.auto_ask, lambda t: None)
        assert missing == ["port", "label", "log_dir"] and not (folder / "config.json").exists()
        cfg, missing = NS.interview(folder, qs, NS.auto_ask, lambda t: None, answers={"port": "COM4", "label": "a", "log_dir": td})
        assert missing == [] and cfg["port"] == "COM4"


def test_setup_package_installs_asks_probes_and_offers_fix_or_stop():
    with tempfile.TemporaryDirectory() as td:
        folder = _copy("globalfia-flopro-sampler", pathlib.Path(td))
        pip_calls = []
        pip_run = lambda argv: (pip_calls.append(argv), types.SimpleNamespace(returncode=0, stdout="ok", stderr=""))[1]
        real_probe, real_ports = NS.probe, NS.serial_ports
        probes = [(False, "COM21 cannot be opened: no such port"), (True, "COM21 opens")]
        NS.probe = lambda f, cfg, sim=False: probes.pop(0)
        NS.serial_ports = lambda: ["COM20", "COM21"]
        try:
            s = Script("y", "1", "f", "2")                                           # install, COM20, fix, COM21
            r = NS.setup_package(folder, s.ask, s.say, sim=False, pip_run=pip_run)
        finally:
            NS.probe, NS.serial_ports = real_probe, real_ports
        assert pip_calls and pip_calls[0][-1] == "pyserial" and pip_calls[0][:3] == [sys.executable, "-m", "pip"]
        assert r["configured"] and r["probe"] is True and r["probe_text"] == "COM21 opens"
        assert json.loads((folder / "config.json").read_text())["port"] == "COM21"
        assert json.loads((folder / "config.json.bak").read_text())["port"] == "COM20"
        assert s.heard("did not answer", "no such port") and s.asked("(f)ix") and s.heard("is ready: COM21 opens")
        assert s.heard("kept at their defaults")
        # stop means stop: nothing further happens
        NS.probe = lambda f, cfg, sim=False: (False, "still no")
        try:
            s = Script("n", "1", "s")
            try:
                NS.setup_package(folder, s.ask, s.say, sim=False, pip_run=pip_run); raise AssertionError("expected Stop")
            except NS.Stop:
                pass
        finally:
            NS.probe = real_probe
        # the simulated twin needs no instrument
        s = Script("n", "2")
        r = NS.setup_package(folder, s.ask, s.say, sim=True, pip_run=pip_run)
        assert r["probe"] is True and "simulated" in r["probe_text"]
        # a package without settings
        folder2 = _copy("ika-c-mag-hs7", pathlib.Path(td))
        s = Script("n")
        r = NS.setup_package(folder2, s.ask, s.say, sim=True, pip_run=pip_run)
        assert r["configured"] and s.heard("needs no settings")


def test_finish_pairs_with_the_gateway_and_installs_the_service():
    from openmhp import relay, service
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        folder = _copy("ika-c-mag-hs7", root)                                       # no config needed, so nothing blocks serving
        joins, installs = [], []
        joiner = lambda url, code, drivers, name=None, quiet=False: (joins.append((url, code, sorted(drivers), name)),
                                                                     {"gateway": url, "name": name, "token": "t"})[1]
        fake_svc = types.SimpleNamespace(status=lambda: {"installed": False},
                                         install=lambda r, b: (installs.append((r, b)), {"ok": True, "note": "running now."})[1],
                                         restart=lambda r, b: {"ok": True})
        real_load = relay.load_node_config; relay.load_node_config = lambda: None
        try:
            s = Script("nonsense", "https://gw.lab.local ab12-cd34", "y")
            out = NS.finish(root, 18900, s.ask, s.say, joiner=joiner, svc=fake_svc, load=lambda folders: {"ika-c-mag-hs7-01": object()})
        finally:
            relay.load_node_config = real_load
        assert joins == [("https://gw.lab.local", "ab12-cd34", ["ika-c-mag-hs7-01"], joins[0][3])] and joins[0][3]
        assert s.asked("not an address and a code") and s.heard("paired with https://gw.lab.local")
        assert installs == [(root, 18900)] and out["service"]["ok"] and out["serve"] is False
        assert s.heard("installed; running now.", "through the gateway")
        # already paired, service installed: restart; and "no" to the service means serve here
        restarts = []
        fake_svc2 = types.SimpleNamespace(status=lambda: {"installed": True}, install=lambda r, b: None,
                                          restart=lambda r, b: (restarts.append((r, b)), {"ok": True})[1])
        relay.load_node_config = lambda: {"gateway": "https://gw.lab.local", "name": "bench-3"}
        try:
            s = Script("y")
            out = NS.finish(root, 18900, s.ask, s.say, joiner=joiner, svc=fake_svc2)
            assert restarts == [(root, 18900)] and s.heard("paired with https://gw.lab.local as 'bench-3'") and not out["serve"]
            s = Script("n")
            out = NS.finish(root, 18900, s.ask, s.say, joiner=joiner, svc=fake_svc)
            assert out["serve"] is True
        finally:
            relay.load_node_config = real_load
        # a package that is not set up stops the flow before the gateway is mentioned
        _copy("globalfia-flopro-sampler", root)
        s = Script()
        out = NS.finish(root, 18900, s.ask, s.say, joiner=joiner, svc=fake_svc)
        assert not out["serve"] and s.heard("not serving yet") and s.heard("mhp node setup globalfia-flopro-sampler") and not s.prompts
        assert NS.parse_pair_line("ab12-cd34 https://gw.lab.local/") == ("https://gw.lab.local", "ab12-cd34")
        assert NS.parse_pair_line("https://gw.lab.local") is None


def test_cli_setup_with_yes_and_set_asks_nothing_and_check_then_passes():
    with tempfile.TemporaryDirectory() as td:
        env = {**os.environ, "OPENMHP_HOME": td, "PYTHONPATH": str(REPO)}
        cli = [sys.executable, "-m", "openmhp.cli", "node"]
        r = subprocess.run([*cli, "add", "globalfia-flopro-sampler", "--from", str(REPO)], capture_output=True, text=True, env=env, cwd=td, stdin=subprocess.DEVNULL)
        assert r.returncode == 0 and "mhp node setup globalfia-flopro-sampler" in r.stderr, r.stderr   # no terminal: the steps are printed
        folder = pathlib.Path(td) / "devices" / "globalfia-flopro-sampler"
        r = subprocess.run([*cli, "--check"], capture_output=True, text=True, env=env, cwd=td)
        assert r.returncode == 1 and "not set up yet" in r.stderr and "mhp node setup globalfia-flopro-sampler" in r.stderr, r.stderr
        r = subprocess.run([*cli, "setup", "globalfia-flopro-sampler", "--yes", "--no-pip"], capture_output=True, text=True, env=env, cwd=td)
        assert r.returncode == 1 and "port still need an answer" in r.stderr and "--set" in r.stderr, r.stderr
        assert not (folder / "config.json").exists() or json.loads((folder / "config.json").read_text())["port"] == "COM21"
        r = subprocess.run([*cli, "setup", "globalfia-flopro-sampler", "--yes", "--no-pip", "--set", "port=COM4"], capture_output=True, text=True, env=env, cwd=td)
        assert r.returncode == 0, r.stderr
        assert json.loads((folder / "config.json").read_text())["port"] == "COM4" and "saved" in r.stderr, r.stderr
        assert "pip install pyserial" in r.stderr, r.stderr                               # --no-pip: named, not run
        r = subprocess.run([*cli, "--check"], capture_output=True, text=True, env=env, cwd=td)
        assert r.returncode == 0 and "ready to serve" in r.stderr, r.stderr
        r = subprocess.run([*cli, "setup", "nope"], capture_output=True, text=True, env=env, cwd=td)
        assert r.returncode == 1 and "no package named nope" in r.stderr


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok ", name)
    shutil.rmtree(_tmp_home, ignore_errors=True)
