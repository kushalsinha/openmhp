"""Scientist folders on a gateway: one folder per scientist, every run of theirs inside it.

    <lab root>/scientists/<name>/
        profile.json            who this is and how their machine reaches the gateway
        runs/<run id>/
            in/                 what their agent copied over: skills, scripts, data
            preview/            what a rehearsal produced for them to look at
            out/                results their machine pulls when the run ends
            meta.json           the run's state

The lab root is `OPENMHP_LAB_ROOT`, or `<OPENMHP_HOME>/gateway/lab`. A name is also a valid Linux
user name, so a gateway can give each scientist their own user owning their folder. Run IDs are
`R-YYMM-NNNN`, unique on the gateway.
"""
from __future__ import annotations

import json
import os
import re
import time
from contextlib import contextmanager
from pathlib import Path

NAME = re.compile(r"^[a-z][a-z0-9_-]{0,30}$")
RUN_ID = re.compile(r"^R-\d{4}-\d{4,}$")
RUN_PARTS = ("in", "preview", "out")


def lab_root() -> Path:
    env = os.environ.get("OPENMHP_LAB_ROOT")
    if env:
        return Path(env).expanduser()
    return Path(os.environ.get("OPENMHP_HOME", "~/.openmhp")).expanduser() / "gateway" / "lab"


def check_name(name: str) -> str:
    if not isinstance(name, str) or not NAME.match(name):
        raise ValueError(f"{name!r} is not a usable scientist name: lower-case letters, digits, '-' and '_', "
                         "starting with a letter, at most 31 characters (it doubles as a Linux user name)")
    return name


def folder(name: str, root: Path | None = None) -> Path:
    return (root or lab_root()) / "scientists" / check_name(name)


def _write_json(path: Path, obj: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def create(name: str, *, root: Path | None = None, ssh_key: str | None = None, agent: str | None = None) -> dict:
    """Make (or update) a scientist's folder and profile. Existing runs are never touched."""
    d = folder(name, root)
    (d / "runs").mkdir(parents=True, exist_ok=True)
    prof = load_profile(name, root) or {"name": name, "created": time.strftime("%Y-%m-%dT%H:%M:%S")}
    if ssh_key is not None:
        prof["ssh_key"] = ssh_key.strip()
    if agent is not None:
        prof["agent"] = agent
    _write_json(d / "profile.json", prof)
    return prof


def load_profile(name: str, root: Path | None = None) -> dict | None:
    p = folder(name, root) / "profile.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def names(root: Path | None = None) -> list[str]:
    base = (root or lab_root()) / "scientists"
    return sorted(p.name for p in base.iterdir() if p.is_dir() and NAME.match(p.name)) if base.is_dir() else []


# ---- runs ----------------------------------------------------------------------------------------
@contextmanager
def _locked(path: Path):
    """An exclusive lock on a small file, so two `mhp-gw open` at once never get the same run ID."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+", encoding="utf-8") as f:
        try:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX)
        except ImportError:                     # Windows, development only: the gateway runs on Linux
            pass
        yield f


def new_run_id(root: Path | None = None, now: float | None = None) -> str:
    root = root or lab_root()
    month = time.strftime("%y%m", time.localtime(now))
    with _locked(root / "run-ids.lock"):
        counter = root / "run-ids.json"
        try:
            seen = json.loads(counter.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            seen = {}
        n = seen.get(month, 0) + 1
        seen[month] = n
        _write_json(counter, seen)
    return f"R-{month}-{n:04d}"


def check_run_id(run_id: str) -> str:
    if not isinstance(run_id, str) or not RUN_ID.match(run_id):
        raise ValueError(f"{run_id!r} is not a run ID (they look like R-2611-0042)")
    return run_id


def run_folder(name: str, run_id: str, root: Path | None = None) -> Path:
    return folder(name, root) / "runs" / check_run_id(run_id)


def open_run(name: str, root: Path | None = None) -> dict:
    """A new run in the scientist's folder, ready for their agent to copy files into `in/`."""
    if load_profile(name, root) is None:
        raise LookupError(f"no scientist {name!r} on this gateway")
    run_id = new_run_id(root)
    d = run_folder(name, run_id, root)
    for part in RUN_PARTS:
        (d / part).mkdir(parents=True, exist_ok=True)
    meta = {"id": run_id, "owner": name, "state": "open", "created": time.strftime("%Y-%m-%dT%H:%M:%S")}
    _write_json(d / "meta.json", meta)
    return meta


def load_run(name: str, run_id: str, root: Path | None = None) -> dict | None:
    try:
        return json.loads((run_folder(name, run_id, root) / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def runs(name: str, root: Path | None = None) -> list[dict]:
    base = folder(name, root) / "runs"
    out = []
    if base.is_dir():
        for d in sorted(base.iterdir()):
            if d.is_dir() and RUN_ID.match(d.name):
                meta = load_run(name, d.name, root)
                if meta:
                    out.append(meta)
    return out
