"""The gate a device package passes to be shipped in supported-devices/.

Two halves. First, every package this repository already ships must pass, so the bar is one
the repo itself meets rather than one written for other people. Second, the gate is shown
*catching* each thing it claims to catch: a package is built with one fault at a time and the
check that should fail is named. A gate nobody has seen fail is a gate nobody should trust.
"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openmhp.inclusion import check, report                                       # noqa: E402

REPO = Path(__file__).resolve().parents[1]
SHIPPED = sorted(p for p in (REPO / "supported-devices").iterdir()
                 if p.is_dir() and (p / "DEVICE.md").is_file())


def _verdict(result: dict, check_name: str) -> dict:
    """The one check whose name contains `check_name`, so tests name a rule, not an index."""
    found = [c for tier in ("Package", "Submission") for c in result[tier]["checks"]
             if check_name in c["check"]]
    assert len(found) == 1, f"{check_name!r} matched {[c['check'] for c in found]}"
    return found[0]


def _fails(result: dict, check_name: str) -> str:
    c = _verdict(result, check_name)
    assert c["ok"] is False, f"expected {c['check']!r} to fail, got ok={c['ok']} ({c['detail']})"
    assert not result["ok"], "the overall verdict should be a failure too"
    return c["detail"]


def _copy_package(src: Path, dest: Path) -> Path:
    shutil.copytree(src, dest / src.name)
    return dest / src.name


# ----------------------------------------------------- what the repository already ships ---- #

def test_every_shipped_package_passes_the_gate():
    assert len(SHIPPED) >= 8, f"expected the supported-devices packages, found {SHIPPED}"
    for folder in SHIPPED:
        result = check(folder)
        assert result["ok"], f"{folder.name} is shipped but does not pass:\n{report(result)}"


def test_the_safety_checks_really_run_on_the_shipped_packages():
    """A gate that skipped its own safety checks everywhere would pass everything.

    Not every package can be probed by pushing a bound -- a device may bound nothing numeric --
    but the identity check applies to all of them, so it must have actually run on each.
    """
    pushed = 0
    for folder in SHIPPED:
        result = check(folder)
        assert _verdict(result, "handle on the sealed configuration")["ok"] is True, folder.name
        if _verdict(result, "loosening every reported rule")["ok"] is True:
            pushed += 1
            assert _verdict(result, "editing the sealed rules")["ok"] is True, folder.name
    assert pushed >= 5, f"only {pushed} packages had a bound to push; the probe may have stopped working"


# ------------------------------------------------------- the gate catches what it claims ---- #

def test_it_catches_a_driver_that_hands_out_the_dict_the_gate_reads(tmp):
    """The escalation this gate exists for, reintroduced in the one line that reintroduces it."""
    pkg = _copy_package(REPO / "supported-devices" / "ika-c-mag-hs7", tmp)
    sim = pkg / "sim.py"
    sim.write_text(sim.read_text(encoding="utf-8") + '''

    # a driver that answers with its own enforced rules instead of a copy of them
    def rpc_safety_limits(self, p, client):
        return {"settings": {s["name"]: s for s in self._enforced["settings"]},
                "actions": {a["name"]: a for a in self._enforced["actions"]},
                "interlocks": [], "safety": self.enforced_safety}
''', encoding="utf-8")
    result = check(pkg)
    detail = _fails(result, "handle on the sealed configuration")
    assert "safety/limits" in detail and "deepcopy" in detail

    # and the behavioural push must notice it too, by raising the bound through that answer
    pushed = _verdict(result, "loosening every reported rule")
    assert pushed["ok"] is False and "still refused" not in pushed["detail"]


def test_it_catches_a_driver_that_rewrites_what_it_enforces_while_running(tmp):
    pkg = _copy_package(REPO / "supported-devices" / "ika-c-mag-hs7", tmp)
    sim = pkg / "sim.py"
    sim.write_text(sim.read_text(encoding="utf-8") + '''

    def on_write(self, name, value):
        self.descriptor["settings"][0]["limits"]["max"] = 9000      # "just for this run"
        return value
''', encoding="utf-8")
    detail = _fails(check(pkg), "does not change what it enforces")
    assert "self.descriptor" in detail and "on_write" in detail


def test_it_catches_a_driver_that_writes_the_sealed_index(tmp):
    pkg = _copy_package(REPO / "supported-devices" / "ika-c-mag-hs7", tmp)
    sim = pkg / "sim.py"
    sim.write_text(sim.read_text(encoding="utf-8") + '''

    def setup(self):
        self._index = {"signals": {}, "settings": {}, "actions": {}}
''', encoding="utf-8")
    detail = _fails(check(pkg), "does not change what it enforces")
    assert "_index" in detail and "load path" in detail


def test_it_catches_a_driver_that_replaces_a_gate(tmp):
    pkg = _copy_package(REPO / "supported-devices" / "ika-c-mag-hs7", tmp)
    sim = pkg / "sim.py"
    sim.write_text(sim.read_text(encoding="utf-8") + '''

    def _verify_seal(self):
        return None                      # "the seal was getting in the way"
''', encoding="utf-8")
    detail = _fails(check(pkg), "does not override a safety gate")
    assert "_verify_seal" in detail


def test_it_catches_a_shipped_script_that_reaches_for_the_host(tmp):
    pkg = _copy_package(REPO / "supported-devices" / "ika-c-mag-hs7", tmp)
    (pkg / "scripts").mkdir(exist_ok=True)
    (pkg / "scripts" / "warm_up.py").write_text(
        "from openmhp.client import _inprocess\n"
        "for drv in _inprocess.values():\n"
        "    pass\n", encoding="utf-8")
    detail = _fails(check(pkg), "scripts can run under the run sandbox")
    assert "openmhp.client" in detail and "run refuses" in detail


def test_it_catches_a_package_with_no_twin(tmp):
    pkg = _copy_package(REPO / "supported-devices" / "ika-c-mag-hs7", tmp)
    (pkg / "sim.py").unlink()
    result = check(pkg)
    _fails(result, "ships a simulated twin")
    # and the checks that need one are skipped, not quietly passed
    for name in ("handle on the sealed configuration", "editing the sealed rules"):
        assert _verdict(result, name)["ok"] is None


def test_it_catches_an_unexplained_safety_block(tmp):
    pkg = _copy_package(REPO / "supported-devices" / "ika-c-mag-hs7", tmp)
    d = pkg / "descriptor.yaml"
    text = d.read_text(encoding="utf-8")
    assert "watchdog_s: 30" in text, "the fixture's watchdog moved; update this test"
    d.write_text(text.replace("watchdog_s: 30", "watchdog_s: null"), encoding="utf-8")
    detail = _fails(check(pkg), "safety block is declared")
    assert "watchdog_s is null" in detail and "lease" in detail


def test_it_catches_a_package_that_is_not_registered_or_listed(tmp):
    """Copied outside the repo it is unregistered; the Submission tier must say so, not skip it."""
    pkg = _copy_package(REPO / "supported-devices" / "ika-c-mag-hs7", tmp)
    (tmp / "openmhp").mkdir()
    (tmp / "openmhp" / "registry.json").write_text(json.dumps({"packages": []}), encoding="utf-8")
    (tmp / "supported-devices").mkdir()
    (tmp / "supported-devices" / "README.md").write_text("# nothing here\n", encoding="utf-8")
    result = check(pkg, repo=tmp)
    assert "no entry named" in _fails(result, "listed in openmhp/registry.json")
    assert "honest status" in _fails(result, "listed in the supported-devices table")


def test_it_catches_a_committed_config_json(tmp):
    pkg = _copy_package(REPO / "supported-devices" / "elveflow-ob1", tmp)
    (pkg / "config.json").write_text(json.dumps({"device_name": "01C1B2A3", "com": "COM4"}),
                                     encoding="utf-8")
    detail = _fails(check(pkg, repo=REPO), "no site-specific values committed")
    assert "config.json is committed" in detail


def test_the_submission_tier_is_skipped_outside_a_checkout(tmp):
    """Outside the repo these questions have no answer, and a skip says so without failing."""
    pkg = _copy_package(REPO / "supported-devices" / "ika-c-mag-hs7", tmp)
    result = check(pkg, repo=None)
    assert result["Package"]["ok"], report(result)
    assert all(c["ok"] is None for c in result["Submission"]["checks"])
    assert result["ok"], "a package outside a checkout should still pass on its own merits"


if __name__ == "__main__":
    import tempfile
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            if "tmp" in fn.__code__.co_varnames[:fn.__code__.co_argcount]:
                with tempfile.TemporaryDirectory() as d:
                    fn(Path(d))
            else:
                fn()
            print("ok ", name)
