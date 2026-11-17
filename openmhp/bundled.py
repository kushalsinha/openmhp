"""The ready-made device packages that ship inside the wheel (openmhp/supported_devices, from the repository's
supported-devices/ folder), so `mhp node add` and `mhp lab add` need no web or git access for them."""
from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent
HOME_REPO = "kushalsinha/openmhp"


def devices_dir() -> Path | None:
    """openmhp/supported_devices in an installed wheel; supported-devices/ beside the package in a checkout."""
    for d in (HERE / "supported_devices", HERE.parent / "supported-devices"):
        if d.is_dir():
            return d
    return None


def package(name: str) -> Path | None:
    d = devices_dir()
    p = d / name if d else None
    return p if p and (p / "DEVICE.md").is_file() else None


def for_target(target: str) -> Path | None:
    """The shipped copy behind a registry target `github:kushalsinha/openmhp/supported-devices/<name>`, unless the
    target pins another ref (then the person asked for that version, which only GitHub has)."""
    spec = target[len("github:"):] if target.startswith("github:") else target
    spec, _, ref = spec.partition("@")
    parts = spec.strip("/").split("/")
    if ref not in ("", "main") or "/".join(parts[:2]) != HOME_REPO or parts[2:3] != ["supported-devices"] or len(parts) != 4:
        return None
    return package(parts[3])
