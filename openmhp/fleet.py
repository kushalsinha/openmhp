"""The lab's fleet: the list of devices this bridge knows about, on disk.

    ~/.openmhp/fleet.json      {"devices": {"<id>": {"target": "...", "added": ts, "card": {...}}}}
    ~/.openmhp/devices/<id>/   device packages written by the onboarding skill

A Fleet feeds a Directory (search, live state) and a Lab (connections). Package
targets (``pkg:/path``) are hosted in-process by whoever loads the fleet, so a
scientist's laptop needs no separate device servers for the packages it owns.
"""
from __future__ import annotations

import json
import re
import os
import time
from pathlib import Path

from .client import connect
from .directory import Directory

HOME = Path(os.environ.get("OPENMHP_HOME", Path.home() / ".openmhp"))


SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def safe_id(value) -> str:
    """Device, package and onboarding ids are identifiers, never paths."""
    if not isinstance(value, str) or not SAFE_ID.match(value) or ".." in value:
        raise ValueError(f"not a valid id: {value!r} (use lowercase letters, digits, '.', '_' or '-')")
    return value


class Fleet:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else HOME / "fleet.json"
        self.devices: dict[str, dict] = {}
        if self.path.is_file():
            self.devices = json.loads(self.path.read_text()).get("devices", {})

    # ---- persistence -----------------------------------------------------
    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"devices": self.devices}, indent=1))

    @property
    def targets(self) -> dict[str, str]:
        return {i: d["target"] for i, d in self.devices.items()}

    # ---- membership ------------------------------------------------------
    def add(self, target: str, sim: bool = False, location: str | None = None) -> dict:
        """Add by http URL, pkg:<folder>, a bare folder path, local:<mod>:<Class>, or github:owner/repo[/path].
        sim=True adds the package's simulated twin (sim.py) instead of its driver. Fetches the card.

        `location` says where the instrument stands; a shared package cannot know that, so it is recorded
        here rather than in the package. A simulated twin stands nowhere and is labelled as such."""
        t = self._normalize(target)
        if t.startswith("github:"):
            t = "pkg:" + str(self.fetch_github(t[len("github:"):]))
        if sim and t.startswith("pkg:"):
            t = "sim:" + t[len("pkg:"):]
        dev = connect(t, "fleet")
        card = dev.call("device/describe", {"detail": "card"})
        dev.close()
        if sim:
            card = {**card, "id": card["id"] + "-sim", "tags": [*card.get("tags", []), "simulated"],
                    "description": "[SIMULATED] " + card.get("description", "")}
        where = str(location or "").strip() or ("simulated" if sim else str(card.get("location") or "").strip())
        card = {**card, "location": where}
        existing = self.devices.get(card["id"])
        if existing is not None and existing["target"] != t:
            raise ValueError(f"a device with id {card['id']!r} is already in the lab at {existing['target']}; "
                             "remove it first, or reload it if its package changed")
        self.devices[card["id"]] = {"target": t, "added": time.time(), "card": card, "sim": sim}
        self.save()
        return card

    def fetch_github(self, spec: str) -> Path:
        """github:owner/repo[/sub/path][@ref] -> local folder under ~/.openmhp/packages (shallow clone, refreshed on re-add)."""
        import shutil, subprocess
        spec, _, ref = spec.partition("@")
        parts = spec.strip("/").split("/")
        if len(parts) < 2:
            raise ValueError("github target must be owner/repo[/path]")
        owner, repo, sub = parts[0], parts[1], "/".join(parts[2:])
        dest = self.path.parent / "packages" / f"{owner}-{repo}"
        if dest.exists():
            shutil.rmtree(dest)
        cmd = ["git", "clone", "--depth", "1", "--quiet"] + (["--branch", ref] if ref else []) + [f"https://github.com/{owner}/{repo}.git", str(dest)]
        subprocess.run(cmd, check=True)
        folder = dest / sub if sub else dest
        if not (folder / "DEVICE.md").is_file():
            cands = [p.parent for p in folder.rglob("DEVICE.md")]
            if len(cands) == 1:
                folder = cands[0]
            else:
                raise FileNotFoundError(f"{spec}: no DEVICE.md at that path; packages found: {[str(c.relative_to(dest)) for c in cands]}")
        return folder

    def set_location(self, device_id: str, location: str) -> dict:
        """Record where an installed device stands. The fleet record is what the directory filters on."""
        entry = self.devices.get(device_id)
        if entry is None:
            raise KeyError(f"no device {device_id!r} in this lab")
        where = str(location or "").strip()
        if not where:
            raise ValueError("location cannot be empty; say where the device stands, e.g. \"bay 3, fume hood 2\"")
        entry["card"] = {**entry["card"], "location": where}
        self.save()
        return entry["card"]

    def unlocated(self) -> list[str]:
        """Installed devices that do not say where they are."""
        return [i for i, d in self.devices.items() if not str(d["card"].get("location") or "").strip()]

    def remove(self, device_id: str) -> bool:
        ok = self.devices.pop(device_id, None) is not None
        if ok:
            self.save()
        return ok

    def list(self) -> list[dict]:
        return [{"id": i, "target": d["target"], **{k: d["card"].get(k) for k in ("class", "location", "description")}}
                for i, d in self.devices.items()]

    def directory(self) -> Directory:
        d = Directory()
        for i, entry in self.devices.items():
            d.add(entry["card"], entry["target"])
        return d

    @staticmethod
    def _normalize(target: str) -> str:
        if target.startswith(("http://", "https://", "pkg:", "sim:", "local:", "stdio:", "github:")):
            return target
        if target.startswith("https://github.com/"):
            return "github:" + target[len("https://github.com/"):].removesuffix(".git")
        p = Path(target).expanduser()
        if (p / "DEVICE.md").is_file():
            return f"pkg:{p.resolve()}"
        if ":" in target and "/" not in target:               # host:port
            return f"http://{target}"
        raise ValueError(f"not a device target: {target!r} (use http://host:port, a device package folder, or local:module:Class)")

    # ---- discovery -------------------------------------------------------
    def scan(self, hosts: list[str] | None = None, ports: list[int] | None = None) -> list[dict]:
        """Devices on the network that are not yet in the fleet."""
        from .discovery import scan
        known = set(self.targets.values())
        return [r for r in scan(hosts, ports) if r["target"] not in known]

    def packages_dir(self) -> Path:
        d = self.path.parent / "devices"
        d.mkdir(parents=True, exist_ok=True)
        return d
