"""Behavioural conformance: score a device against the levels in SPEC 15.

    mhp conformance pkg:openmhp/devices/thermocycler-01
    mhp conformance http://bench-pc:18921 --json

Conformance in MHP is behavioural, so this exercises the device rather than reading its
descriptor and believing it. Every probe is non-destructive: writes and invocations go
through `dryRun`, which runs the same gates without touching the instrument, and nothing
here e-stops a device or starts real work. That means it is safe to run against hardware,
which is the only way the result means anything.

The report is tied to the protocol version the device reports, because a level a device met
under one version is not evidence about another.
"""
from __future__ import annotations

import time
from typing import Any

from .client import RemoteError


def _probe(fn, *a, **kw) -> tuple[bool, str]:
    try:
        return True, _short(fn(*a, **kw))
    except RemoteError as e:
        return False, f"{e.code}: {e}"
    except Exception as e:                         # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def _short(v: Any, n: int = 60) -> str:
    s = str(v).replace("\n", " ")
    return s if len(s) <= n else s[:n] + "..."


def _expect_refusal(fn, code: int, *a, **kw) -> tuple[bool, str]:
    """A gate is proved by what it refuses, not by what it allows."""
    try:
        fn(*a, **kw)
        return False, f"accepted; expected refusal {code}"
    except RemoteError as e:
        return (e.code == code), f"{e.code} ({'as expected' if e.code == code else f'expected {code}'})"
    except Exception as e:                         # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def run(dev) -> dict:
    """Return {level: {ok, checks: [(name, ok, detail)]}} for one connected device."""
    d = dev.call("device/describe", {"detail": "full"})   # limits, safety and the protocol version
    desc = d.get("device", {})
    signals = [s["name"] for s in d.get("signals", []) or []]
    settings = d.get("settings", []) or []
    actions = d.get("actions", []) or []
    levels: dict[str, list] = {"Core": [], "Actions": [], "Safe": []}

    def add(level, name, ok, detail=""):
        levels[level].append({"check": name, "ok": bool(ok), "detail": detail})

    # ---- Core -----------------------------------------------------------
    add("Core", "device/describe card", *_probe(dev.call, "device/describe", {"detail": "card"}))
    add("Core", "device/describe summary", *_probe(dev.call, "device/describe", {"detail": "summary"}))
    add("Core", "device/describe full", *_probe(dev.call, "device/describe", {"detail": "full"}))
    if actions:
        add("Core", "device/describe select",
            *_probe(dev.call, "device/describe", {"select": {"actions": [actions[0]["name"]]}}))
    add("Core", "reports a protocol version", bool(d.get("mhp")), str(d.get("mhp")))
    add("Core", "resources/list", *_probe(dev.call, "resources/list", {}))
    if signals:
        add("Core", "signals/read", *_probe(dev.read, signals[0]))
    else:
        add("Core", "signals/read", False, "the device declares no signals")
    bounded = next((s for s in settings
                    if isinstance(s.get("limits"), dict) and "max" in (s.get("limits") or {})), None)
    if bounded:
        over = bounded["limits"]["max"] + 1
        add("Core", "a bounded setting refuses an out-of-range write",
            *_expect_refusal(dev.write, -32010, bounded["name"], over, dry_run=True))
    else:
        add("Core", "a bounded setting refuses an out-of-range write", False,
            "no setting declares a max to test against")
    add("Core", "unknown names are refused",
        *_expect_refusal(dev.read, -32040, "almost_certainly_not_a_signal"))

    # ---- Actions --------------------------------------------------------
    if actions:
        # a method-driven action refusing with MethodRequired is the gate working, not a
        # failure, so prefer a plain action and treat that refusal as a pass if there is none
        a0 = next((a for a in actions if a.get("methods") is not True), actions[0])
        ok, detail = _probe(dev.invoke, a0["name"], dry_run=True)
        if not ok and detail.startswith("-32015"):
            ok, detail = True, "refused with MethodRequired, which is the method gate working"
        add("Actions", f"actions/invoke accepts a dry run ({a0['name']})", ok, detail)
        add("Actions", "an unknown job is refused",
            *_expect_refusal(dev.call, -32041, "jobs/status", {"id": "job_definitely_missing"}))
        gated = [a for a in actions if a.get("approval") == "confirm"]
        if gated:
            add("Actions", "a confirm-gated action refuses without approval",
                *_expect_refusal(dev.invoke, -32012, gated[0]["name"]))
        else:
            add("Actions", "a confirm-gated action refuses without approval", True,
                "no action declares approval: confirm")
        add("Actions", "methods/* answers even when nothing is method-driven",
            *_probe(dev.call, "methods/list", {}))
    else:
        add("Actions", "declares at least one action", False, "no actions declared")

    # ---- Safe -----------------------------------------------------------
    safety = d.get("safety", {}) or {}
    add("Safe", "declares an emergency stop", safety.get("estop") is True or safety.get("estop_kind"),
        str(safety.get("estop") or safety.get("estop_kind")))
    add("Safe", "declares a watchdog window", bool(safety.get("watchdog_s")), str(safety.get("watchdog_s")))
    ok, detail = _probe(dev.acquire, 30)
    add("Safe", "session/acquire grants a lease", ok, detail)
    if ok:
        add("Safe", "session/renew keeps it", *_probe(dev.call, "session/renew", {"ttl": 30}))
        add("Safe", "session/release returns it", *_probe(dev.call, "session/release", {}))
    add("Safe", "errors carry a timing reference and a recovery class",
        *_recovery_fields(dev))

    out = {}
    for level, checks in levels.items():
        out[level] = {"ok": all(c["ok"] for c in checks) and bool(checks), "checks": checks}
    out["_device"] = {"id": desc.get("id"), "class": desc.get("class"), "mhp": d.get("mhp"),
                      "checked": time.strftime("%Y-%m-%dT%H:%M:%S")}
    return out


def _recovery_fields(dev) -> tuple[bool, str]:
    """C16/C3: a refusal must be machine-readable, not prose to be parsed."""
    try:
        dev.read("almost_certainly_not_a_signal")
        return False, "expected a refusal to inspect"
    except RemoteError as e:
        missing = [f for f in ("ts", "recovery", "transient", "effect") if getattr(e, f, None) is None]
        return (not missing), ("all present" if not missing else f"missing {missing}")
    except Exception as e:                         # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def report(result: dict) -> str:
    dev = result.get("_device", {})
    lines = [f"MHP conformance: {dev.get('id')} ({dev.get('class')})",
             f"protocol {dev.get('mhp')}   checked {dev.get('checked')}", ""]
    for level in ("Core", "Actions", "Safe"):
        r = result.get(level)
        if not r:
            continue
        lines.append(f"MHP {level}: {'PASS' if r['ok'] else 'FAIL'}")
        for c in r["checks"]:
            lines.append(f"  [{'x' if c['ok'] else ' '}] {c['check']}" + (f"  -- {c['detail']}" if c["detail"] else ""))
        lines.append("")
    passed = [lv for lv in ("Core", "Actions", "Safe") if result.get(lv, {}).get("ok")]
    lines.append("Levels met: " + (", ".join(f"MHP {p}" for p in passed) if passed else "none"))
    lines.append("Behavioural result for this device at this protocol version; it is not a "
                 "statement about any other version or build.")
    return "\n".join(lines)
