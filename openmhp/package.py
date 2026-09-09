"""Device packages: a device described the way an Agent Skill is.

    thermocycler-01/
    ├── DEVICE.md          Level 1: YAML frontmatter = the card (always cheap to load)
    │                      Level 2: Markdown body   = operating instructions (loaded when chosen)
    ├── descriptor.yaml    Level 3: full machine-readable spec (limits, params, examples)
    ├── driver.py          Level 3: code; a Driver subclass (or BoundDriver factory)
    ├── references/        Level 3: manual excerpts, calibration notes, SOPs
    └── scripts/           Level 3: reusable orchestration scripts for mhp_run

Progressive disclosure on the wire:
    device/describe {detail: "card"}     -> frontmatter (+ live state, capability names)
    device/describe {detail: "summary"}  -> card + instructions + slim capability table
    device/describe {detail: "full"} / {select: ...} -> descriptor.yaml
    resources/list, resources/read {path} -> references/, scripts/, descriptor.yaml, driver.py

Frontmatter fields: id, class, make, model, location, tags, description (what the
device is and when an agent should pick it; <= 1024 chars), driver (optional
"driver.py:ClassName"), mhp (protocol version).
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

CARD_FIELDS = ("id", "class", "make", "model", "location", "tags", "description")
TEXT_SUFFIXES = {".md", ".txt", ".yaml", ".yml", ".json", ".py", ".csv", ".toml", ".sh"}
RESOURCE_CAP = 64_000       # chars returned by resources/read


def _yaml_load(text: str):
    try:
        import yaml
    except ImportError as e:                                    # pragma: no cover
        raise RuntimeError("device packages need PyYAML: pip install pyyaml") from e
    return yaml.safe_load(text) or {}


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split '---\\nyaml\\n---\\nbody' -> (dict, body)."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if not m:
        return {}, text
    return _yaml_load(m.group(1)), m.group(2).strip()


@dataclass
class DevicePackage:
    dir: Path
    meta: dict                       # frontmatter
    instructions: str                # DEVICE.md body
    descriptor: dict                 # merged: descriptor.yaml + meta -> descriptor["device"]
    resources: list[str] = field(default_factory=list)

    def resource_path(self, rel: str) -> Path:
        p = (self.dir / rel).resolve()
        if self.dir.resolve() not in p.parents and p != self.dir.resolve():
            raise PermissionError(f"{rel} is outside the device package")
        return p

    def read_resource(self, rel: str) -> dict:
        p = self.resource_path(rel)
        if not p.is_file():
            raise FileNotFoundError(rel)
        if p.suffix.lower() not in TEXT_SUFFIXES:
            return {"path": rel, "bytes": p.stat().st_size, "text": None, "note": "binary resource; fetch out of band"}
        text = p.read_text(errors="replace")
        return {"path": rel, "text": text[:RESOURCE_CAP], "truncated": len(text) > RESOURCE_CAP}

    def load_driver_class(self):
        spec_name = self.meta.get("driver", "driver.py")
        file, _, cls = spec_name.partition(":")
        path = self.resource_path(file)
        modname = f"mhp_pkg_{re.sub(r'[^a-z0-9]', '_', self.meta['id'].lower())}"
        spec = importlib.util.spec_from_file_location(modname, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[modname] = mod
        spec.loader.exec_module(mod)
        if cls:
            return getattr(mod, cls)
        from .driver import Driver
        if hasattr(mod, "DEVICE"):
            return lambda: mod.DEVICE                                     # BoundDriver / adapter instance
        cands = [v for v in vars(mod).values() if isinstance(v, type) and issubclass(v, Driver) and v is not Driver]
        local = [c for c in cands if c.__module__ == modname]
        cands = local or cands                                            # prefer classes defined here, accept imports
        if len(cands) != 1:
            raise RuntimeError(f"{path}: expected exactly one Driver subclass or a DEVICE object, found {len(cands)}")
        return cands[0]


def load_package(path: str | Path) -> DevicePackage:
    d = Path(path)
    md = d / "DEVICE.md"
    if not md.is_file():
        raise FileNotFoundError(f"{d} has no DEVICE.md")
    meta, body = parse_frontmatter(md.read_text())
    if "id" not in meta or "class" not in meta:
        raise ValueError(f"{md}: frontmatter needs at least id and class")

    desc: dict = {}
    for name in ("descriptor.yaml", "descriptor.yml", "descriptor.json"):
        f = d / name
        if f.is_file():
            desc = json.loads(f.read_text()) if name.endswith(".json") else _yaml_load(f.read_text())
            break
    device = {**desc.get("device", {}), **{k: meta[k] for k in CARD_FIELDS if k in meta}}
    descriptor = {**desc, "device": device}
    descriptor.setdefault("signals", []); descriptor.setdefault("settings", []); descriptor.setdefault("actions", [])
    descriptor.setdefault("safety", {})

    resources = sorted(str(p.relative_to(d)) for p in d.rglob("*")
                       if p.is_file() and not p.name.startswith(".") and "__pycache__" not in p.parts
                       and p.name != "DEVICE.md")
    return DevicePackage(d, meta, body, descriptor, resources)


def load_driver(path: str | Path):
    """Instantiate the package's driver with descriptor, instructions and resources attached."""
    pkg = load_package(path)
    cls = pkg.load_driver_class()
    drv = cls()
    drv.attach_package(pkg)
    return drv
