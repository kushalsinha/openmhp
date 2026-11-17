"""`mhp guide`: the user guide, shipped inside the package for machines with no web or git access.

    mhp guide                      the topics, one line each
    mhp guide <topic>              one topic in full (a unique prefix is enough: `mhp guide gate`)
    mhp guide search <words>       every line that mentions all the words, as topic:line
    mhp guide path                 the folder holding the Markdown files

The pages are the website's (openmhp.com), converted by scripts/build_guide.py, plus troubleshooting.md and the
specification (spec.md).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

GUIDE = Path(__file__).resolve().parent / "guide"
ORDER = ["troubleshooting", "quickstart", "introduction", "gateway", "lab-nodes", "experiment-flow", "add-a-device",
         "cookbook", "recipes", "adapters", "architecture", "features", "design", "roadmap", "spec"]


def topics() -> list[str]:
    have = {p.stem for p in GUIDE.glob("*.md")}
    return [t for t in ORDER if t in have] + sorted(have - set(ORDER))


def _lines(topic: str) -> list[str]:
    return (GUIDE / f"{topic}.md").read_text(encoding="utf-8").splitlines()


def summary(topic: str) -> str:
    """The title and the first sentence under it."""
    title, first = topic, ""
    for line in _lines(topic):
        if line.startswith("# ") and title == topic:
            title = line[2:].strip().rstrip(".")
        elif title != topic and line.strip() and not line.startswith(("<!--", "#", "[Figure", "```", "|", ">")):
            first = re.split(r"(?<=\.)\s", line.strip(), maxsplit=1)[0][:160]
            break
    return f"{title}: {first}" if first else title


def resolve(name: str) -> str | None:
    ts = topics()
    if name in ts:
        return name
    hits = [t for t in ts if t.startswith(name)] or [t for t in ts if name in t]
    return hits[0] if len(hits) == 1 else None


def search(words: list[str], limit: int = 60) -> list[str]:
    ws = [w.lower() for w in words]
    out = []
    for t in topics():
        for i, line in enumerate(_lines(t), 1):
            low = line.lower()
            if all(w in low for w in ws):
                out.append(f"{t}:{i}: {line.strip()[:200]}")
    return out[:limit] + ([f"... {len(out) - limit} more; narrow the words"] if len(out) > limit else [])


def main(args: list[str]) -> int:
    from . import __version__
    if not GUIDE.is_dir():
        print("this install has no guide folder; reinstall with: pip install -U openmhp", file=sys.stderr)
        return 1
    if not args:
        print(f"OpenMHP {__version__} user guide ({GUIDE})", "", sep="\n")
        for t in topics():
            print(f"  {t:17s} {summary(t)}")
        print("", "mhp guide <topic>   |   mhp guide search <words>   |   mhp guide path", sep="\n")
        return 0
    if args[0] == "path":
        print(GUIDE)
        return 0
    if args[0] == "search":
        if len(args) < 2:
            print("usage: mhp guide search <words>", file=sys.stderr)
            return 2
        hits = search(args[1:])
        print("\n".join(hits) if hits else f"nothing in the guide mentions {' '.join(args[1:])!r}")
        return 0 if hits else 1
    t = resolve(args[0])
    if t is None:
        print(f"no guide topic {args[0]!r}. Topics: {', '.join(topics())}", file=sys.stderr)
        return 2
    print((GUIDE / f"{t}.md").read_text(encoding="utf-8"))
    return 0
