"""Recipes: tested cross-instrument procedures an agent can find and adapt.

Each recipe is a Python file for mhp_run with a header block:

    # recipe: pcr-with-plate-transfer
    # needs: robot_arm, thermocycler
    # asks: which deck slot holds the plate; the cycling program
    # summary: Move a plate from the deck to the thermocycler, run a program, hold at 4 C, return it.
    PARAMS = {"plate_slot": "deck_A1", "steps": [...], "cycles": 30}   # overridable

The agent searches with mhp_lab op='recipes' and runs one with mhp_run recipe=<name> params={...}.
Recipes are ordinary scripts: they see `lab`, `run_dir`, and `PARAMS`.
"""
from __future__ import annotations

import re
from pathlib import Path

HERE = Path(__file__).parent


def load_all(extra_dirs: list[Path] | None = None) -> list[dict]:
    out = []
    for d in [HERE, *(extra_dirs or [])]:
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.py")):
            if p.name.startswith("_"):
                continue
            text = p.read_text()
            meta = dict(re.findall(r"^#\s*(recipe|needs|asks|summary):\s*(.+)$", text, re.M))
            if "recipe" not in meta:
                continue
            m = re.search(r"^PARAMS\s*=\s*(\{.*?\})\s*$", text, re.M | re.S)
            out.append({"name": meta["recipe"], "needs": [c.strip() for c in meta.get("needs", "").split(",") if c.strip()],
                        "asks": meta.get("asks", ""), "summary": meta.get("summary", ""), "params": m.group(1).strip() if m else "{}",
                        "path": str(p), "source": text})
    return out


def search(query: str, recipes: list[dict] | None = None, limit: int = 5) -> list[dict]:
    recipes = recipes if recipes is not None else load_all()
    q = set(re.findall(r"[a-z0-9]+", query.lower()))
    scored = []
    for r in recipes:
        hay = " ".join([r["name"], " ".join(r["needs"]), r["asks"], r["summary"]]).lower().replace("-", " ").replace("_", " ")
        s = sum(1 for t in q if t in hay)
        if s or not q:
            scored.append((s, r))
    scored.sort(key=lambda x: (-x[0], x[1]["name"]))
    return [{k: v for k, v in r.items() if k != "source"} for _, r in scored[:limit]]


def get(name: str, recipes: list[dict] | None = None) -> dict | None:
    for r in (recipes if recipes is not None else load_all()):
        if r["name"] == name:
            return r
    return None


def with_params(source: str, params: dict | None = None) -> str:
    """Make a recipe take caller overrides as data. The run supplies them in `__mhp_params__`; they are merged
    into PARAMS right after its definition. Values are never turned into source code."""
    line = "\n# --- parameter overrides from the caller (data, not code) ---\nPARAMS.update(__mhp_params__)\n"
    m = re.search(r"^PARAMS\s*=\s*\{.*?\}\s*$", source, re.M | re.S)
    if not m:
        return "PARAMS = {}" + line + source
    return source[:m.end()] + line + source[m.end():]
