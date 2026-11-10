"""``mhp node add <package> [<dir>]``: put a device package on this instrument PC.

A node serves whatever package folders sit in its devices directory; this is how a folder gets there
without a git checkout or a USB stick. The package name is looked up in the registry (the bundled
index ships with openmhp, so the list works offline), fetched as a tarball of the repository over
HTTPS (no git needed on the lab PC), copied into the devices directory, given a ``config.json`` from
its example, and the person is told, in order, what to fill in and run next.

``--from <folder | archive>`` takes the package from a local checkout, a copied folder or a .tar.gz
instead, for PCs with no internet.
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path

from . import registry

TARBALL = "https://codeload.github.com/{owner}/{repo}/tar.gz/{ref}"
DEFAULT_REF = "main"
HOME = Path(os.environ.get("OPENMHP_HOME", Path.home() / ".openmhp"))


def default_dir() -> Path:
    """Where packages go when no directory is given: the same place the agent-side tools use."""
    return HOME / "devices"


def short(p) -> str:
    """A path the way a person types it: ~ for the home folder on macOS and Linux, as is on Windows."""
    p = str(p)
    if os.name != "nt":
        home = str(Path.home())
        if p == home or p.startswith(home + os.sep):
            return "~" + p[len(home):]
    return p


def this_os() -> str:
    return {"win32": "Windows", "darwin": "macOS", "linux": "Linux"}.get(sys.platform, sys.platform)


def windows_only(folder: Path, entry: dict | None) -> bool:
    """Does the package drive its instrument through Windows-only vendor software?"""
    if (entry or {}).get("os") == "windows":
        return True
    setup = folder / "references" / "setup.md"
    if setup.is_file():
        first = setup.read_text(encoding="utf-8", errors="replace").splitlines()[:1]
        return bool(first) and "(windows)" in first[0].lower()
    return False


def config_keys(folder: Path, limit: int = 6) -> list[str]:
    """The settings a person types into config.json: the string-valued keys of the example, in its order."""
    ex = folder / "config.example.json"
    try:
        data = json.loads(ex.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    keys = [k for k, v in data.items() if isinstance(v, str)] if isinstance(data, dict) else []
    return keys[:limit] + (["..."] if len(keys) > limit else [])


def _frontmatter(folder: Path, key: str) -> str:
    try:
        for line in (folder / "DEVICE.md").read_text(encoding="utf-8", errors="replace").splitlines()[1:40]:
            if line == "---":
                break
            if line.startswith(key + ":"):
                return line.split(":", 1)[1].strip().strip('"')
    except OSError:
        pass
    return ""


def available() -> list[dict]:
    """Every package the registry knows, by name."""
    return sorted(registry.load(), key=lambda e: e.get("name", ""))


def lookup(name: str) -> dict:
    for e in available():
        if e.get("name") == name:
            return e
    names = ", ".join(e.get("name", "?") for e in available())
    raise LookupError(f"no package named {name!r}. Known packages: {names}. "
                      f"Run `mhp node add` alone for descriptions, or pass --from <folder> for your own package.")


def parse_github(target: str) -> tuple[str, str, str, str]:
    """github:owner/repo[/sub/path][@ref] -> owner, repo, sub, ref."""
    spec = target[len("github:"):] if target.startswith("github:") else target
    spec, _, ref = spec.partition("@")
    parts = spec.strip("/").split("/")
    if len(parts) < 2:
        raise ValueError(f"{target!r}: expected github:owner/repo/path")
    return parts[0], parts[1], "/".join(parts[2:]), ref or DEFAULT_REF


def _safe_members(tar: tarfile.TarFile, want: str):
    """Regular files and directories under ``want`` only: no links, no absolute paths, no `..`."""
    for m in tar.getmembers():
        parts = Path(m.name).parts
        if not parts or parts[0] in ("", "/", "..") or ".." in parts:
            continue
        rel = "/".join(parts[1:])                       # drop the "<repo>-<ref>/" the archive wraps everything in
        if not (rel == want or rel.startswith(want + "/")):
            continue
        if not (m.isfile() or m.isdir()):
            continue                                    # a symlink or device in a device package is never right
        yield m, Path(rel[len(want):].lstrip("/"))


def extract_package(archive: bytes | Path, sub: str, dest: Path) -> Path:
    """Copy supported-devices/<name> (``sub``) out of a repository tarball into ``dest``."""
    fobj = io.BytesIO(archive) if isinstance(archive, bytes) else open(archive, "rb")
    try:
        with tarfile.open(fileobj=fobj, mode="r:gz") as tar:
            found = False
            for m, rel in _safe_members(tar, sub.strip("/")):
                found = True
                target = dest / rel
                if m.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                src = tar.extractfile(m)
                if src is None:
                    continue
                with src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
    finally:
        fobj.close()
    if not found or not (dest / "DEVICE.md").is_file():
        raise FileNotFoundError(f"the archive has no device package at {sub}")
    return dest


def fetch(entry_target: str, dest: Path, archive_url: str | None = None) -> Path:
    """Download the repository tarball once and take the package folder out of it."""
    owner, repo, sub, ref = parse_github(entry_target)
    url = archive_url or TARBALL.format(owner=owner, repo=repo, ref=ref)
    req = urllib.request.Request(url, headers={"User-Agent": "openmhp"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    return extract_package(data, sub, dest)


def pip_lines(folder: Path) -> list[str]:
    """`pip install ...` commands the package's setup notes mention, deduplicated, openmhp itself dropped."""
    out: list[str] = []
    for md in sorted(folder.rglob("*.md")):
        for m in re.finditer(r"pip install ((?:\"[^\"]+\"|[\w\[\],.=<>~-]+)(?: (?:\"[^\"]+\"|[\w\[\],.=<>~-]+))*)", md.read_text(encoding="utf-8", errors="replace")):
            pkgs = [p for p in m.group(1).split() if p != "openmhp" and not p.startswith('"openmhp')]
            if pkgs and " ".join(pkgs) not in out:
                out.append(" ".join(pkgs))
    return out


def add(name: str, dest_dir: Path | str | None = None, source: str | Path | None = None) -> dict:
    """Install one package into ``dest_dir`` and return what happened and what to do next."""
    dest_dir = Path(dest_dir or default_dir()).expanduser()
    source = str(source) if source is not None else None
    entry = None
    if source is None or source.startswith("github:"):
        entry = lookup(name) if not (source or "").startswith("github:") else {"name": name, "target": source}
        target = entry["target"]
        if not str(target).startswith("github:"):
            raise ValueError(f"{name}: registry target {target!r} is not a github: target; use --from")
    folder = dest_dir / name
    if (folder / "DEVICE.md").exists():
        raise FileExistsError(f"{folder} already holds a package. To replace it, move that folder away first "
                              f"(its config.json is your lab's settings; keep a copy).")
    dest_dir.mkdir(parents=True, exist_ok=True)
    staging = dest_dir / f".{name}.partial"
    if staging.exists():
        shutil.rmtree(staging)
    try:
        if source is None or source.startswith("github:"):
            fetch(target, staging)
            origin = target
        elif source.startswith(("http://", "https://", "file:")) or source.endswith((".tar.gz", ".tgz")):
            if source.startswith(("http://", "https://", "file:")):
                fetch(f"github:x/x/supported-devices/{name}", staging, archive_url=source)
            else:
                extract_package(Path(source), f"supported-devices/{name}", staging)
            origin = source
        else:
            src = Path(source).expanduser()
            cand = [src, src / name, src / "supported-devices" / name]
            src = next((c for c in cand if (c / "DEVICE.md").is_file()), None)
            if src is None:
                raise FileNotFoundError(f"no device package {name!r} under {source} (looked for DEVICE.md in {[str(c) for c in cand]})")
            shutil.copytree(src, staging, ignore=shutil.ignore_patterns("__pycache__", "config.json", ".git"))
            origin = str(src)
        staging.rename(folder)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    made_config = False
    if (folder / "config.example.json").is_file() and not (folder / "config.json").is_file():
        shutil.copyfile(folder / "config.example.json", folder / "config.json")
        made_config = True
    from .validate import validate_path
    v = validate_path(str(folder))
    setup = next((p for p in (folder / "references" / "setup.md", folder / "SETUP.md") if p.is_file()), None)
    title = " ".join(x for x in (_frontmatter(folder, "make"), _frontmatter(folder, "model")) if x) or (entry or {}).get("model", "")
    return {"name": name, "title": title, "folder": str(folder), "dir": str(dest_dir),
            "dir_is_default": dest_dir.resolve() == default_dir().expanduser().resolve(),
            "origin": origin, "config_created": made_config,
            "config": str(folder / "config.json") if (folder / "config.json").is_file() else None,
            "config_keys": config_keys(folder),
            "setup": str(setup) if setup else None, "pip": pip_lines(folder),
            "windows_only": windows_only(folder, entry),
            "valid": v["ok"], "errors": v["errors"]}


def say_next(r: dict, joined: dict | None, service_installed: bool) -> str:
    """What is printed after ``add``: one line on what happened, then the few commands that remain."""
    where = "" if r["dir_is_default"] else f" {short(r['dir'])}"          # plain `mhp node` finds the default folder itself
    title = f" ({r['title']})" if r.get("title") else ""
    lines = []
    if r.get("windows_only") and sys.platform != "win32":
        lines.append(f"  note: this package needs the vendor's Windows software, and this is {this_os()}. Only the simulated "
                     f"twin runs here; to control the instrument, add it on the Windows PC wired to it.")
    steps = [f"pip install {p}" for p in r["pip"]]
    if r["config"]:
        keys = ", ".join(r.get("config_keys") or []) or "the values it asks for"
        hint = "   (references/setup.md explains each)" if r["setup"] else ""
        steps.append(f"edit {short(r['config'])}\n     fill in {keys}{hint}")
    steps.append(f"mhp node setup {r['name']}{where}   (asks the questions instead of steps 1-2, then checks)" if r["config"] or r["pip"] else f"mhp node{where} --check")
    if joined:
        steps.append(f"restart mhp node: {joined.get('gateway')} lists the new instrument when the node reconnects"
                     + (f"\n     (service: mhp node --uninstall-service, then mhp node{where} --install-service)" if service_installed else ""))
    else:
        steps.append(f"mhp node{where}   (with a gateway, the first time add:  --join <gateway url> <code>)")
    lines.append("\nnext:")
    lines += [f"  {i}. {st}" for i, st in enumerate(steps, 1)]
    return "\n".join(lines)


def say_available() -> str:
    rows = available()
    if not rows:
        return "no packages in the registry (is openmhp installed completely?)"
    w = max(len(e.get("name", "")) for e in rows)
    out = ["mhp node add <name>   adds one of these to this PC:", ""]
    for e in rows:
        desc = str(e.get("description", "")).split(". ")[0].rstrip(".")
        tag = "   [Windows]" if e.get("os") == "windows" else ""
        out.append(f"  {e.get('name', ''):{w}s}  {e.get('make', '')} {e.get('model', '')}: {desc}{tag}")
    out.append(f"\nthey go to {short(default_dir())} unless you name a folder.  Your own package:  mhp node add <name> --from <folder>")
    return "\n".join(out)


def main(args: list[str], source: str | None = None, *, no_setup: bool = False, yes: bool = False, sets: list[str] | None = None,
         all_fields: bool = False, no_pip: bool = False, base: int = 18900) -> int | str:
    """``mhp node add``. Returns 0/1, or "serve:<dir>" when the person asked to serve in this window."""
    import sys
    if not args:
        print(say_available(), file=sys.stderr)
        return 0
    name, dest = args[0], (args[1] if len(args) > 1 else None)
    try:
        r = add(name, dest, source)
    except (LookupError, FileExistsError, FileNotFoundError, ValueError, OSError, tarfile.TarError) as e:
        print(f"could not add {name}: {e}", file=sys.stderr)
        return 1
    from . import node_setup
    print(f"added {r['name']}" + (f" ({r['title']})" if r.get("title") else "") + f" to {short(r['dir'])}", file=sys.stderr)
    if not r["valid"]:
        print("  WARNING: the package did not pass validation: " + "; ".join(r["errors"]), file=sys.stderr)
    if no_setup or not (yes or node_setup.interactive()):
        print(say_next(r, _joined(), _service_installed()), file=sys.stderr)
        return 0
    return node_setup.run([Path(r["folder"])], Path(r["dir"]), base, yes=yes, sets=sets, all_fields=all_fields, no_pip=no_pip)


def _joined() -> dict | None:
    try:
        from . import relay
        return relay.load_node_config()
    except Exception:                                   # noqa: BLE001
        return None


def _service_installed() -> bool:
    try:
        from . import service
        return bool(service.status().get("installed"))
    except Exception:                                   # noqa: BLE001
        return False
