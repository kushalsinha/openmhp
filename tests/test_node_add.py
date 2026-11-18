"""`mhp node add <package> [<dir>]`: a device package lands on the instrument PC with its config.json,
from the registry's repository tarball or from a local folder, and the person is told what to do next."""
from __future__ import annotations

import io
import json
import os
import pathlib
import sys
import tarfile
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from openmhp import node_add                                              # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[1]


def _repo_tarball(tmp: pathlib.Path, names: list[str]) -> pathlib.Path:
    """What codeload.github.com hands out: everything under one '<repo>-<ref>/' folder."""
    out = tmp / "openmhp-main.tar.gz"
    with tarfile.open(out, "w:gz") as tar:
        for n in names:
            tar.add(REPO / "supported-devices" / n, arcname=f"openmhp-main/supported-devices/{n}",
                    filter=lambda m: None if "__pycache__" in m.name or m.name.endswith("config.json") else m)
        info = tarfile.TarInfo("openmhp-main/supported-devices/evil/DEVICE.md")       # a link must never be extracted
        info.type = tarfile.SYMTYPE; info.linkname = "/etc/passwd"
        tar.addfile(info)
        payload = b"x"
        info = tarfile.TarInfo("openmhp-main/../escape.txt"); info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    return out


def test_registry_names_match_the_shipped_packages():
    names = {e["name"] for e in node_add.available()}
    shipped = {p.name for p in (REPO / "supported-devices").iterdir() if (p / "DEVICE.md").is_file()}
    assert shipped <= names, shipped - names
    text = node_add.say_available()
    assert "waters-empower-hplc" in text and "mhp node add <name>" in text


def test_add_from_a_local_folder_creates_config_and_says_what_is_next():
    with tempfile.TemporaryDirectory() as td:
        dest = pathlib.Path(td) / "devices"
        r = node_add.add("waters-empower-hplc", dest, source=REPO / "supported-devices")
        folder = pathlib.Path(r["folder"])
        assert folder == dest / "waters-empower-hplc" and (folder / "DEVICE.md").is_file() and (folder / "driver.py").is_file()
        assert r["config_created"] and "address" in json.loads((folder / "config.json").read_text())
        assert not (folder / "__pycache__").exists()
        assert r["valid"], r["errors"]
        assert any("opti-hplc-handler" in p for p in r["pip"]), r["pip"]
        text = node_add.say_next(r, joined=None, service_installed=False)
        assert "pip install" in text and "config.json" in text and f"mhp node setup waters-empower-hplc {dest}" in text and "--join" in text
        assert "address" in text and "project, username" in text, text            # the keys to fill in, not "ports, addresses, names"
        assert text.count(str(dest)) == 3, text                                     # the folder is named where it is needed, not on every line
        text = node_add.say_next(r, joined={"gateway": "https://gw.office", "name": "bench-3"}, service_installed=True)
        assert "gw.office" in text and "--install-service" in text
        # Windows-only vendor software is said so on another OS; the Empower Web API package runs anywhere
        assert not r["windows_only"]
        rw = node_add.add("elveflow-ob1", dest, source=REPO / "supported-devices")
        assert rw["windows_only"]
        assert ("Windows" in node_add.say_next(rw, None, False)) == (sys.platform != "win32")
        # a second add must not clobber the lab's filled-in config.json
        (folder / "config.json").write_text('{"backend": "toolkit"}')
        try:
            node_add.add("waters-empower-hplc", dest, source=REPO / "supported-devices"); raise AssertionError("expected a refusal")
        except FileExistsError as e:
            assert "config.json" in str(e)
        assert json.loads((folder / "config.json").read_text()) == {"backend": "toolkit"}
        # --from pointing straight at the package folder, or at a checkout root, both work
        r2 = node_add.add("ika-c-mag-hs7", dest, source=REPO / "supported-devices" / "ika-c-mag-hs7")
        r3 = node_add.add("sri-8610c-gc", dest, source=REPO)
        assert r2["valid"] and r3["valid"]


def test_add_from_the_repository_tarball_takes_one_folder_and_nothing_unsafe():
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        tar = _repo_tarball(tmp, ["globalfia-flopro-sampler", "ika-c-mag-hs7"])
        dest = tmp / "devices"
        # the registry entry's github: target, with the download pointed at the local archive
        r = node_add.add("globalfia-flopro-sampler", dest, source=tar.as_uri())
        folder = pathlib.Path(r["folder"])
        assert (folder / "DEVICE.md").is_file() and (folder / "references" / "setup.md").is_file()
        assert (folder / "config.json").is_file() and r["valid"], r["errors"]
        assert not (dest / "ika-c-mag-hs7").exists() and not (dest / "evil").exists()
        assert not list(tmp.rglob("escape.txt")) and not list(dest.rglob("*.partial"))
        # a plain .tar.gz path works the same, and a package the archive lacks is a clear error
        r = node_add.add("ika-c-mag-hs7", dest, source=tar)
        assert r["valid"]
        try:
            node_add.add("elveflow-ob1", dest, source=tar); raise AssertionError("expected a refusal")
        except FileNotFoundError as e:
            assert "no device package" in str(e)
        assert not (dest / "elveflow-ob1").exists() and not (dest / ".elveflow-ob1.partial").exists()


def test_shipped_packages_install_with_no_web_or_git():
    """Every registry package ships in the wheel: `mhp node add <name>` and `mhp lab add github:...` copy it locally."""
    from openmhp import bundled, fleet
    def no_network(*a, **kw):
        raise AssertionError("went to the network for a package that ships with OpenMHP")
    real_fetch = node_add.fetch
    node_add.fetch = no_network
    import subprocess
    real_sub = subprocess.run
    subprocess.run = no_network
    try:
        with tempfile.TemporaryDirectory() as td:
            r = node_add.add("ika-c-mag-hs7", pathlib.Path(td) / "devices")
            assert r["valid"] and "shipped with OpenMHP" in r["origin"], r
            assert not list((pathlib.Path(td) / "devices").rglob("__pycache__"))
            f = fleet.Fleet(pathlib.Path(td) / "fleet.json")
            folder = f.fetch_github("kushalsinha/openmhp/supported-devices/waters-empower-hplc")
            assert (folder / "DEVICE.md").is_file() and pathlib.Path(td) in folder.parents
    finally:
        node_add.fetch = real_fetch
        subprocess.run = real_sub
    # every registry entry has its shipped copy, and only the home repository at main is taken from it
    from openmhp import registry
    entries = registry.load()
    assert len(entries) > 50
    for e in entries:
        assert bundled.for_target(e["target"]) is not None, e["name"]
    assert bundled.for_target("github:kushalsinha/openmhp/supported-devices/ika-c-mag-hs7") is not None
    assert bundled.for_target("github:kushalsinha/openmhp/supported-devices/ika-c-mag-hs7@main") is not None
    assert bundled.for_target("github:kushalsinha/openmhp/supported-devices/ika-c-mag-hs7@v0.9.0") is None
    assert bundled.for_target("github:someone/fork/supported-devices/ika-c-mag-hs7") is None
    assert bundled.for_target("github:kushalsinha/openmhp/supported-devices/no-such-package") is None
    # `mhp lab add <name>` takes a ready-made package by name, through the shipped copy
    assert fleet.Fleet._normalize("ika-c-mag-hs7") == "github:kushalsinha/openmhp/supported-devices/ika-c-mag-hs7"
    try:
        fleet.Fleet._normalize("no-such-package"); raise AssertionError("expected a refusal")
    except ValueError as e:
        assert "ready-made package's name" in str(e)


def test_join_on_a_pc_whose_node_runs_as_a_service():
    """`mhp node --join <url> <code>` where the background service holds the ports: join without serving, then restart
    the service (it connects by itself). With --install-service, join first, then install. Never only one of the two."""
    import contextlib, io
    from openmhp import cli, relay as R, service as svc
    calls = []
    saved = (R.join, svc.status, svc.installed_record, svc.restart, svc.install)
    R.join = lambda url, code, drivers, name=None, **kw: calls.append(("join", url, code, drivers)) or \
        {"gateway": url, "name": "bench-1"}
    svc.status = lambda: {"installed": True, "running": True, "path": "/x"}
    svc.installed_record = lambda: {"folder": "/srv/devices", "http": 19000, "python": sys.executable}
    svc.restart = lambda folder, base: calls.append(("restart", str(folder), base)) or {"ok": True, "steps": []}
    svc.install = lambda folder, base, dry_run=False: calls.append(("install", str(folder), base)) or \
        {"ok": True, "steps": [], "path": "/x", "content": "", "dry_run": False}
    try:
        with tempfile.TemporaryDirectory() as td:
            dev = pathlib.Path(td) / "devices"
            node_add.add("ika-c-mag-hs7", dev)
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = cli.main(["node", str(dev), "--join", "https://gw:8443", "ab12-cd34"])
            assert code == 0, err.getvalue()
            assert calls == [("join", "https://gw:8443", "ab12-cd34", {}), ("restart", "/srv/devices", 19000)], calls
            assert "joined gateway https://gw:8443 as 'bench-1'" in err.getvalue()
            calls.clear()
            svc.status = lambda: {"installed": False, "running": None, "path": "/x"}
            with contextlib.redirect_stderr(io.StringIO()):
                code = cli.main(["node", str(dev), "--join", "https://gw:8443", "ab12-cd34", "--install-service"])
            assert code == 0 and [c[0] for c in calls] == ["join", "install"], calls
    finally:
        R.join, svc.status, svc.installed_record, svc.restart, svc.install = saved


def test_unknown_names_and_bad_sources_are_refused_in_words():
    with tempfile.TemporaryDirectory() as td:
        dest = pathlib.Path(td)
        try:
            node_add.add("agilent-1290", dest); raise AssertionError("expected a refusal")
        except LookupError as e:
            assert "Known packages" in str(e) and "waters-empower-hplc" in str(e) and "--from" in str(e)
        try:
            node_add.add("waters-empower-hplc", dest, source=dest / "nowhere"); raise AssertionError("expected a refusal")
        except FileNotFoundError as e:
            assert "DEVICE.md" in str(e)
        assert node_add.parse_github("github:kushalsinha/openmhp/supported-devices/ika-c-mag-hs7@v1") == \
            ("kushalsinha", "openmhp", "supported-devices/ika-c-mag-hs7", "v1")
        assert node_add.parse_github("github:kushalsinha/openmhp/supported-devices/ika-c-mag-hs7")[3] == "main"


def test_cli_add_and_plain_node_find_the_default_directory():
    import subprocess
    with tempfile.TemporaryDirectory() as td:
        env = {**os.environ, "OPENMHP_HOME": td, "PYTHONPATH": str(REPO)}
        r = subprocess.run([sys.executable, "-m", "openmhp.cli", "node", "add"], capture_output=True, text=True, env=env, cwd=td)
        assert r.returncode == 0 and "cytiva-akta-avant" in r.stderr, r.stderr
        r = subprocess.run([sys.executable, "-m", "openmhp.cli", "node", "add", "globalfia-flopro-sampler", "--from", str(REPO)],
                           capture_output=True, text=True, env=env, cwd=td)
        assert r.returncode == 0, r.stderr
        folder = pathlib.Path(td) / "devices" / "globalfia-flopro-sampler"
        assert (folder / "config.json").is_file() and str(folder) in r.stderr and "mhp node setup" in r.stderr, r.stderr
        assert "pip install -U pyserial" in r.stderr and "fill in port" in r.stderr, r.stderr
        assert "3. mhp node setup globalfia-flopro-sampler   (" in r.stderr and "4. mhp node   (" in r.stderr, r.stderr   # default folder: no path
        # a package without a config.example.json (the IKA hotplate) needs no config step
        r = subprocess.run([sys.executable, "-m", "openmhp.cli", "node", "add", "ika-c-mag-hs7", "--from", str(REPO)],
                           capture_output=True, text=True, env=env, cwd=td)
        assert r.returncode == 0 and "config.json" not in r.stderr, r.stderr
        r = subprocess.run([sys.executable, "-m", "openmhp.cli", "node", "add", "nope"], capture_output=True, text=True, env=env, cwd=td)
        assert r.returncode == 1 and "could not add nope" in r.stderr
        # plain `mhp node --check` from an empty folder falls back to the directory `add` filled
        r = subprocess.run([sys.executable, "-m", "openmhp.cli", "node", "--check"], capture_output=True, text=True, env=env, cwd=td)
        # the flopro config.json is still the example, so --check names it and exits 1; the IKA needs nothing
        assert r.returncode == 1 and "globalfia-flopro-sampler: not set up yet" in r.stderr and "then run again:  mhp node" in r.stderr, r.stderr


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok ", name)
