"""Community device packages: a small index, searchable by an agent.

The bundled index lists packages in this repository's packages/ folder. A lab
can point OPENMHP_REGISTRY at its own index URL or file (same JSON shape), and
~/.openmhp/registry.json is merged in if present. Entries are added to a lab with
    mhp_lab op='add' target='github:owner/repo/path'
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from pathlib import Path

BUNDLED = Path(__file__).parent / "registry.json"


def load() -> list[dict]:
    entries: list[dict] = []
    for src in [str(BUNDLED), os.environ.get("OPENMHP_REGISTRY"), str(Path(os.environ.get("OPENMHP_HOME", Path.home() / ".openmhp")) / "registry.json")]:
        if not src:
            continue
        try:
            if src.startswith("http"):
                with urllib.request.urlopen(src, timeout=5) as r:
                    data = json.loads(r.read())
            elif Path(src).is_file():
                data = json.loads(Path(src).read_text())
            else:
                continue
            entries += data.get("packages", [])
        except Exception:                                    # noqa: BLE001  a bad registry must not break the lab
            continue
    seen, out = set(), []
    for e in entries:
        if e.get("target") and e["target"] not in seen:
            seen.add(e["target"]); out.append(e)
    return out


def search(query: str, limit: int = 8) -> list[dict]:
    q = set(re.findall(r"[a-z0-9]+", query.lower()))
    scored = []
    for e in load():
        hay = " ".join(str(e.get(k, "")) for k in ("name", "class", "make", "model", "description", "kind", "tags")).lower()
        s = sum(1 for t in q if t in hay)
        if s or not q:
            scored.append((s, e))
    scored.sort(key=lambda x: (-x[0], x[1].get("name", "")))
    return [e for _, e in scored[:limit]]
