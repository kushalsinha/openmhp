"""Methods: the MHP primitive for named, versioned parameter sets. The rules are SPEC.md §4.5 (M1..M10);
this module is the reference store and enforces them one for one.

An HPLC or GC method, a PCR program, a diffraction scan: the same instrument runs different parameter
sets for different projects and compounds. They live in the device package, Level 3, under ``methods/``,
one folder per project, and every device answers ``methods/*`` by default (a device with no method-driven
action answers empty and refuses ``save``).

    methods/
    ├── _shared/<method>.yaml                 owned by no project
    └── <project>/<method>.yaml               the current version
                 <method>.history.jsonl       every earlier version, append-only
                 <method>.runs.jsonl          every run on this instrument, append-only
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Callable

import yaml

ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
SHARED = "_shared"
REQUIRED = ("name", "project", "action", "params", "compounds", "version", "hash", "created", "updated", "validated", "status")
OPTIONAL = ("author", "notes", "source", "derived_from")
SOURCE_KINDS = ("vendor_file", "manual", "person", "agent", "derived")
STATUS = ("active", "retired")
_MAX_HISTORY = 200


class MethodError(ValueError):
    """A malformed method or request; the driver maps it to InvalidValue."""


def _hash(action: str, params: dict) -> str:
    return hashlib.sha256(json.dumps({"action": action, "params": params}, sort_keys=True, default=str).encode()).hexdigest()[:12]


def _norm_list(v) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        v = [v]
    return sorted({str(x).strip().lower() for x in v if str(x).strip()})


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:12]


def card(m: dict) -> dict:
    """The record without params: what list and find return."""
    return {k: m.get(k) for k in ("project", "name", "version", "hash", "action", "compounds", "status", "validated",
                                  "author", "notes", "source", "derived_from", "updated")}


def provenance(m: dict, overrides: dict | None = None) -> dict:
    out = {"project": m.get("project"), "name": m.get("name"), "version": m.get("version"), "hash": m.get("hash")}
    if overrides:
        out["overrides"] = overrides
    return out


def params_for(m: dict, overrides: dict | None = None, explicit: dict | None = None) -> dict:
    """M6: the method's params, then overrides, then explicit params; later keys win."""
    out = dict(m.get("params") or {})
    out.update(overrides or {})
    out.update(explicit or {})
    return out


def split_id(name, project=None) -> tuple[str, str]:
    """'project/method' or a bare method id with a project (default _shared) -> (project, method)."""
    if not isinstance(name, str) or not name:
        raise MethodError("a method is named by 'project/method', or by name with project")
    if "/" in name:
        if project and project != name.split("/", 1)[0]:
            raise MethodError(f"method {name!r} names project {name.split('/', 1)[0]!r} but project={project!r} was given")
        project, name = name.split("/", 1)
    project = project or SHARED
    if not valid_project(project):
        raise MethodError(f"not a valid project id: {project!r} (lowercase letters, digits, '.', '_' or '-'; or _shared)")
    if not ID.match(name) or ".." in name:
        raise MethodError(f"not a valid method id: {name!r} (lowercase letters, digits, '.', '_' or '-')")
    return project, name


def valid_project(project) -> bool:
    return project == SHARED or (isinstance(project, str) and bool(ID.match(project)) and ".." not in project)


def check_record(rec, path: str = "") -> list[str]:
    """M3: exactly the allowed keys, every required one present and well-formed, name/project matching the path."""
    where = f"{path}: " if path else ""
    if not isinstance(rec, dict):
        return [f"{where}not a mapping"]
    errs = []
    extra = set(rec) - set(REQUIRED) - set(OPTIONAL)
    if extra:
        errs.append(f"{where}unknown keys {sorted(extra)}")
    missing = [k for k in REQUIRED if k not in rec]
    if missing:
        return errs + [f"{where}missing {k}" for k in missing]
    if not isinstance(rec["name"], str) or not ID.match(rec["name"]):
        errs.append(f"{where}name is not a valid id")
    if not valid_project(rec["project"]):
        errs.append(f"{where}project is not a valid id")
    if path:
        p = Path(path)
        if rec.get("name") != p.stem:
            errs.append(f"{where}name {rec.get('name')!r} does not match the file name {p.stem!r}")
        if rec.get("project") != p.parent.name:
            errs.append(f"{where}project {rec.get('project')!r} does not match the folder {p.parent.name!r}")
    if not isinstance(rec["action"], str) or not rec["action"]:
        errs.append(f"{where}action must be a non-empty string")
    if not isinstance(rec["params"], dict):
        errs.append(f"{where}params must be an object")
    if not _norm_list(rec.get("compounds")):
        errs.append(f"{where}compounds must name at least one compound")
    if not isinstance(rec["version"], int) or isinstance(rec["version"], bool) or rec["version"] < 1:
        errs.append(f"{where}version must be an integer >= 1")
    if isinstance(rec["action"], str) and isinstance(rec["params"], dict) and rec.get("hash") != _hash(rec["action"], rec["params"]):
        errs.append(f"{where}hash does not match action and params (expected {_hash(rec['action'], rec['params']) if isinstance(rec['params'], dict) else '?'})")
    for k in ("created", "updated"):
        if not isinstance(rec[k], (int, float)) or isinstance(rec[k], bool):
            errs.append(f"{where}{k} must be Unix seconds")
    v = rec["validated"]
    if v is not None and (not isinstance(v, dict) or v.get("hash") != rec.get("hash") or "at" not in v):
        errs.append(f"{where}validated must be null or {{at, hash}} with hash equal to the record's")
    if rec["status"] not in STATUS:
        errs.append(f"{where}status must be one of {STATUS}")
    src = rec.get("source")
    if src is not None and (not isinstance(src, dict) or src.get("kind") not in SOURCE_KINDS):
        errs.append(f"{where}source must be {{kind: {'|'.join(SOURCE_KINDS)}, ref}}")
    d = rec.get("derived_from")
    if d is not None and (not isinstance(d, dict) or not {"project", "name", "version"} <= set(d)):
        errs.append(f"{where}derived_from must be {{project, name, version}}")
    return errs


class MethodStore:
    def __init__(self, root: Path | str, capable: bool = True, check: Callable[[str, dict], None] | None = None,
                 method_driven: Callable[[], list[str]] | None = None):
        """`capable`: the device declares a method-driven action (M1). `check(action, params)`: the device's own
        parameter gate, run on save (M5). `method_driven()`: names of the actions methods may target."""
        self.root = Path(root)
        self.capable = capable
        self.check = check
        self.method_driven = method_driven or (lambda: [])

    # ---- files ------------------------------------------------------------
    def _path(self, project: str, name: str) -> Path:
        return self.root / project / f"{name}.yaml"

    def _load(self, p: Path) -> dict | None:
        try:
            rec = yaml.safe_load(p.read_text())
        except (OSError, yaml.YAMLError):
            return None
        return rec if not check_record(rec, str(p)) else None

    def _all(self, retired: bool = False) -> list[dict]:
        if not self.root.is_dir():
            return []
        out = []
        for p in sorted(self.root.glob("*/*.yaml")):
            rec = self._load(p)
            if rec and (retired or rec.get("status") == "active"):
                out.append(rec)
        return out

    def problems(self) -> list[str]:
        """Everything in the folder that breaks M2 or M3; used by the package validator."""
        if not self.root.is_dir():
            return []
        errs = []
        for p in sorted(self.root.iterdir()):
            if p.name == "README.md" or p.name.startswith("."):
                continue
            if not p.is_dir():
                errs.append(f"methods/{p.name}: only project folders and README.md belong directly under methods/")
                continue
            if not valid_project(p.name):
                errs.append(f"methods/{p.name}: not a valid project id")
                continue
            for f in sorted(p.iterdir()):
                rel = f"methods/{p.name}/{f.name}"
                if f.suffix == ".yaml":
                    try:
                        rec = yaml.safe_load(f.read_text())
                    except (OSError, yaml.YAMLError) as e:
                        errs.append(f"{rel}: unreadable YAML ({e})")
                        continue
                    for e in check_record(rec, str(f)):
                        errs.append(f"{rel}: {e.split(': ', 1)[-1]}")
                    if isinstance(rec, dict) and rec.get("action") and rec["action"] not in self.method_driven():
                        errs.append(f"{rel}: action {rec['action']!r} is not declared with methods: true")
                elif not (f.name.endswith(".history.jsonl") or f.name.endswith(".runs.jsonl")):
                    errs.append(f"{rel}: not a method file (<method>.yaml, .history.jsonl or .runs.jsonl)")
        return errs

    # ---- queries ----------------------------------------------------------
    def overview(self) -> dict:
        ms = self._all()
        return {"count": len(ms),
                "compounds": sorted({c for m in ms for c in _norm_list(m.get("compounds"))}),
                "projects": sorted({m["project"] for m in ms}),
                "actions": sorted({m["action"] for m in ms}),
                "method_driven": list(self.method_driven())}

    def list(self, compound: str | None = None, project: str | None = None, action: str | None = None,
             query: str | None = None, retired: bool = False) -> list[dict]:
        c = (compound or "").strip().lower()
        q = (query or "").lower().split()
        out = []
        for m in self._all(retired=retired):
            if c and c not in _norm_list(m.get("compounds")):
                continue
            if project and m["project"] != project:
                continue
            if action and m["action"] != action:
                continue
            if q and not all(t in json.dumps(card(m), default=str).lower() for t in q):
                continue
            out.append(card(m))
        return sorted(out, key=lambda x: x.get("updated") or 0, reverse=True)

    def get(self, name: str, project: str | None = None, version: int | None = None) -> dict:
        project, name = split_id(name, project)
        p = self._path(project, name)
        m = self._load(p) if p.is_file() else None
        if m is None:
            raise MethodError(f"no method {project}/{name}")
        if version is None or version == m["version"]:
            return m
        hist = self._path(project, name).with_suffix("").with_suffix(".history.jsonl")
        if hist.is_file():
            for line in hist.read_text().splitlines():
                try:
                    old = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if old.get("version") == version:
                    return old
        raise MethodError(f"method {project}/{name} has no version {version}")

    def find(self, compound: str, project: str | None = None, action: str | None = None) -> dict:
        """M8. Project methods first, then _shared, then other projects'."""
        compound = (compound or "").strip()
        if not compound:
            raise MethodError("find needs a compound")
        if project:
            split_id("x", project)                                    # validates the project id
        levels = ([(project, f"in project {project}")] if project and project != SHARED else []) + \
                 [(SHARED, "shared on this instrument")]
        for proj, label in levels:
            cands = self.list(compound=compound, project=proj, action=action)
            if len(cands) == 1:
                return {"choice": "one", "method": cands[0], "why": f"the only method for {compound} {label}",
                        **({"newProject": project} if project and proj != project else {})}
            if cands:
                return {"choice": "several", "candidates": cands, **({"newProject": project} if project and proj != project else {}),
                        "ask": f"There are {len(cands)} methods for {compound} {label}: " + ", ".join(c["name"] for c in cands)
                               + ". Which one should I use for this run?"}
        others = self.list(compound=compound, action=action)
        if len(others) == 1:
            return {"choice": "one", "method": others[0], **({"newProject": project} if project else {}),
                    "why": f"the only method for {compound} on this instrument, filed under project {others[0]['project']}"
                           + (f"; none under {project}" if project else "")}
        if others:
            return {"choice": "several", "candidates": others, **({"newProject": project} if project else {}),
                    "ask": f"There are {len(others)} methods for {compound} on this instrument"
                           + (f", none filed under project {project}" if project else "") + ": "
                           + ", ".join(f"{c['project']}/{c['name']}" for c in others) + ". Which one should I use?"}
        return {"choice": "none", "candidates": [], **({"newProject": project} if project else {}),
                "ask": f"No saved method for {compound}" + (f" in project {project}" if project else "")
                       + " on this instrument. Ask the person for the parameters, run once with them, and save them"
                       + (f" under project {project}" if project else "") + " so the next run can find them."}

    # ---- writing ----------------------------------------------------------
    def _append(self, p: Path, entry: dict) -> None:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")

    def save(self, method: dict, by: str | None = None, note: str | None = None) -> dict:
        """M4 and M5. The device assigns version, hash, timestamps, validated and status."""
        if not self.capable:
            raise MethodError("this device declares no method-driven action (methods: true on an action), so it keeps no methods")
        if not isinstance(method, dict):
            raise MethodError("a method is an object")
        project, name = split_id(method.get("name"), method.get("project"))
        action, params = method.get("action"), method.get("params")
        if not isinstance(action, str) or not action:
            raise MethodError("method.action is required: the method-driven action that receives the parameters")
        if action not in self.method_driven():
            raise MethodError(f"action {action!r} is not declared with methods: true; methods may target {self.method_driven()}")
        if not isinstance(params, dict):
            raise MethodError("method.params must be an object: exactly what actions/invoke sends")
        compounds = _norm_list(method.get("compounds") or method.get("compound"))
        if not compounds:
            raise MethodError("method.compounds is required: what the method is for")
        for k in set(method) - {"name", "project", "action", "params", "compounds", "compound", "author", "notes", "source", "derived_from"}:
            raise MethodError(f"method.{k} is not a caller's field; the device assigns version, hash, timestamps, validated and status")
        if self.check is not None:
            self.check(action, params)                                 # the device's refusal, unchanged; nothing written
        p = self._path(project, name)
        old = self._load(p) if p.is_file() else None
        h = _hash(action, params)
        now = time.time()
        rec = {"name": name, "project": project, "action": action, "params": params, "compounds": compounds,
               "version": 1, "hash": h, "created": (old or {}).get("created", now), "updated": now,
               "validated": {"at": now, "hash": h} if self.check is not None else None, "status": "active"}
        for k in OPTIONAL:
            v = method.get(k, (old or {}).get(k))
            if v is not None:
                rec[k] = v
        if note:
            rec["notes"] = note
        if by and not rec.get("author"):
            rec["author"] = by
        if old is not None:
            if old["hash"] == h and old["action"] == action and old["status"] == "active":
                rec["version"] = old["version"]                          # metadata-only change
            else:
                self._append(p.with_suffix("").with_suffix(".history.jsonl"), old)
                rec["version"] = old["version"] + 1
        errs = check_record(rec)
        if errs:
            raise MethodError("; ".join(errs))
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".yaml.tmp")
        tmp.write_text(yaml.safe_dump(rec, sort_keys=False, allow_unicode=True))
        os.replace(tmp, p)
        return rec

    def retire(self, name: str, project: str | None = None) -> dict:
        if not self.capable:
            raise MethodError("this device keeps no methods")
        m = self.get(name, project)
        if m["status"] == "retired":
            return m
        rec = {**m, "status": "retired", "updated": time.time()}
        p = self._path(m["project"], m["name"])
        tmp = p.with_suffix(".yaml.tmp")
        tmp.write_text(yaml.safe_dump(rec, sort_keys=False, allow_unicode=True))
        os.replace(tmp, p)
        return rec

    def record_run(self, prov: dict, entry: dict) -> None:
        """M6: every run of a method is appended to its runs file on the instrument."""
        try:
            project, name = split_id(prov.get("name"), prov.get("project"))
        except MethodError:
            return
        self._append(self.root / project / f"{name}.runs.jsonl", {"ts": time.time(), **entry})

    # ---- comparison -------------------------------------------------------
    @staticmethod
    def diff(a: dict, b: dict) -> dict:
        pa, pb = a.get("params") or {}, b.get("params") or {}
        changed = {k: {"from": pa.get(k), "to": pb.get(k)} for k in sorted(set(pa) | set(pb)) if pa.get(k) != pb.get(k)}
        return {"a": provenance(a), "b": provenance(b),
                "action": {"from": a.get("action"), "to": b.get("action")} if a.get("action") != b.get("action") else None,
                "params": changed, "same": not changed and a.get("action") == b.get("action")}
