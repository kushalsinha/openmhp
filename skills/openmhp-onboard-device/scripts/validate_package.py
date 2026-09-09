#!/usr/bin/env python3
"""Validate an MHP device package folder (DEVICE.md + descriptor.yaml [+ driver.py]).

    python validate_package.py devices/thermocycler-01
Exit 1 on errors; warnings do not fail.
"""
import re
import sys

from openmhp.package import load_package

TYPES = {"number", "integer", "boolean", "string", "object", "array"}
APPROVAL = {"auto", "confirm", "forbid"}


def validate(pkg):
    p, m, d = [], pkg.meta, pkg.descriptor
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", str(m.get("id", ""))):
        p.append("frontmatter id missing or not lowercase-hyphenated")
    if not m.get("class"):
        p.append("frontmatter class missing")
    desc = str(m.get("description", ""))
    if not desc:
        p.append("frontmatter description missing")
    elif len(desc) > 1024:
        p.append(f"description is {len(desc)} chars (max 1024)")
    elif len(desc) < 60:
        p.append("WARNING description is very short; say what it is and when to pick it")
    for k in ("location", "tags"):
        if not m.get(k):
            p.append(f"frontmatter {k} missing (directory filters on it)")
    body = pkg.instructions
    if len(body) < 200:
        p.append("WARNING DEVICE.md body is short; agents rely on it once they pick the device")
    if "## Operating procedure" not in body:
        p.append("WARNING DEVICE.md has no '## Operating procedure' section")
    for rel in re.findall(r"`((?:references|scripts)/[^`]+)`", body):
        if rel not in pkg.resources:
            p.append(f"DEVICE.md mentions {rel} but the file is missing")
    sigs = {s.get("name") for s in d.get("signals", [])}
    for sect in ("signals", "settings", "actions"):
        names = [x.get("name") for x in d.get(sect, [])]
        if len(names) != len(set(names)):
            p.append(f"{sect}: duplicate names")
    for s in d.get("signals", []) + d.get("settings", []):
        if s.get("type", "number") not in TYPES:
            p.append(f"{s.get('name')}: bad type {s.get('type')}")
    for s in d.get("settings", []):
        if s.get("type", "number") in ("number", "integer") and "limits" not in s:
            p.append(f"settings.{s.get('name')}: numeric setting without limits")
        if s.get("approval", "auto") not in APPROVAL:
            p.append(f"settings.{s.get('name')}: bad approval")
    for a in d.get("actions", []):
        if a.get("approval", "auto") not in APPROVAL:
            p.append(f"actions.{a.get('name')}: bad approval")
        if a.get("duration", "short") not in ("short", "long"):
            p.append(f"actions.{a.get('name')}: duration must be short|long")
        for i in a.get("interlocks", []):
            if i not in sigs:
                p.append(f"actions.{a.get('name')}: interlock '{i}' is not a signal")
        if a.get("approval", "auto") == "auto" and not a.get("interlocks"):
            p.append(f"WARNING actions.{a.get('name')}: auto action with no interlocks; confirm this is safe")
        if a.get("params") and not a.get("examples"):
            p.append(f"WARNING actions.{a.get('name')}: has params but no examples")
    saf = d.get("safety") or {}
    if "estop" not in saf:
        p.append("safety.estop missing (true/false)")
    if "watchdog_s" not in saf:
        p.append("safety.watchdog_s missing")
    if "driver.py" not in pkg.resources:
        p.append("WARNING no driver.py in the package")
    return p


if __name__ == "__main__":
    problems = validate(load_package(sys.argv[1]))
    hard = [x for x in problems if not x.startswith("WARNING")]
    for x in problems:
        print(("warn  " + x[8:]) if x.startswith("WARNING") else ("error " + x))
    print("OK" if not hard else f"{len(hard)} error(s)")
    sys.exit(1 if hard else 0)
