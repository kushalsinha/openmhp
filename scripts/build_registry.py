#!/usr/bin/env python3
"""Refresh openmhp/registry.json from the packages in supported-devices/.

    python scripts/build_registry.py            # rewrite the rubric scores and check every entry
    python scripts/build_registry.py --check    # exit 1 if anything is stale or inconsistent, write nothing

Hand-written fields stay hand-written (description, tags, category, os, kind). This script fills
`class`, `make`, `model` and `sim` from each package's DEVICE.md, scores the package with
`openmhp.rubric` and writes the result under `rubric`, so the registry an agent searches and the
website table both carry the same self-assessed score. It refuses to write when a package has no
entry or an entry has no package.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from openmhp.package import load_package      # noqa: E402
from openmhp.rubric import score              # noqa: E402

REG = REPO / "openmhp" / "registry.json"
DEVICES = REPO / "supported-devices"
README = DEVICES / "README.md"


def main(argv: list[str]) -> int:
    check = "--check" in argv
    reg = json.loads(REG.read_text(encoding="utf-8"))
    entries = {e["name"]: e for e in reg.get("packages", [])}
    folders = {p.name: p for p in sorted(DEVICES.iterdir()) if p.is_dir() and (p / "DEVICE.md").is_file()}
    problems = [f"no registry entry for supported-devices/{n}" for n in folders if n not in entries]
    problems += [f"registry entry {n!r} has no package folder" for n in entries if n not in folders]
    changed = []
    for name, folder in folders.items():
        e = entries.get(name)
        if e is None:
            continue
        pkg = load_package(folder)
        meta = pkg.meta
        want = {"class": meta.get("class"), "make": meta.get("make"), "model": meta.get("model"),
                "sim": (folder / "sim.py").is_file()}
        for k, v in want.items():
            if e.get(k) != v:
                changed.append(f"{name}.{k}: {e.get(k)!r} -> {v!r}")
                e[k] = v
        if not e.get("category"):
            problems.append(f"{name}: no category (chemistry | biology | physics | engineering | pharma-small-molecule | pharma-biologics)")
        r = score(folder, registry_entry=e)
        rub = {"score": r["score"], "max": r["max"], "percent": r["percent"],
               "criteria": {c["id"]: c["grade"] for c in r["criteria"]}}
        if e.get("rubric") != rub:
            changed.append(f"{name}.rubric: {e.get('rubric', {}).get('score') if e.get('rubric') else None} -> {rub['score']}/{rub['max']}")
            e["rubric"] = rub
    for name, e in entries.items():
        for k in ("via", "status", "description", "tags"):
            if not e.get(k):
                problems.append(f"{name}: registry entry needs `{k}`")
        if e.get("status") not in (None, "hardware tested", "twin tested", "template"):
            problems.append(f"{name}: status must be hardware tested | twin tested | template")
    table = render_table(entries)
    readme = README.read_text(encoding="utf-8")
    new_readme = re.sub(r"(<!-- packages:begin[^>]*-->\n).*?(<!-- packages:end -->)", lambda m: m.group(1) + table + m.group(2),
                        readme, flags=re.S)
    if new_readme != readme:
        changed.append("supported-devices/README.md table")
    for line in problems:
        print("problem:", line)
    for line in changed:
        print("update: ", line)
    if problems:
        return 1
    if check:
        return 1 if changed else 0
    if changed:
        reg["packages"] = list(entries.values())
        REG.write_text(json.dumps(reg, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        README.write_text(new_readme, encoding="utf-8")
        print(f"wrote {REG.relative_to(REPO)} ({len(entries)} packages) and the README table")
    else:
        print("registry up to date")
    return 0


CATEGORIES = [("pharma-small-molecule", "Pharma, small molecule"), ("pharma-biologics", "Pharma, biologics"),
              ("chemistry", "Chemistry"), ("biology", "Biology"), ("physics", "Physics and optics"),
              ("materials-synthesis", "Materials, synthesis and processing"),
              ("materials-characterization", "Materials, characterization"), ("energy-storage", "Energy storage"),
              ("engineering", "Engineering and data acquisition")]


def render_table(entries: dict) -> str:
    out = []
    groups: dict[str, list] = {}
    for e in entries.values():
        groups.setdefault(str(e.get("category") or "other"), []).append(e)
    keys = [k for k, _ in CATEGORIES if k in groups] + sorted(k for k in groups if k not in dict(CATEGORIES))
    for key in keys:
        title = dict(CATEGORIES).get(key, key)
        out.append(f"\n**{title}**\n")
        out.append("| Package | Instrument | Talks through | Host | Status | Rubric |")
        out.append("|---|---|---|---|---|---|")
        for e in sorted(groups[key], key=lambda x: x["name"]):
            rub = e.get("rubric") or {}
            score = f"{rub.get('score', '?')} / {rub.get('max', '?')}" if rub else "?"
            host = "Windows" if e.get("os") == "windows" else "any"
            out.append(f"| [`{e['name']}`]({e['name']}) | {e.get('make', '')} {e.get('model', '')} | {e.get('via', '')} "
                       f"| {host} | {e.get('status', '')} | {score} |")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
