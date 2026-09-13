"""Install the bundled Agent Skills into the harnesses found on this machine.

    mhp skills install            -> every harness skills dir that exists (or Claude Code's, created)
    mhp skills install ~/.codex/skills /some/other/dir
    mhp skills list
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).parent / "skills"
HARNESS_DIRS = {                      # harness -> where it looks for skills
    "Claude Code": Path.home() / ".claude" / "skills",
    "Codex": Path.home() / ".codex" / "skills",
    "OpenClaw": Path.home() / ".openclaw" / "skills",
    "Hermes": Path.home() / ".hermes" / "skills",
}


def bundled() -> list[Path]:
    return sorted(p for p in SKILLS_DIR.iterdir() if (p / "SKILL.md").is_file())


def install(dest: Path) -> list[str]:
    dest.mkdir(parents=True, exist_ok=True)
    out = []
    for skill in bundled():
        target = dest / skill.name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(skill, target, ignore=shutil.ignore_patterns("__pycache__"))
        out.append(str(target))
    return out


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] == "list":
        for s in bundled():
            print(s.name)
        return 0
    if argv[0] != "install":
        sys.exit(__doc__)
    dests = [Path(d).expanduser() for d in argv[1:]]
    if not dests:
        dests = [d for d in HARNESS_DIRS.values() if d.parent.exists()] or [HARNESS_DIRS["Claude Code"]]
    for d in dests:
        for path in install(d):
            print("installed", path)
    return 0
