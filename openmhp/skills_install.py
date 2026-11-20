"""Install the bundled Agent Skills into the harnesses found on this machine, and keep them current.

    mhp skills install            -> every harness skills dir that exists (or Claude Code's, created)
    mhp skills install ~/.codex/skills /some/other/dir
    mhp skills status             -> which installed copies are current, out of date, or changed by hand
    mhp skills list

Skills ship inside the package, so a new OpenMHP release is also how skills are updated. Each installed copy
carries a small marker (.openmhp-skill.json) recording what was installed. When this package is newer than an
installed copy, `refresh()` replaces it: the MCP server, the background watcher and `mhp agent --join` call it,
so a scientist's agent picks up new skills after an upgrade without anyone remembering `mhp skills install`.
A copy someone changed by hand is never overwritten by a refresh, and a copy newer than this package's (put
there by a newer install) is never downgraded; they are told instead. `mhp skills install` replaces a hand-changed
copy only because a person asked, and backs it up first. Anything replaced is backed up, under
~/.openmhp/skill-backups/.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

SKILLS_DIR = Path(__file__).parent / "skills"
MARK = ".openmhp-skill.json"
HARNESS_DIRS = {                      # harness -> where it looks for skills
    "Claude Code": Path.home() / ".claude" / "skills",
    "Codex": Path.home() / ".codex" / "skills",
    "OpenClaw": Path.home() / ".openclaw" / "skills",
    "Hermes": Path.home() / ".hermes" / "skills",
}


def bundled() -> list[Path]:
    return sorted(p for p in SKILLS_DIR.iterdir() if (p / "SKILL.md").is_file())


def version_of(folder: Path) -> str | None:
    """The `version:` in a skill's SKILL.md front matter."""
    try:
        head = (folder / "SKILL.md").read_text(encoding="utf-8").split("\n---", 1)[0]
    except OSError:
        return None
    m = re.search(r'^\s+version:\s*"?([^"\n]+)"?\s*$', head, re.M)
    return m.group(1).strip() if m else None


def bundled_version(name: str) -> str | None:
    return version_of(SKILLS_DIR / name)


def digest(folder: Path) -> str:
    """The content of a skill folder, ignoring the marker and caches."""
    h = hashlib.sha256()
    for f in sorted(p for p in folder.rglob("*") if p.is_file() and p.name != MARK and "__pycache__" not in p.parts):
        h.update(f.relative_to(folder).as_posix().encode() + b"\0" + f.read_bytes() + b"\0")
    return h.hexdigest()


def _newer(a: str | None, b: str | None) -> bool:
    """Is version a newer than b? Unknown versions compare as oldest."""
    def key(v):
        return tuple(int(x) if x.isdigit() else 0 for x in re.split(r"[.\-]", v)) if v else ()
    return key(a) > key(b)


def backup_root() -> Path:
    return Path(os.environ.get("OPENMHP_HOME", "~/.openmhp")).expanduser() / "skill-backups"


def _backup(target: Path, stamp: str, root: Path | None = None) -> Path:
    keep = (root or backup_root()) / stamp / target.parent.parent.name.lstrip(".") / target.name
    keep.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(target, keep, dirs_exist_ok=True)
    return keep


def install(dest: Path, names: list[str] | None = None, *, replace_changed: bool = False,
            skipped: list | None = None, backup: bool = True) -> list[str]:
    """Copy the bundled skills into one harness folder. A copy newer than this package's is never replaced; a copy
    changed by hand is replaced only with replace_changed=True (a person asked), and anything replaced is backed up
    first. `skipped` collects what was left alone, with why."""
    from . import __version__
    dest.mkdir(parents=True, exist_ok=True)
    states = {r["name"]: r for r in status([dest])}
    stamp = time.strftime("%Y%m%dT%H%M%S")
    out = []
    for skill in bundled():
        if names is not None and skill.name not in names:
            continue
        target = dest / skill.name
        st = states.get(skill.name, {}).get("state")
        if st == "newer" or (st == "changed" and not replace_changed):
            if skipped is not None:
                skipped.append({**states[skill.name], "why": "a newer version is installed" if st == "newer"
                                else "changed by hand; `mhp skills install` replaces it (backed up first)"})
            continue
        if st == "current":
            out.append(str(target))
            continue
        tmp = dest / f".{skill.name}.installing"
        if tmp.exists():
            shutil.rmtree(tmp)
        shutil.copytree(skill, tmp, ignore=shutil.ignore_patterns("__pycache__"))   # whole, before the old one goes
        if target.exists():
            if backup:
                _backup(target, stamp)
            shutil.rmtree(target)
        os.replace(tmp, target)
        (target / MARK).write_text(json.dumps({"name": skill.name, "version": version_of(skill), "digest": digest(target),
                                               "openmhp": __version__, "installed": time.strftime("%Y-%m-%dT%H:%M:%S")},
                                              indent=1), encoding="utf-8")
        out.append(str(target))
    return out


def harness_dirs() -> list[Path]:
    return [d for d in HARNESS_DIRS.values() if d.parent.exists()]


def status(dirs: list[Path] | None = None) -> list[dict]:
    """Every installed copy of a bundled skill, and whether it is current.

    state: current   - the same as this package's
           outdated  - this package has a newer one and the copy is as installed: safe to replace
           newer     - the copy is a newer version than this package's (a newer install put it there): left alone
           changed   - someone edited the copy since it was installed: left alone
           missing   - not installed in that harness"""
    rows = []
    for d in harness_dirs() if dirs is None else dirs:
        for skill in bundled():
            target = d / skill.name
            row = {"dir": str(d), "name": skill.name, "path": str(target), "bundled": version_of(skill)}
            if not (target / "SKILL.md").is_file():
                rows.append({**row, "state": "missing", "installed": None})
                continue
            have, mine = version_of(target), digest(target)
            row["installed"] = have
            if mine == digest(skill):
                rows.append({**row, "state": "current"})
                continue
            try:
                mark = json.loads((target / MARK).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                mark = None
            if mark is not None:
                untouched = mark.get("digest") == mine
            else:          # installed before markers existed: ours if it says so and is older than the bundled one
                text = (target / "SKILL.md").read_text(encoding="utf-8", errors="replace")
                untouched = "author: openmhp" in text and _newer(version_of(skill), have)
            if _newer(have, version_of(skill)):
                rows.append({**row, "state": "newer"})
                continue
            rows.append({**row, "state": "outdated" if untouched else "changed"})
    return rows


def refresh(dirs: list[Path] | None = None, backup_root: Path | None = None) -> dict:
    """Replace every outdated copy with this package's skill, backing up what was there. Changed copies stay."""
    if dirs is None and (os.environ.get("OPENMHP_NO_SKILL_REFRESH") or os.environ.get("OPENMHP_NO_UPDATE_CHECK")):
        return {"updated": [], "changed": []}          # off, as update checks are (tests and CI set it)
    rows = status(dirs)
    updated, changed = [], [r for r in rows if r["state"] == "changed"]
    stamp = time.strftime("%Y%m%dT%H%M%S")
    root = backup_root or Path(os.environ.get("OPENMHP_HOME", "~/.openmhp")).expanduser() / "skill-backups"
    for r in rows:
        if r["state"] != "outdated":
            continue
        try:
            keep = _backup(Path(r["path"]), stamp, root)
            install(Path(r["dir"]), [r["name"]], backup=False)
            updated.append({**r, "backup": str(keep)})
        except OSError as e:
            changed.append({**r, "error": str(e)})
    return {"updated": updated, "changed": changed}


def notice(result: dict | None = None) -> str | None:
    """One sentence for the agent to pass on after refresh(), or None when there is nothing to say."""
    result = refresh() if result is None else result
    parts = []
    if result["updated"]:
        names = sorted({f"{r['name']} {r['bundled']}" for r in result["updated"]})
        parts.append("The OpenMHP skills were updated to the versions in this install (" + ", ".join(names) + "). "
                     "They load the next time the agent starts; tell the user in one sentence.")
    if result["changed"]:
        names = sorted({f"{r['name']} in {r['dir']}" for r in result["changed"]})
        parts.append("These OpenMHP skills differ from this install's and were changed by hand, so they were left "
                     "as they are: " + "; ".join(names) + ". If the user wants the new versions, `mhp skills install` "
                     "replaces them (their copies are backed up first, under ~/.openmhp/skill-backups).")
    return " ".join(parts) or None


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] == "list":
        for s in bundled():
            print(f"{s.name} {version_of(s) or ''}".strip())
        return 0
    if argv[0] == "status":
        for r in status():
            print(f"{r['state']:<9} {r['name']} {r['installed'] or '-'} (this install has {r['bundled']})  {r['path']}")
        return 0
    if argv[0] != "install":
        sys.exit(__doc__)
    dests = [Path(d).expanduser() for d in argv[1:]]
    if not dests:
        dests = harness_dirs() or [HARNESS_DIRS["Claude Code"]]
    skipped: list = []
    for d in dests:
        for path in install(d, replace_changed=True, skipped=skipped):
            print("installed", path)
    for r in skipped:
        print(f"left alone {r['path']}: {r['why']} ({r['installed']} there, {r['bundled']} here)")
    if skipped:
        print("to use this install's version anyway: delete that folder, then run  mhp skills install  again")
    return 0
