"""Validate a device package. Used by `mhp validate <folder>` and the onboarding skill."""
from __future__ import annotations

import re

from .package import DevicePackage, load_package

TYPES = {"number", "integer", "boolean", "string", "object", "array"}
APPROVAL = {"auto", "confirm", "forbid"}


def validate(pkg: DevicePackage, location: str | None = None) -> tuple[list[str], list[str]]:
    """Return (errors, warnings).

    `location` is where the device actually stands, when the caller knows it (a fleet record, which is
    the authority once a device is installed). A distributable package cannot know its own location, so
    an empty one in the frontmatter is only worth mentioning when nothing else supplies it.
    """
    err, warn = [], []
    m, d = pkg.meta, pkg.descriptor
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", str(m.get("id", ""))):
        err.append("frontmatter id missing or not lowercase-hyphenated")
    if not m.get("class"):
        err.append("frontmatter class missing")
    desc = str(m.get("description", ""))
    if not desc:
        err.append("frontmatter description missing")
    elif len(desc) > 1024:
        err.append(f"description is {len(desc)} chars (max 1024)")
    elif len(desc) < 60:
        warn.append("description is very short; say what it is and when to pick it")
    if not m.get("tags"):
        err.append("frontmatter tags missing (directory filters on them)")
    if not (str(location or "").strip() or str(m.get("location") or "").strip()):
        warn.append("no location: say where this device stands with `mhp lab location <id> \"bay 3\"` "
                    "(or mhp_lab op='location'); the directory filters on it")
    body = pkg.instructions
    if len(body) < 200:
        warn.append("DEVICE.md body is short; agents rely on it once they pick the device")
    if "## Operating procedure" not in body:
        warn.append("DEVICE.md has no '## Operating procedure' section")
    for rel in re.findall(r"`((?:references|scripts)/[^`]+)`", body):
        if rel not in pkg.resources:
            err.append(f"DEVICE.md mentions {rel} but the file is missing")
    sigs = {s.get("name") for s in d.get("signals", [])}
    for sect in ("signals", "settings", "actions"):
        names = [x.get("name") for x in d.get(sect, [])]
        if len(names) != len(set(names)):
            err.append(f"{sect}: duplicate names")
    for s in d.get("signals", []) + d.get("settings", []):
        if s.get("type", "number") not in TYPES:
            err.append(f"{s.get('name')}: bad type {s.get('type')}")
    for s in d.get("settings", []):
        lim = s.get("limits")
        if s.get("type", "number") in ("number", "integer"):
            if not isinstance(lim, dict) or ("min" not in lim and "max" not in lim):
                err.append(f"settings.{s.get('name')}: numeric setting needs limits with min and/or max")
            elif "min" not in lim or "max" not in lim:
                warn.append(f"settings.{s.get('name')}: only one bound declared ({sorted(lim)})")
        if s.get("approval", "auto") not in APPROVAL:
            err.append(f"settings.{s.get('name')}: bad approval")
        if "during_job" in s and not isinstance(s["during_job"], bool):
            err.append(f"settings.{s.get('name')}: during_job must be true or false")
    for a in d.get("actions", []):
        if a.get("approval", "auto") not in APPROVAL:
            err.append(f"actions.{a.get('name')}: bad approval")
        if a.get("duration", "short") not in ("short", "long"):
            err.append(f"actions.{a.get('name')}: duration must be short|long")
        for i in a.get("interlocks", []):
            if i not in sigs:
                err.append(f"actions.{a.get('name')}: interlock '{i}' is not a signal")
        if a.get("approval", "auto") == "auto" and not a.get("interlocks"):
            warn.append(f"actions.{a.get('name')}: auto action with no interlocks; confirm this is safe")
        declared = a.get("params") if isinstance(a.get("params"), dict) else None
        for pname, bound in (a.get("limits") or {}).items():
            if declared is not None and pname not in declared:
                err.append(f"actions.{a.get('name')}: limits name undeclared parameter '{pname}'")
            ok_list = isinstance(bound, (list, tuple)) and len(bound) == 2
            ok_dict = isinstance(bound, dict) and bool({"min", "max", "enum"} & set(bound))
            if not (ok_list or ok_dict):
                err.append(f"actions.{a.get('name')}: malformed limits for '{pname}' (use [min, max], {{min, max}} or {{enum: [...]}})")
        for req in a.get("required") or []:
            if declared is not None and req not in declared:
                err.append(f"actions.{a.get('name')}: required parameter '{req}' is not declared in params")
        for flag in ("concurrent", "pausable", "cancellable", "methods"):
            if flag in a and not isinstance(a[flag], bool):
                err.append(f"actions.{a.get('name')}: {flag} must be true or false")
        if a.get("methods") is True and not a.get("params"):
            warn.append(f"actions.{a.get('name')}: method-driven but declares no params; a method cannot be validated when saved")
        if a.get("params") and not a.get("examples"):
            warn.append(f"actions.{a.get('name')}: has params but no examples")
    saf = d.get("safety") or {}
    if "estop" not in saf:
        err.append("safety.estop missing (true/false)")
    if "watchdog_s" not in saf:
        err.append("safety.watchdog_s missing (a number of seconds, or null)")
    serial = d.get("serial")
    if saf.get("estop") is True and isinstance(serial, dict) and not serial.get("estop"):
        err.append("safety.estop is true but serial.estop lists no stop commands")
    driver_py = pkg.dir / "driver.py"
    manual = driver_py.is_file() and "drivers.manual" in driver_py.read_text(errors="replace")
    if manual and saf.get("estop") is True:
        warn.append("operator-run instrument declares estop: true; a request to a person is not an automatic stop (use estop: false, estop_kind: operator)")
    if manual and saf.get("watchdog_s"):
        warn.append("operator-run instrument declares a watchdog; nothing stops automatically if the agent goes silent")
    if "driver.py" not in pkg.resources:
        warn.append("no driver.py in the package")
    # methods/ (SPEC 4.5): only on devices that declare a method-driven action, and only well-formed records
    from .methods import MethodStore
    driven = [a["name"] for a in d.get("actions", []) if a.get("methods") is True]
    mdir = pkg.dir / "methods"
    if mdir.exists() and not driven:
        err.append("methods/ folder present but no action is declared with methods: true (M1)")
    if mdir.exists() and not mdir.is_dir():
        err.append("methods must be a folder")
    if mdir.is_dir() and driven:
        store = MethodStore(mdir, capable=True, method_driven=lambda: driven)
        err += store.problems()
        for m in store.list():
            if m.get("validated") is None:
                warn.append(f"methods/{m['project']}/{m['name']}: never validated by the device; save it through methods/save once")
    return err, warn


def validate_path(path: str, location: str | None = None) -> dict:
    err, warn = validate(load_package(path), location=location)
    return {"ok": not err, "errors": err, "warnings": warn}


def main(argv=None):
    import sys
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        sys.exit("usage: mhp validate <device package folder>")
    r = validate_path(argv[0])
    for e in r["errors"]:
        print("error", e)
    for w in r["warnings"]:
        print("warn ", w)
    print("OK" if r["ok"] else f"{len(r['errors'])} error(s)")
    return 0 if r["ok"] else 1
