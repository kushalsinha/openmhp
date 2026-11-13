"""A run's charter: what a scientist approved for one run on the gateway, and what the gateway enforces.

The charter names the instruments a run may use and, for each, what it may do without asking: which
actions and settings, with what parameter ranges. It also sets budgets (experiments, deadline),
consumables with limits, standing approvals for confirm-gated actions, and actions that always go back
to the scientist. Everything the run does with its run token is checked against it at the gateway,
before any lab PC sees the request (see charter_gate). English fields (objective, stop conditions,
cleanup) guide the run's agent; the structured fields are what code enforces.

    {
      "version": 1, "run": "R-2611-0042", "owner": "alice",
      "objective": "Best capacity retention after 50 cycles over salt and additive",
      "autonomy": "act",                                   # suggest | act | campaigns
      "instruments": {"lh": "bench/ot2-01", "cycler": "cells/neware-01"},
      "envelope": {
        "lh": {"actions": {"dispense": {"volume_ul": {"min": 1, "max": 200}}},
               "settings": {"speed": {"min": 10, "max": 80}}},
        "cycler": {"actions": {"start_protocol": {}}, "settings": {}}
      },
      "consumables": {"lipf6_ml": {"limit": 40, "uses": [{"instrument": "lh", "action": "dispense",
                                                          "param": "volume_ul", "scale": 0.001}]}},
      "budgets": {"experiments": 24, "count": {"instrument": "cycler", "action": "start_protocol"},
                  "deadline": "2026-11-20T18:00:00"},
      "standing_approvals": [{"instrument": "lh", "action": "open_door", "until": "2026-11-20T18:00:00", "uses": 30}],
      "always_ask": [{"instrument": "cycler", "action": "clear_channel"}],
      "stop_conditions": ["retention above 95 %", "two failed cells in a row"],
      "cleanup": "cycler channels to rest; liquid handler homed; report which cells are unassembled",
      "reporting": {"every_hours": 6}
    }

An action or setting the envelope does not list is outside it. A parameter the envelope does not
bound is free (the device's own limits still apply). `{}` for an action means "allowed, any params".
"""
from __future__ import annotations

import hashlib
import json
import time

VERSION = 1
AUTONOMY = ("suggest", "act", "campaigns")
REQUIRED = ("run", "owner", "objective", "instruments", "envelope")


def canonical(charter: dict) -> bytes:
    """The bytes a digest is taken over: sorted keys, no whitespace, approval records left out."""
    body = {k: v for k, v in charter.items() if k not in ("approved_by", "approved_at", "digest")}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def digest(charter: dict) -> str:
    return "sha256:" + hashlib.sha256(canonical(charter)).hexdigest()


def _when(s: str) -> float:
    return time.mktime(time.strptime(s, "%Y-%m-%dT%H:%M:%S"))


def _range_problems(where: str, spec) -> list[str]:
    if not isinstance(spec, dict):
        return [f"{where}: expected {{'min': .., 'max': ..}} or {{'in': [...]}}"]
    out = []
    for k in spec:
        if k not in ("min", "max", "in"):
            out.append(f"{where}: unknown bound {k!r} (min, max or in)")
    if "min" in spec and "max" in spec and isinstance(spec["min"], (int, float)) and isinstance(spec["max"], (int, float)) \
            and spec["min"] > spec["max"]:
        out.append(f"{where}: min is above max")
    if "in" in spec and not isinstance(spec["in"], list):
        out.append(f"{where}: 'in' must be a list")
    return out


def problems(charter: dict) -> list[str]:
    """Everything wrong with a charter, in words; empty when it can be approved and enforced."""
    out = []
    if not isinstance(charter, dict):
        return ["a charter is a JSON object"]
    for k in REQUIRED:
        if k not in charter:
            out.append(f"missing {k!r}")
    if charter.get("version", VERSION) != VERSION:
        out.append(f"version {charter.get('version')!r} is not {VERSION}")
    if charter.get("autonomy", "act") not in AUTONOMY:
        out.append(f"autonomy must be one of {', '.join(AUTONOMY)}")
    inst = charter.get("instruments") or {}
    if not isinstance(inst, dict) or not inst:
        out.append("instruments: name at least one, as {alias: 'node/device'}")
        inst = {}
    for alias, dev in inst.items():
        if not isinstance(dev, str) or dev.count("/") != 1:
            out.append(f"instruments.{alias}: expected 'node/device', got {dev!r}")
    env = charter.get("envelope") or {}
    for alias, e in env.items():
        if alias not in inst:
            out.append(f"envelope.{alias}: not one of the run's instruments")
            continue
        for kind in ("actions", "settings"):
            for name, spec in (e.get(kind) or {}).items():
                if kind == "actions":
                    if not isinstance(spec, dict):
                        out.append(f"envelope.{alias}.actions.{name}: expected {{param: bounds}}")
                        continue
                    for param, b in spec.items():
                        out += _range_problems(f"envelope.{alias}.actions.{name}.{param}", b)
                else:
                    out += _range_problems(f"envelope.{alias}.settings.{name}", spec)
    for cname, c in (charter.get("consumables") or {}).items():
        if not isinstance(c.get("limit"), (int, float)):
            out.append(f"consumables.{cname}: needs a numeric limit")
        for u in c.get("uses") or []:
            if u.get("instrument") not in inst:
                out.append(f"consumables.{cname}: uses an instrument the run does not have ({u.get('instrument')!r})")
    b = charter.get("budgets") or {}
    if "experiments" in b and not (isinstance(b["experiments"], int) and b["experiments"] >= 0):
        out.append("budgets.experiments: a whole number")
    if "experiments" in b and not b.get("count"):
        out.append("budgets.count: say which action counts as one experiment")
    if b.get("deadline"):
        try:
            _when(b["deadline"])
        except (ValueError, TypeError):
            out.append("budgets.deadline: use YYYY-MM-DDTHH:MM:SS")
    for i, a in enumerate(charter.get("standing_approvals") or []):
        if a.get("instrument") not in inst or not a.get("action"):
            out.append(f"standing_approvals[{i}]: needs one of the run's instruments and an action")
        if a.get("until"):
            try:
                _when(a["until"])
            except (ValueError, TypeError):
                out.append(f"standing_approvals[{i}].until: use YYYY-MM-DDTHH:MM:SS")
    for i, a in enumerate(charter.get("always_ask") or []):
        if a.get("instrument") not in inst:
            out.append(f"always_ask[{i}]: not one of the run's instruments")
    return out


def _bounds_text(spec: dict) -> str:
    if not spec:
        return "any"
    if "in" in spec:
        return "one of " + ", ".join(map(str, spec["in"]))
    lo, hi = spec.get("min"), spec.get("max")
    return f"{lo} to {hi}" if lo is not None and hi is not None else (f"at least {lo}" if lo is not None else f"at most {hi}")


def summary(charter: dict) -> str:
    """The English the scientist reads before approving. Generated from the structured charter, so what
    they approve is what the gateway enforces."""
    inst = charter.get("instruments", {})
    lines = [f"# Charter for {charter.get('run', '?')} ({charter.get('owner', '?')})", "",
             charter.get("objective", ""), "",
             f"Autonomy: {charter.get('autonomy', 'act')}. Instruments: " + ", ".join(f"{a} ({d})" for a, d in inst.items()) + ".", ""]
    lines.append("## What the run may do without asking")
    for alias, e in (charter.get("envelope") or {}).items():
        for name, spec in (e.get("actions") or {}).items():
            bounds = "; ".join(f"{p} {_bounds_text(b)}" for p, b in spec.items()) or "any parameters"
            lines.append(f"- {alias}: run {name} ({bounds})")
        for name, spec in (e.get("settings") or {}).items():
            lines.append(f"- {alias}: set {name} to {_bounds_text(spec)}")
    lines.append("- any instrument: read signals, check jobs, e-stop")
    lines += ["", "## Limits"]
    b = charter.get("budgets") or {}
    if "experiments" in b:
        c = b.get("count") or {}
        lines.append(f"- at most {b['experiments']} experiments (each {c.get('instrument')} {c.get('action')})")
    if b.get("deadline"):
        lines.append(f"- finished by {b['deadline']}")
    for cname, c in (charter.get("consumables") or {}).items():
        lines.append(f"- {cname}: at most {c['limit']}")
    if charter.get("standing_approvals"):
        lines += ["", "## Approved in advance"]
        for a in charter["standing_approvals"]:
            extra = (f", until {a['until']}" if a.get("until") else "") + (f", at most {a['uses']} times" if a.get("uses") else "")
            lines.append(f"- {a['instrument']}: {a['action']}{extra}")
    if charter.get("always_ask"):
        lines += ["", "## Always asks you first"]
        lines += [f"- {a['instrument']}: {a.get('action', 'any action')}" for a in charter["always_ask"]]
    if charter.get("stop_conditions"):
        lines += ["", "## Stops when"] + [f"- {s}" for s in charter["stop_conditions"]]
    if charter.get("cleanup"):
        lines += ["", "## Cleanup", charter["cleanup"]]
    lines += ["", f"Digest: {digest(charter)}", ""]
    return "\n".join(lines)
