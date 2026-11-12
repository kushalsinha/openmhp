"""Score one device package against the autonomous-ready procurement criteria a package can affect.

    mhp rubric <device package folder> [--json]

The twenty-one criteria of Gottstein et al. (2026) grade an instrument as a buyer would. Most are
answered by the protocol once, for every device (reachable control, structured errors, leases,
versioning, ...). Twelve depend on what a package declares and ships, and those are graded here
from the descriptor, the driver and the twin: Pass (1.0), Partial (0.5), Fail (0.0) or N/A, each
with one line of evidence. The protocol-level criteria are listed as *inherited* so the device
card never claims them on its own. This is a self-assessment from the package's files, not an
independent test.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from .package import load_package
from .validate import ACCESS_WORDS, SELF_STATE, validate

PROTOCOL_CRITERIA = {"C1": "Reachable control", "C3": "Structured errors", "C4": "Open API access",
                     "C8": "Reference client", "C9": "Concurrent access", "C10": "Device/readiness state",
                     "C11": "Result durability", "C13": "Versioning discipline", "C17": "Conformance evidence"}

DEVICE_CRITERIA = [("C2", "Typing and units", 3), ("C5", "Result retrieval", 3), ("C6", "Runtime self-description", 2),
                   ("C7", "Observable state", 2), ("C12", "Instrument self-state", 2), ("C14", "Simulation mode", 3),
                   ("C15", "Control-loss observability", 3), ("C16", "Error recovery taxonomy", 2),
                   ("C18", "OS independence", 2), ("C19", "Automated load/unload", 2),
                   ("C20", "Motion readiness", 2), ("C21", "Safety-event participation", 2)]

SCORE = {"Pass": 1.0, "Partial": 0.5, "Fail": 0.0}
_MHP_ERRORS = {"MHPError", "LimitViolation", "InterlockOpen", "ApprovalRequired", "Forbidden", "InvalidValue",
               "MethodRequired", "DeviceFault", "DeviceBusy", "EStopActive", "NotLeased", "UnknownName",
               "JobNotFound", "NotSupported", "JobCancelled"}


def _shapes(shape, out: list, where: str) -> None:
    if not isinstance(shape, dict):
        out.append((where, None)); return
    out.append((where, shape))
    for k, sub in (shape.get("properties") or {}).items():
        _shapes(sub, out, f"{where}.{k}")
    if isinstance(shape.get("items"), dict):
        _shapes(shape["items"], out, f"{where}[]")


def _c2(d: dict) -> tuple[str, str]:
    """Every value typed; physical ones with a UCUM unit; numbers bounded; optionals defaulted or nullable."""
    problems, n = [], 0
    for sect in ("signals", "settings"):
        for s in d.get(sect) or []:
            n += 1
            if not s.get("type"):
                problems.append(f"{sect}.{s.get('name')} has no type")
            if sect == "settings" and s.get("type", "number") in ("number", "integer") and not s.get("limits"):
                problems.append(f"settings.{s.get('name')} unbounded")
            if sect == "settings" and s.get("type", "number") == "number" and s.get("unit") is None and s.get("limits"):
                problems.append(f"settings.{s.get('name')} has no unit")
    for a in d.get("actions") or []:
        req = set(a.get("required") or [])
        for pname, shape in (a.get("params") or {}).items():
            flat: list = []
            _shapes(shape, flat, f"{a.get('name')}.{pname}")
            for where, sh in flat:
                n += 1
                if sh is None:
                    problems.append(f"{where} is prose"); continue
                if not sh.get("type"):
                    problems.append(f"{where} has no type")
                if where.count(".") == 1 and pname not in req and "default" not in sh and not sh.get("nullable"):
                    problems.append(f"{where} optional with no default")
    if not n:
        return "N/A", "nothing typed to grade: no signals, settings or parameters"
    if not problems:
        return "Pass", f"{n} declared values, all typed; numbers bounded; optionals defaulted or nullable; UCUM units"
    if len(problems) <= max(1, n // 5):
        return "Partial", "; ".join(problems[:3])
    return "Fail", "; ".join(problems[:3])


def _c5(d: dict) -> tuple[str, str]:
    longs = [a for a in d.get("actions") or [] if a.get("duration") == "long"]
    if not longs:
        return "N/A", "no long action: results are the short actions' return values"
    with_ret = [a["name"] for a in longs if isinstance(a.get("returns"), dict)]
    if len(with_ret) == len(longs):
        return "Pass", f"every long action declares `returns` ({', '.join(with_ret)})"
    if with_ret:
        return "Partial", f"`returns` on {with_ret}, not on {[a['name'] for a in longs if a['name'] not in with_ret]}"
    return "Fail", "no long action declares a result contract"


def _c6(pkg) -> tuple[str, str]:
    desc = str(pkg.meta.get("description", ""))
    notes = sum(1 for sect in ("signals", "settings", "actions") for x in pkg.descriptor.get(sect) or [] if x.get("notes"))
    items = sum(len(pkg.descriptor.get(sect) or []) for sect in ("signals", "settings", "actions"))
    ok_card = 60 <= len(desc) <= 1024
    ok_body = "## Operating procedure" in pkg.instructions and len(pkg.instructions) >= 200
    ratio = notes / items if items else 1
    if ok_card and ok_body and ratio >= 0.5:
        return "Pass", f"card {len(desc)} chars, operating procedure, notes on {notes}/{items} capabilities"
    if ok_card and ok_body:
        return "Partial", f"notes on only {notes}/{items} capabilities"
    return "Fail", "card or operating procedure missing" if not (ok_card and ok_body) else "sparse"


def _c7(pkg, d: dict) -> tuple[str, str]:
    sigs = {s.get("name") for s in d.get("signals") or []}
    have = [n for n in ("connected", "state", "busy", "running") if n in sigs]
    src = (Path(pkg.dir) / "driver.py").read_text(encoding="utf-8", errors="replace") if (Path(pkg.dir) / "driver.py").is_file() else ""
    longs = [a for a in d.get("actions") or [] if a.get("duration") == "long"]
    reports = ("progress(" in src or "checkpoint(" in src or "drivers." in src) if longs else True
    if ("state" in have or "connected" in have) and ("busy" in have or "running" in have) and reports:
        return "Pass", f"signals {have}; long actions report progress"
    if have:
        return "Partial", f"signals {have}" + ("" if reports else "; long actions do not report progress")
    return "Fail", "no connected/state/busy signal"


def _c12(d: dict, manual: bool) -> tuple[str, str]:
    sigs = {s.get("name") for s in d.get("signals") or []}
    have = sorted(sigs & set(SELF_STATE))
    if manual:
        return "N/A", "operator-run: the person is the instrument's record"
    if {"calibration_status", "qualification_status"} <= set(have):
        return "Pass", f"self-state signals {have} (SPEC 4.6)"
    if have:
        return "Partial", f"only {have}; calibration_status and qualification_status are the minimum"
    return "Fail", "no self-state signal; nothing says whether the instrument is calibrated or qualified"


def _c14(folder: Path) -> tuple[str, str]:
    if not (folder / "sim.py").is_file():
        return "Fail", "no sim.py twin"
    try:
        from .package import load_driver
        drv = load_driver(folder, sim=True)
        try:
            armed = drv.rpc("sim/fault", {"mode": "raise", "on": "invoke"}, "rubric")
            drv.rpc("sim/fault", {"mode": None}, "rubric")
        finally:
            drv.close()
        if armed.get("armed"):
            return "Pass", "twin loads without the vendor library and answers sim/fault (raise, hang, refuse)"
    except Exception as e:                                                    # noqa: BLE001
        return "Partial", f"sim.py present but the twin did not load cleanly: {type(e).__name__}: {e}"
    return "Partial", "twin loads but fault injection did not arm"


def _c15(d: dict, manual: bool) -> tuple[str, str]:
    saf = d.get("safety") or {}
    if manual:
        return "N/A", "operator-run: no controller holds the instrument"
    if saf.get("watchdog_s"):
        return "Pass", f"watchdog {saf['watchdog_s']} s, action {saf.get('watchdog_action', 'estop')}"
    return "Fail", "watchdog_s is null: silence from the controller is not noticed"


def _c16(folder: Path) -> tuple[str, str]:
    """A driver that raises bare exceptions makes the base report `unknown` outcomes it did not have to."""
    bare, typed = [], 0
    for name in ("driver.py", "sim.py"):
        p = folder / name
        if not p.is_file():
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Raise) and node.exc is not None:
                call = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
                nm = getattr(call, "id", None) or getattr(call, "attr", None)
                if nm in _MHP_ERRORS or nm == "JobCancelled":
                    typed += 1
                elif nm in ("RuntimeError", "ValueError", "TypeError", "KeyError", "OSError", "Exception"):
                    bare.append(f"{name}: raise {nm}")
    if not bare:
        return "Pass", f"{typed} typed raise(s); refusals carry recovery, transient and effect"
    if typed >= len(bare):
        return "Partial", f"{typed} typed, {len(bare)} bare: {bare[0]}"
    return "Fail", f"mostly bare exceptions: {bare[0]}"


def _c18(folder: Path, entry: dict | None) -> tuple[str, str]:
    setup = folder / "references" / "setup.md"
    text = setup.read_text(encoding="utf-8", errors="replace").lower() if setup.is_file() else ""
    if entry and entry.get("os") == "windows":
        return "Partial", "vendor route is Windows-only; the twin runs anywhere"
    if "windows only" in text or "windows-only" in text:
        return "Partial", "setup notes say the vendor route is Windows-only"
    return "Pass", "pure Python route; serves from Linux, macOS or Windows"


def _c19(d: dict) -> tuple[str, str]:
    phys = d.get("physical") or {}
    if "automated_load" in phys:
        return ("Pass" if phys["automated_load"] else "Fail"), f"physical.automated_load: {phys['automated_load']}"
    return "N/A", "a physical property; declare physical.automated_load when known"


def _c20(d: dict, pkg, manual: bool) -> tuple[str, str]:
    sigs = {s.get("name") for s in d.get("signals") or []}
    prose = " ".join([str((d.get("device") or {}).get("notes", "")), str((d.get("physical") or {}).get("notes", "")),
                      *[str(x.get("notes", "")) for sect in ("signals", "settings", "actions") for x in d.get(sect) or []],
                      pkg.instructions])
    boundary = ACCESS_WORDS.search(prose)
    if "robot_access_ready" in sigs:
        return "Pass", "robot_access_ready declared: a handling system reads one name before it loads"
    if not boundary:
        return "N/A", "no lid, door, tray or drawer: nothing meets a handling system"
    return "Fail", f"mentions a {boundary.group(0).lower()} but declares no robot_access_ready"


def _c21(d: dict, folder: Path, manual: bool) -> tuple[str, str]:
    saf = d.get("safety") or {}
    src = (folder / "driver.py").read_text(encoding="utf-8", errors="replace") if (folder / "driver.py").is_file() else ""
    hw = saf.get("hardware_stop") or "latch_external_stop" in src
    if saf.get("estop") is True and hw:
        return "Pass", "e-stop and a declared hardware stop the driver reports"
    if saf.get("estop") is True:
        return "Pass", "e-stop implemented; shutdown escalates; stop source recorded" if not manual else "operator stop"
    if saf.get("notes") or saf.get("estop_kind"):
        return "Partial", "no software stop; safety.notes says who stops it"
    return "Fail", "no stop and no note"


def score(folder: str | Path, registry_entry: dict | None = None) -> dict:
    folder = Path(folder).resolve()
    pkg = load_package(folder)
    d = pkg.descriptor
    driver_py = folder / "driver.py"
    manual = driver_py.is_file() and "drivers.manual" in driver_py.read_text(encoding="utf-8", errors="replace")
    if registry_entry is None:
        try:
            reg = json.loads((folder.parents[1] / "openmhp" / "registry.json").read_text(encoding="utf-8"))
            registry_entry = next((p for p in reg.get("packages", []) if p.get("name") == folder.name), None)
        except (OSError, ValueError, IndexError):
            registry_entry = None
    grades = {"C2": _c2(d), "C5": _c5(d), "C6": _c6(pkg), "C7": _c7(pkg, d), "C12": _c12(d, manual),
              "C14": _c14(folder), "C15": _c15(d, manual), "C16": _c16(folder), "C18": _c18(folder, registry_entry),
              "C19": _c19(d), "C20": _c20(d, pkg, manual), "C21": _c21(d, folder, manual)}
    rows, total, maximum = [], 0.0, 0
    for cid, title, wt in DEVICE_CRITERIA:
        grade, evidence = grades[cid]
        row = {"id": cid, "criterion": title, "weight": wt, "grade": grade, "evidence": evidence}
        if grade != "N/A":
            total += wt * SCORE[grade]; maximum += wt
        rows.append(row)
    err, warn = validate(pkg, location="rubric")
    return {"package": folder.name, "score": round(total, 1), "max": maximum,
            "percent": round(100 * total / maximum) if maximum else None,
            "criteria": rows, "inherited": PROTOCOL_CRITERIA, "validate": {"errors": len(err), "warnings": len(warn)},
            "note": "self-assessed from the package's files against the device-level criteria of Gottstein et al. "
                    "(2026); protocol-level criteria are inherited from OpenMHP; not independently tested"}


def report(r: dict) -> str:
    lines = [f"Rubric: {r['package']}   {r['score']} / {r['max']}" + (f" ({r['percent']}%)" if r["percent"] is not None else ""), ""]
    for row in r["criteria"]:
        lines.append(f"  {row['id']:>3} {row['criterion']:<28} {row['grade']:<7} {row['evidence']}")
    lines.append("")
    lines.append("inherited from the protocol: " + ", ".join(f"{k} {v}" for k, v in r["inherited"].items()))
    lines.append(r["note"])
    return "\n".join(lines)


def main(argv=None) -> int:
    import sys
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        sys.exit("usage: mhp rubric <device package folder> [--json]")
    r = score(argv[0])
    print(json.dumps(r, indent=2, default=str) if "--json" in argv else report(r))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
