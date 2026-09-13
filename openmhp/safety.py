"""The safety card: a readable review of a device before first use.

It reports what was actually checked and what was not. A limit counts as verified
only when a probe was refused with the limit error itself; any other refusal
(forbidden, fault, lease) means the limit was not exercised. Emergency stop and
watchdog behaviour are described from the configuration but not exercised. The
card is evidence for the owner's review, not a safety certification.
"""
from __future__ import annotations

from .client import Device, RemoteError
from .driver import InvalidValue, LimitViolation
from .package import load_package
from .validate import validate


def _probe_write(dev: Device, spec: dict, value, expect: int, check: str, findings: list) -> dict:
    probe = {"kind": "write", "name": spec["name"], "value": value, "check": check}
    try:
        dev.call("settings/write", {"name": spec["name"], "value": value, "dryRun": True})
        probe.update(status="failed", result="ACCEPTED (should have been refused)")
        findings.append({"level": "error", "text": f"{spec['name']}: {check} value {value!r} was not refused"})
    except RemoteError as e:
        if e.code == expect:
            probe.update(status="passed", result=f"refused as expected: {e.message}")
        else:
            probe.update(status="not exercised", result=f"not exercised: {e.message}")
            findings.append({"level": "warn", "text": f"{spec['name']}: {check} check not exercised ({e.message})"})
    return probe


def safety_card(dev: Device, package_path: str | None = None, location: str | None = None) -> dict:
    full = dev.describe("full")
    d = full["device"]
    settings, actions, safety = full.get("settings", []), full.get("actions", []), full.get("safety", {})
    findings, probes, checks = [], [], []

    if package_path:
        err, warn = validate(load_package(package_path), location=location)
        findings += [{"level": "error", "text": e} for e in err] + [{"level": "warn", "text": w} for w in warn]
        checks.append("package validator")

    for s in settings:
        lim = s.get("limits") or {}
        if s.get("type", "number") not in ("number", "integer"):
            continue
        if "max" not in lim and "min" not in lim:
            findings.append({"level": "error", "text": f"{s['name']}: numeric setting without limits"})
            continue
        if "max" in lim:
            probes.append(_probe_write(dev, s, lim["max"] + 1, LimitViolation.code, "above-max", findings))
        if "min" in lim:
            probes.append(_probe_write(dev, s, lim["min"] - 1, LimitViolation.code, "below-min", findings))
        probes.append(_probe_write(dev, s, "not a number", InvalidValue.code, "wrong-type", findings))
    if settings:
        checks.append("setting probes (dry run)")

    for a in actions:
        probe = {"kind": "invoke", "name": a["name"], "approval": a.get("approval", "auto"), "interlocks": a.get("interlocks", [])}
        try:
            r = dev.call("actions/invoke", {"name": a["name"], "params": _example(a), "dryRun": True})
            text = "passes the gates"
            if r.get("needsApproval"):
                text += " once a person confirms"
            elif not a.get("interlocks"):
                text += " (no interlock, no confirmation)"
            probe.update(status="passed", result=text)
        except RemoteError as e:
            probe.update(status="refused", result=f"gate: {e.message}")
        probes.append(probe)
    if actions:
        checks.append("action gate dry runs")

    estop, estop_kind = safety.get("estop", False), safety.get("estop_kind")
    wd = safety.get("watchdog_s")
    in_process = hasattr(dev, "driver")
    if not estop:
        findings.append({"level": "warn", "text": "no automatic emergency stop" +
                         (": stopping is a request to the operator" if estop_kind == "operator" else "; the agent cannot stop this device")})
    if not wd:
        findings.append({"level": "warn", "text": "no watchdog; the device will not stop if its controller goes silent"})

    where = str(location or "").strip() or str(d.get("location") or "").strip()
    lines = [f"SAFETY CARD: {d.get('id')} ({d.get('make', '')} {d.get('model', '')}"
             + (f", {where}" if where else "") + ")", ""]
    lines.append("Limits the driver enforces (values are also type-checked):")
    for s in settings:
        lim = s.get("limits") or {}
        lines.append(f"  - {s['name']}: {lim.get('min', '-')} to {lim.get('max', '-')} {s.get('unit', '')}".rstrip() +
                     (", needs a person's confirmation" if s.get("approval") == "confirm" else "") +
                     (f"  ({s['notes']})" if s.get("notes") else ""))
    lines.append("Actions and their gates:")
    for a in actions:
        g = []
        if a.get("interlocks"): g.append("requires " + ", ".join(a["interlocks"]))
        if a.get("approval") == "confirm": g.append("a person must confirm each time")
        if a.get("approval") == "forbid": g.append("never agent-operated")
        if a.get("limits"): g.append("parameter limits " + ", ".join(sorted(a["limits"])))
        lines.append(f"  - {a['name']}: {'; '.join(g) or 'no gate'}")
    if estop:
        lines.append(f"Emergency stop: declared ({safety.get('notes', '')}); not exercised by this card")
    else:
        lines.append("Emergency stop: " + ("operator-performed, not automatic" if estop_kind == "operator" else "NONE"))
    if wd:
        lines.append(f"Watchdog: {wd} s while a client holds a lease; enforced by the driver runtime, not exercised by this card" +
                     ("; this driver runs inside the host process, so host power loss is not covered" if in_process else ""))
    else:
        lines.append("Watchdog: none")
    if findings:
        lines.append("Findings:")
        lines += [f"  [{f['level']}] {f['text']}" for f in findings]
    lines.append("Probes (dry runs; nothing was actuated):")
    lines += [f"  - {p['kind']} {p['name']}" + (f" {p['check']}" if p.get("check") else "") + f": {p['result']}" for p in probes]
    ok = not any(f["level"] == "error" for f in findings)
    limit_probes = [p for p in probes if p["kind"] == "write"]
    passed = sum(p["status"] == "passed" for p in limit_probes)
    skipped = sum(p["status"] == "not exercised" for p in limit_probes)
    lines.append("")
    if ok:
        lines.append(f"RESULT: no configuration errors found. Checks performed: {', '.join(checks) or 'none'}. "
                     f"Setting probes refused as expected: {passed} of {len(limit_probes)}" + (f"; not exercised: {skipped}" if skipped else "") + ". "
                     "Not checked: emergency-stop behaviour, watchdog expiry, physical behaviour. "
                     "The owner must review this card; it is not a safety certification.")
    else:
        lines.append("RESULT: configuration errors found; fix them before use.")
    return {"ok": ok, "text": "\n".join(lines), "findings": findings, "probes": probes, "checks": checks}


def _example(a: dict) -> dict:
    ex = a.get("examples") or []
    if ex and isinstance(ex[0], dict):
        return ex[0]
    return {k: 0 for k in (a.get("params") or {})} if isinstance(a.get("params"), dict) else {}
