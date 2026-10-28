"""What a device package must pass to be shipped in `supported-devices/`.

    mhp inclusion supported-devices/ika-c-mag-hs7
    mhp inclusion <folder> --json

`mhp validate` asks whether a package is well formed, and answers from the files. This asks
the harder question -- whether a package is fit to hand to somebody else's instrument -- and
answers most of it by *running* the package's simulated twin, because a descriptor is a claim
and a refusal is evidence.

Two tiers, reported separately:

* **Package** applies to any package anywhere, including one that never leaves a lab. It is the
  tier an onboarding agent should run before handing DEVICE.md to the owner.
* **Submission** is what this repository additionally requires to carry a package in
  `supported-devices/`: a twin that needs no vendor library, a registry entry, a row in the
  table, and no site-specific values committed. These checks need the repo around them, so
  outside a checkout they are reported as skipped rather than failed.

The safety checks in the Package tier are the ones worth explaining. A device keeps the
configuration it *enforces* sealed, separate from the copy it reports, and every reporting RPC
hands back a deep copy (see `Driver._reindex`). A package can undo that without meaning to: a
driver that overrides a reporting RPC and returns its own dict, or that rewrites `descriptor`
while the instrument runs, puts the bounds back within reach of whatever is talking to it --
and for an agent-operated instrument, whatever is talking to it includes code an agent wrote.
So this gate mutates every bound the twin reports and then checks that the twin still refuses
the out-of-range write, and separately edits the sealed index to confirm the driver actually
routes through the gates instead of doing its own thing in `on_write`. Both are behavioural:
they would catch a driver that reintroduced the hole by any route, including one not yet
thought of.
"""
from __future__ import annotations

import ast
import copy
import json
from pathlib import Path
from typing import Any, Callable

from .client import LocalDevice, RemoteError
from .package import load_driver, load_package
from .validate import validate

# Set on the driver by the load path and nowhere else. A package that assigns to one of these
# is writing to what the device enforces, which is a person's job, done in the files.
SEALED_ATTRS = ("_enforced", "_index", "_seal_digest")

# Overriding one of these replaces the gate rather than extending the device. `on_write`,
# `on_invoke`, `on_read`, `setup` and `on_estop` are the hooks a package is meant to fill.
GATE_METHODS = ("_gate", "_verify_seal", "_reindex", "_check_setting_value", "_check_state",
                "_check_interlocks", "_check_approval", "_check_lease")

# A run script that reaches for these is refused at runtime (openmhp/runs.py), so a package
# that ships one is shipping something that cannot run.
SCRIPT_BLOCKED_IMPORTS = ("openmhp", "gc")


class _Report:
    """Checks, in the order they were run, each with the evidence for its verdict."""

    def __init__(self) -> None:
        self.tiers: dict[str, list[dict]] = {"Package": [], "Submission": []}

    def add(self, tier: str, name: str, ok: bool | None, detail: str = "") -> None:
        """ok=None means skipped: not applicable here, and not evidence either way."""
        self.tiers[tier].append({"check": name, "ok": ok, "detail": detail})

    def result(self) -> dict:
        out: dict[str, Any] = {}
        for tier, checks in self.tiers.items():
            out[tier] = {"ok": all(c["ok"] is not False for c in checks) and bool(checks),
                         "checks": checks}
        out["ok"] = all(out[t]["ok"] for t in self.tiers)
        out["failures"] = [f"{t}: {c['check']} -- {c['detail']}"
                           for t in self.tiers for c in self.tiers[t] if c["ok"] is False]
        return out


def _guard(fn: Callable, *a, **kw) -> tuple[bool, str]:
    """Run a probe and turn any surprise into a failed check.

    This gate is pointed at packages written by anyone, including ones broken in ways nothing
    here anticipates. A submission gate that raises a traceback has told the author nothing, so
    an unexpected exception is a result: this package does not hold up under being checked.
    """
    try:
        return fn(*a, **kw)
    except Exception as e:                                                        # noqa: BLE001
        return False, (f"the check itself failed with {type(e).__name__}: {e}. Something about "
                       f"this package is not what the protocol assumes")


def _guard_value(fn: Callable, *a):
    """As `_guard`, for a probe that returns a value rather than a verdict."""
    try:
        return fn(*a)
    except Exception:                                                             # noqa: BLE001
        return None


def _refuses(fn: Callable, code: int, *a, **kw) -> tuple[bool, str]:
    """A gate is proved by what it refuses. Returns (ok, evidence)."""
    try:
        fn(*a, **kw)
        return False, f"accepted; expected refusal {code}"
    except RemoteError as e:
        return e.code == code, f"{e.code}" + ("" if e.code == code else f", expected {code}")
    except Exception as e:                                                        # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def _source_trees(folder: Path) -> list[tuple[str, ast.AST]]:
    out = []
    for name in ("driver.py", "sim.py"):
        p = folder / name
        if p.is_file():
            try:
                out.append((name, ast.parse(p.read_text(encoding="utf-8"))))
            except SyntaxError as e:
                out.append((name, e))                                             # reported by the caller
    return out


def _enclosing_function(tree: ast.AST, node: ast.AST) -> str | None:
    """The function a node sits in, so `setup()` can be told from the rest of the file."""
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(n is node for n in ast.walk(fn)):
            return fn.name
    return None


def _writes_to_sealed_config(folder: Path) -> list[str]:
    """Assignments that change what the device enforces, after it has been sealed.

    `setup()` is allowed to extend `self.descriptor`: it runs inside the load path and the
    driver re-seals after it, which is how a driver that discovers its own channels declares
    them. Anywhere else -- `on_write`, `on_invoke`, a helper, module level -- the edit lands
    after the seal, which now stops the device rather than obeying it.
    """
    problems = []
    for name, tree in _source_trees(folder):
        if isinstance(tree, SyntaxError):
            problems.append(f"{name}: does not parse ({tree.msg} line {tree.lineno})")
            continue
        for node in ast.walk(tree):
            targets = []
            if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr in ("update", "setdefault", "pop", "clear"):
                targets = [node.func.value]                                       # descriptor.update(...)
            for t in targets:
                attr = t
                while isinstance(attr, ast.Subscript):                            # descriptor["safety"]["x"] = ...
                    attr = attr.value
                if not isinstance(attr, ast.Attribute):
                    continue
                where = _enclosing_function(tree, node)
                if attr.attr in SEALED_ATTRS:
                    problems.append(f"{name}:{node.lineno} assigns to {attr.attr}, which only the "
                                    f"package load path may set")
                elif attr.attr == "descriptor" and where != "setup":
                    problems.append(f"{name}:{node.lineno} changes self.descriptor in "
                                    f"{where or 'module scope'}; only setup() may, because the "
                                    f"driver re-seals after it")
    return problems


def _overrides_a_gate(folder: Path) -> list[str]:
    problems = []
    for name, tree in _source_trees(folder):
        if isinstance(tree, SyntaxError):
            continue                                                              # already reported
        for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            for fn in cls.body:
                if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.name in GATE_METHODS:
                    problems.append(f"{name}:{fn.lineno} {cls.name}.{fn.name} overrides a safety "
                                    f"gate; put vendor code in on_read/on_write/on_invoke/on_estop")
    return problems


def _script_problems(folder: Path) -> list[str]:
    """Scripts a package ships must be runnable under the run sandbox, which refuses these."""
    problems = []
    for p in sorted((folder / "scripts").glob("**/*.py")) if (folder / "scripts").is_dir() else []:
        rel = p.relative_to(folder).as_posix()
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError as e:
            problems.append(f"{rel}: does not parse ({e.msg} line {e.lineno})")
            continue
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                mods = [node.module]
            for m in mods:
                if m.split(".")[0] in SCRIPT_BLOCKED_IMPORTS:
                    problems.append(f"{rel}:{node.lineno} imports {m}, which a run refuses: a script "
                                    f"gets `lab`, not the host it runs in")
    return problems


# --------------------------------------------------------------------- behavioural safety ---- #

def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _bounded_setting(settings: list[dict]) -> dict | None:
    for s in settings:
        lim = s.get("limits")
        if isinstance(lim, dict) and _num(lim.get("max")) and s.get("approval", "auto") != "forbid":
            return s
    return None


def _bound_to_push(d: dict) -> dict | None:
    """One numeric bound to try to raise, and the call that must be refused when it is raised.

    A setting's `limits` is the obvious one, but plenty of instruments bound nothing else and
    put every real limit on an action parameter instead -- a potentiostat's current, a GC's run
    time. Those are the bounds that matter on those devices, so they are the ones to push.
    """
    s = _bounded_setting(d.get("settings") or [])
    if s:
        return {"kind": "settings", "name": s["name"], "param": None,
                "max": s["limits"]["max"], "example": {}}
    for a in d.get("actions") or []:
        if a.get("approval", "auto") == "forbid" or a.get("methods") is True or not a.get("examples"):
            continue
        for param, bound in (a.get("limits") or {}).items():
            high = (bound[1] if isinstance(bound, (list, tuple)) and len(bound) == 2 and _num(bound[1])
                    else bound.get("max") if isinstance(bound, dict) else None)
            if _num(high):
                return {"kind": "actions", "name": a["name"], "param": param,
                        "max": high, "example": _example(a)}
    return None


def _push(dev: LocalDevice, probe: dict, value: Any):
    """Make the call `probe` describes, with `value` where the bound applies."""
    if probe["kind"] == "settings":
        return dev.write(probe["name"], value, approved=True, dry_run=True)
    return dev.invoke(probe["name"], approved=True, dry_run=True,
                      **{**probe["example"], probe["param"]: value})


def _describe_probe(probe: dict) -> str:
    return probe["name"] if probe["param"] is None else f"{probe['name']}.{probe['param']}"


def _reported_bounds_are_copies(dev: LocalDevice, probe: dict) -> tuple[bool, str]:
    """Loosen every rule the device reports, through every answer that carries one, then call.

    This is the escalation that needed no sandbox escape: a caller handed the dict the gate
    consults could raise a limit with one assignment, and a run script is handed exactly that
    by design. Each answer below must be a copy, so the refusal afterwards is what proves it.
    """
    high = probe["max"]
    raised = high + abs(high) + 1000                                              # unmistakably outside
    answers = []
    for method, params in (("safety/limits", {}),
                           ("device/describe", {"detail": "full"}),
                           ("device/describe", {"detail": "summary"}),
                           ("device/describe", {"select": {probe["kind"]: [probe["name"]]}}),
                           ("settings/list", {}),
                           ("actions/list", {})):
        try:
            answers.append(dev.call(method, params))
        except RemoteError as e:
            return False, f"{method} failed: {e}"
    for answer in answers:
        _loosen(answer, raised)
    ok, evidence = _refuses(_push, -32010, dev, probe, raised)
    if not ok:
        return False, (f"after loosening every reported rule, {_describe_probe(probe)}={raised} "
                       f"{evidence}. A reporting RPC is handing out the dict the gate reads; "
                       f"return a deep copy of it")
    still = _reported_max(dev, probe)
    if still is not None and still != high:
        return False, (f"the device now reports {still} as the bound on {_describe_probe(probe)}; "
                       f"it was {high}. It refused the write, but it is misreporting what it "
                       f"enforces, so an agent would plan against a bound that is not real")
    return True, f"{len(answers)} answers loosened, {_describe_probe(probe)}={raised} still refused ({evidence})"


REPORTING_RPCS = (("device/describe", {"detail": "card"}),
                  ("device/describe", {"detail": "summary"}),
                  ("device/describe", {"detail": "full"}),
                  ("safety/limits", {}),
                  ("signals/list", {}),
                  ("settings/list", {}),
                  ("actions/list", {}))


def _answers_share_nothing_with_the_seal(drv, dev: LocalDevice) -> tuple[bool, str]:
    """No reporting answer may contain an object that is *inside* the sealed configuration.

    The behavioural push below needs a bound to push; this does not, so it is the check that
    applies to every package, including one that bounds nothing numeric today and bounds
    something next release. It is also exact: it does not ask whether an edit got through, it
    asks whether the caller was handed the gate's own dict in the first place.
    """
    sealed: set[int] = set()
    _collect(drv._enforced, sealed)
    _collect(drv._index, sealed)
    shared = []
    for method, params in REPORTING_RPCS:
        try:
            answer = dev.call(method, params)
        except RemoteError as e:
            if e.code == -32050:                                                  # NotSupported: fine, skip it
                continue
            return False, f"{method} failed: {e}"
        found: set[int] = set()
        _collect(answer, found)
        if found & sealed:
            shared.append(f"{method}{'' if not params else ' ' + str(params)}")
    if shared:
        return False, (f"{', '.join(shared)} returned part of the sealed configuration itself, so a "
                       f"caller can change what this device enforces by editing the answer it was "
                       f"given; return copy.deepcopy(...) instead")
    return True, f"{len(REPORTING_RPCS)} reporting answers, none sharing an object with the seal"


def _collect(obj: Any, into: set[int], depth: int = 0) -> None:
    if depth > 12 or not isinstance(obj, (dict, list)):
        return
    into.add(id(obj))
    for v in (obj.values() if isinstance(obj, dict) else obj):
        _collect(v, into, depth + 1)


def _reported_max(dev: LocalDevice, probe: dict) -> Any:
    """What the device says the bound is now, read back through a fresh answer."""
    lim = dev.limits()
    if probe["kind"] == "settings":
        return (lim.get("settings") or {}).get(probe["name"], {}).get("max")
    bound = ((lim.get("actions") or {}).get(probe["name"], {}).get("limits") or {}).get(probe["param"])
    if isinstance(bound, (list, tuple)) and len(bound) == 2:
        return bound[1]
    return bound.get("max") if isinstance(bound, dict) else None


def _loosen(block: Any, to: float) -> None:
    """Raise every bound, clear every interlock, drop every approval, disarm every watchdog."""
    if isinstance(block, dict):
        for k, v in list(block.items()):
            if k == "limits" and isinstance(v, dict):
                for param, bound in list(v.items()):
                    if isinstance(bound, (list, tuple)) and len(bound) == 2 and all(_num(x) for x in bound):
                        v[param] = [-to, to]
                    else:
                        _loosen(bound, to)
            elif k == "max" and _num(v):
                block[k] = to
            elif k == "min" and _num(v):
                block[k] = -to
            elif k == "interlocks" and isinstance(v, list):
                del v[:]
            elif k == "approval" and v in ("confirm", "forbid"):
                block[k] = "auto"
            elif k == "watchdog_s":
                block[k] = None
            else:
                _loosen(v, to)
    elif isinstance(block, list):
        for item in block:
            _loosen(item, to)


def _gate_probes(dev: LocalDevice) -> list[tuple[str, bool | None, str]]:
    """What the twin must refuse, probed one gate at a time.

    `mhp conformance` scores a device against the levels in SPEC 15 and is the right thing to
    run against hardware. It is not this gate: it marks a check failed when the device declares
    nothing to probe -- no bounded setting, no confirm-gated action -- and a selector valve with
    one enum setting is not less fit to ship than a hotplate. So the probes below are the same
    shape, with the difference that a device that declares nothing to test gets a skip and a
    reason. Run `mhp conformance` as well; the levels are what a package's status line claims.
    """
    out: list[tuple[str, bool | None, str]] = []
    d = dev.call("device/describe", {"detail": "full"})

    # every reporting tier answers, because an agent reads them in this order
    try:
        for tier in ("card", "summary", "full"):
            dev.call("device/describe", {"detail": tier})
        dev.call("resources/list", {})
        out.append(("all three describe tiers and resources/list answer", True, ""))
    except RemoteError as e:
        out.append(("all three describe tiers and resources/list answer", False, str(e)))

    out.append(("an unknown name is refused", *_refuses(dev.read, -32040, "almost_certainly_not_a_signal")))

    # a refusal has to be machine-readable: an agent decides whether to retry from these fields,
    # and prose is not a decision it can make
    try:
        dev.read("almost_certainly_not_a_signal")
        out.append(("a refusal carries ts, recovery, transient and effect", False, "nothing was refused"))
    except RemoteError as e:
        missing = [f for f in ("ts", "recovery", "transient", "effect") if getattr(e, f, None) is None]
        out.append(("a refusal carries ts, recovery, transient and effect", not missing,
                    f"missing {missing}" if missing else "all four"))

    setting = _bounded_setting(d.get("settings") or [])
    if setting is None:
        out.append(("an out-of-range write is refused", None, "no setting declares a numeric max"))
    else:
        over = setting["limits"]["max"] + abs(setting["limits"]["max"]) + 1
        out.append((f"an out-of-range write is refused ({setting['name']})",
                    *_refuses(dev.write, -32010, setting["name"], over, approved=True, dry_run=True)))

    gated = [a for a in d.get("actions") or [] if a.get("approval") == "confirm"]
    if gated:
        out.append((f"a confirm-gated action refuses without approval ({gated[0]['name']})",
                    *_refuses(dev.invoke, -32012, gated[0]["name"], **_example(gated[0]))))
    else:
        out.append(("a confirm-gated action refuses without approval", None,
                    "no action declares approval: confirm"))

    # an interlock is only worth declaring if it is consulted, so find one reading false and try
    held = next(((a, i) for a in d.get("actions") or [] for i in a.get("interlocks") or []
                 if _reads_false(dev, i) and a.get("approval", "auto") != "forbid"), None)
    if held:
        action, signal = held
        out.append((f"an open interlock refuses the action ({action['name']} needs {signal})",
                    *_refuses(dev.invoke, -32011, action["name"], approved=True, dry_run=True,
                              **_example(action))))
    else:
        out.append(("an open interlock refuses the action", None,
                    "every declared interlock reads true on the twin, so none can be probed here"))

    # the happy path, with the package's own example: an action whose examples do not run is a
    # worked example an agent will copy and be refused for
    for action in d.get("actions") or []:
        if action.get("approval") in ("confirm", "forbid") or action.get("methods") is True \
                or not action.get("examples"):
            continue
        ok, detail = True, ""
        try:
            dev.invoke(action["name"], dry_run=True, **action["examples"][0])
        except RemoteError as e:
            ok, detail = e.code == -32011, f"{e.code}: {e}"                       # an open interlock is fine
        out.append((f"the first declared example of {action['name']} is accepted as a dry run", ok, detail))

    return out


def _example(action: dict) -> dict:
    ex = action.get("examples") or []
    return dict(ex[0]) if ex and isinstance(ex[0], dict) else {}


def _reads_false(dev: LocalDevice, signal: str) -> bool:
    try:
        return dev.read(signal) is False
    except RemoteError:
        return False


def _safety_is_declared_or_explained(pkg) -> list[str]:
    """A package may have nothing to stop and no watchdog to arm. It may not leave that unsaid.

    `validate` warns here; inclusion does not, because the person reading a shipped package
    cannot ask the author what the blank meant.
    """
    saf = pkg.descriptor.get("safety") or {}
    notes = str(saf.get("notes") or "").strip()
    driver = pkg.dir / "driver.py"
    manual = driver.is_file() and "drivers.manual" in driver.read_text(encoding="utf-8", errors="replace")
    problems = []
    if saf.get("estop") is not True and not (notes or saf.get("estop_kind")):
        problems.append("safety.estop is not true and safety.notes does not say what stops this "
                        "instrument instead")
    if not saf.get("watchdog_s"):
        if not manual:
            problems.append("safety.watchdog_s is null, so operating this device needs no lease and "
                            "nothing notices a controller that dies holding one; declare a window, "
                            "with watchdog_action: release if the work must not be interrupted")
        elif not notes:
            problems.append("an operator-run device declares no watchdog; say so in safety.notes")
    for a in pkg.descriptor.get("actions") or []:
        if a.get("params") and not a.get("examples"):
            problems.append(f"actions.{a['name']} takes parameters but ships no example, so the "
                            f"first caller guesses")
    return problems


def _tamper_is_detected(drv, dev: LocalDevice, probe: dict) -> tuple[bool, str]:
    """Edit the sealed rules in memory: the device must stop, not obey and not quietly ignore.

    A driver that answers writes in `on_write` without going through `_gate` would pass the
    check above by accident -- nothing it reports is the gate's dict, because it has no gate.
    This is how that shows up: the call it should refuse is a legal one, so only the seal can
    be what refuses it.
    """
    kind, name = probe["kind"], probe["name"]
    before = copy.deepcopy(drv._index[kind][name])
    try:
        if probe["param"] is None:
            drv._index[kind][name]["limits"] = {"min": -1e9, "max": 1e9}
        else:
            drv._index[kind][name].setdefault("limits", {})[probe["param"]] = [-1e9, 1e9]
        ok, evidence = _refuses(_push, -32013, dev, probe, probe["max"])
        if not ok:
            return False, (f"with the sealed rules edited in memory, a legal call to "
                           f"{_describe_probe(probe)} {evidence}. Nothing checked the seal, so this "
                           f"driver is not going through Driver._gate")
        return True, f"a legal call was refused with -32013 once the sealed rules were edited ({evidence})"
    finally:
        drv._index[kind][name] = before
        drv._reindex()                                                            # re-seal over the restored copy


# --------------------------------------------------------------------------- the two tiers ---- #

def _package_tier(rep: _Report, folder: Path) -> None:
    pkg = load_package(folder)
    err, warn = validate(pkg, location="checked by the inclusion gate")
    rep.add("Package", "mhp validate reports no errors", not err,
            "; ".join(err) if err else f"{len(warn)} warning(s)")

    for label, problems in (("a driver does not change what it enforces", _writes_to_sealed_config(folder)),
                            ("a driver does not override a safety gate", _overrides_a_gate(folder)),
                            ("shipped scripts can run under the run sandbox", _script_problems(folder))):
        rep.add("Package", label, not problems, "; ".join(problems))

    has_sim = (folder / "sim.py").is_file()
    rep.add("Package", "ships a simulated twin (sim.py)", has_sim,
            "sim.py" if has_sim else "no sim.py: nobody can rehearse against this package, and CI "
                                     "cannot test it without the instrument")
    unsaid = _safety_is_declared_or_explained(pkg)
    rep.add("Package", "the safety block is declared, or says why it is not",
            not unsaid, "; ".join(unsaid))

    if not has_sim:
        for name in ("the twin loads with no vendor library and no config.json",
                     "the gates refuse what they declare",
                     "no reported answer is a handle on the sealed configuration",
                     "loosening every reported rule changes nothing",
                     "editing the sealed rules stops the device"):
            rep.add("Package", name, None, "needs a twin")
        return

    try:
        drv = load_driver(folder, sim=True)
        dev = LocalDevice(drv)
        card = dev.call("device/describe", {"detail": "card"})
    except Exception as e:                                                        # noqa: BLE001
        rep.add("Package", "the twin loads with no vendor library and no config.json", False,
                f"{type(e).__name__}: {e}")
        for name in ("the gates refuse what they declare",
                     "no reported answer is a handle on the sealed configuration",
                     "loosening every reported rule changes nothing",
                     "editing the sealed rules stops the device"):
            rep.add("Package", name, None, "the twin did not load")
        return
    rep.add("Package", "the twin loads with no vendor library and no config.json", True,
            f"{card.get('id')} ({card.get('class')})")

    try:
        probes = _gate_probes(dev)
    except Exception as e:                                                        # noqa: BLE001
        probes = [("the gates refuse what they declare", False,
                   f"probing the gates raised {type(e).__name__}: {e}")]
    for name, ok, detail in probes:
        rep.add("Package", name, ok, detail)

    rep.add("Package", "no reported answer is a handle on the sealed configuration",
            *_guard(_answers_share_nothing_with_the_seal, drv, dev))

    probe = _guard_value(_bound_to_push, dev.call("device/describe", {"detail": "full"}))
    if probe is None:
        why = ("nothing numeric is bounded: no setting declares a max, and no action bounds a "
               "parameter outside a method, so there is no limit here for a caller to try to "
               "raise. Worth a second look -- most instruments have one")
        rep.add("Package", "loosening every reported rule changes nothing", None, why)
        rep.add("Package", "editing the sealed rules stops the device", None, why)
    else:
        rep.add("Package", "loosening every reported rule changes nothing",
                *_guard(_reported_bounds_are_copies, dev, probe))
        rep.add("Package", "editing the sealed rules stops the device",
                *_guard(_tamper_is_detected, drv, dev, probe))


def _submission_tier(rep: _Report, folder: Path, repo: Path | None) -> None:
    name = folder.name
    if repo is None:
        for check in ("listed in openmhp/registry.json", "listed in the supported-devices table",
                      "no site-specific values committed", "says how to reach the real instrument"):
            rep.add("Submission", check, None, "not inside an openmhp checkout")
        return

    try:
        registry = json.loads((repo / "openmhp" / "registry.json").read_text(encoding="utf-8"))
        entry = next((p for p in registry.get("packages", []) if p.get("name") == name), None)
    except (OSError, ValueError) as e:
        entry, registry = None, None
        rep.add("Submission", "listed in openmhp/registry.json", False, f"registry unreadable: {e}")
    if registry is not None:
        rel = f"supported-devices/{name}"
        problems = []
        if entry is None:
            problems.append(f"no entry named {name!r}: agents find community packages through the registry")
        else:
            if not str(entry.get("target", "")).endswith(rel):
                problems.append(f"target {entry.get('target')!r} does not end in {rel}")
            if not entry.get("description") or not entry.get("tags"):
                problems.append("entry needs a description and tags; the registry is searched on them")
            if (folder / "sim.py").is_file() and entry.get("sim") is not True:
                problems.append("the package has a twin but the entry does not say sim: true")
        rep.add("Submission", "listed in openmhp/registry.json", not problems, "; ".join(problems))

    table = (repo / "supported-devices" / "README.md")
    row = ""
    if table.is_file():
        row = next((ln for ln in table.read_text(encoding="utf-8").splitlines()
                    if f"`{name}`" in ln and ln.lstrip().startswith("|")), "")
    status = next((s for s in ("hardware tested", "twin tested", "template") if s in row), None)
    rep.add("Submission", "listed in the supported-devices table", bool(status),
            f"status: {status}" if status else "no row in supported-devices/README.md with an honest "
                                               "status (hardware tested | twin tested | template)")

    # config.json is the one file that is always this lab's and never a package's: addresses,
    # serial numbers, COM ports. It is gitignored, so a committed one means it slipped in.
    committed = [p.relative_to(folder).as_posix() for p in folder.rglob("config.json")]
    needs_config = any("config.json" in (folder / f).read_text(encoding="utf-8", errors="replace")
                       for f in ("driver.py", "sim.py") if (folder / f).is_file())
    problems = [f"{c} is committed; ship config.example.json instead" for c in committed]
    if needs_config and not (folder / "config.example.json").is_file():
        problems.append("the driver reads config.json but no config.example.json ships, so nobody "
                        "knows what to put in it")
    rep.add("Submission", "no site-specific values committed", not problems, "; ".join(problems))

    setup = folder / "references" / "setup.md"
    vendor = needs_config or "hardware tested" == status
    if setup.is_file():
        text = setup.read_text(encoding="utf-8")
        first_test = "first" in text.lower() and "test" in text.lower()
        rep.add("Submission", "says how to reach the real instrument", True,
                f"references/setup.md, {len(text.splitlines())} lines"
                + ("" if first_test else "; consider a first-hardware-test section"))
    else:
        rep.add("Submission", "says how to reach the real instrument", not vendor,
                "no references/setup.md, and the driver needs a vendor library or config"
                if vendor else "no vendor setup needed")


def _find_repo(folder: Path) -> Path | None:
    for p in [folder, *folder.parents]:
        if (p / "openmhp" / "registry.json").is_file() and (p / "supported-devices").is_dir():
            return p
    return None


def check(folder: str | Path, repo: str | Path | None = None) -> dict:
    """Run both tiers over one device package folder."""
    folder = Path(folder).resolve()
    rep = _Report()
    _package_tier(rep, folder)
    _submission_tier(rep, folder, Path(repo).resolve() if repo else _find_repo(folder))
    out = rep.result()
    out["_package"] = {"folder": folder.name, "path": str(folder)}
    return out


def report(result: dict) -> str:
    lines = [f"Inclusion check: {result.get('_package', {}).get('folder')}", ""]
    for tier in ("Package", "Submission"):
        r = result.get(tier)
        if not r:
            continue
        lines.append(f"{tier}: {'PASS' if r['ok'] else 'FAIL'}")
        for c in r["checks"]:
            mark = "x" if c["ok"] else ("-" if c["ok"] is None else " ")
            lines.append(f"  [{mark}] {c['check']}" + (f"  -- {c['detail']}" if c["detail"] else ""))
        lines.append("")
    lines.append("READY" if result["ok"] else f"{len(result['failures'])} check(s) to fix")
    lines.append("[-] is skipped: not applicable here, and not evidence either way.")
    return "\n".join(lines)


def main(argv=None) -> int:
    import sys
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        sys.exit("usage: mhp inclusion <device package folder> [--json]")
    result = check(argv[0])
    print(json.dumps(result, indent=2, default=str) if "--json" in argv else report(result))
    return 0 if result["ok"] else 1
