"""Tell people that a newer OpenMHP is out: inside an agent harness, on a lab PC running `mhp node`,
and on the gateway that sees every lab PC.

Nothing here ever blocks or updates anything by itself (a qualified instrument PC changes software
under change control, not on its own). The MCP server, node and gateway never block on this. At start it reads a small cache (~/.openmhp/update-check.json) and,
when that is older than a day, refreshes it on a daemon thread from PyPI's public JSON endpoint. The only
thing sent is an anonymous GET for the package name. The bridge passes the result to the agent once per
session, with the command that upgrades this particular install.

Set OPENMHP_NO_UPDATE_CHECK=1 to turn it off (air-gapped labs, CI).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import threading
import time
import urllib.request
from pathlib import Path

from . import __version__

PYPI_URL = "https://pypi.org/pypi/openmhp/json"
CHECK_EVERY_S = 24 * 3600


def disabled() -> bool:
    return os.environ.get("OPENMHP_NO_UPDATE_CHECK", "").strip().lower() not in ("", "0", "false", "no")


def home() -> Path:
    return Path(os.environ.get("OPENMHP_HOME", Path.home() / ".openmhp")).expanduser()


def cache_path() -> Path:
    return home() / "update-check.json"


def parse(v: str) -> tuple[int, ...] | None:
    """Release versions only: '0.10.0' -> (0, 10, 0). Pre-releases and dev builds are never offered."""
    return tuple(int(x) for x in v.split(".")) if re.fullmatch(r"\d+(\.\d+)*", v or "") else None


def newer(latest: str | None, current: str = __version__) -> bool:
    a, b = parse(latest or ""), parse(current)
    return bool(a and b and a > b)


def read_cache() -> dict:
    try:
        return json.loads(cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def fetch_latest(timeout: float = 4.0) -> str | None:
    req = urllib.request.Request(PYPI_URL, headers={"Accept": "application/json", "User-Agent": f"openmhp/{__version__}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())["info"]["version"]


def refresh(fetch=fetch_latest, now: float | None = None) -> dict:
    """Re-check when the cache is stale. Never raises: an offline lab simply sees no notice."""
    now = time.time() if now is None else now
    cache = read_cache()
    if disabled() or now - float(cache.get("checked", 0)) < CHECK_EVERY_S:
        return cache
    try:
        cache = {"checked": now, "latest": fetch()}
    except Exception:                                          # noqa: BLE001  offline, proxy, PyPI down
        cache = {"checked": now, "latest": cache.get("latest")}
    try:
        cache_path().parent.mkdir(parents=True, exist_ok=True)
        cache_path().write_text(json.dumps(cache), encoding="utf-8")
    except OSError:
        pass
    return cache


def refresh_in_background() -> None:
    if not disabled():
        threading.Thread(target=refresh, name="mhp-update-check", daemon=True).start()


def latest_known(*others: str | None) -> str:
    """The newest release this process knows of: its own version, the cached PyPI answer, and any others
    (a gateway passes on what it knows, so a lab PC with no internet still learns of a release)."""
    known = [v for v in (__version__, read_cache().get("latest"), *others) if parse(v or "")]
    return max(known, key=parse)


def watch(on_newer, every_s: float = 3600, stop: threading.Event | None = None) -> threading.Event:
    """For long-running processes (a node, a gateway): re-check in the background and call on_newer(version)
    once for each newer release seen. Returns the Event that stops it."""
    stop = stop or threading.Event()

    def loop():
        told = None
        while not stop.is_set():
            refresh()
            latest = read_cache().get("latest")
            if newer(latest) and latest != told:
                told = latest
                try:
                    on_newer(latest)
                except Exception:                              # noqa: BLE001  a notice must never take a node down
                    pass
            stop.wait(every_s)
    if not disabled():
        threading.Thread(target=loop, name="mhp-update-watch", daemon=True).start()
    return stop


def installed_by_npx() -> bool:
    return Path(sys.prefix).resolve() == (home() / "venv").resolve()


def upgrade_command() -> str:
    """The command that upgrades THIS install: the npx launcher's venv, or whatever pip put it in."""
    if installed_by_npx():
        return "npx -y openmhp-cli@latest update"
    return 'pip install -U "openmhp[all]" && mhp skills install'


def _q(x: str | Path) -> str:
    x = str(x)
    return f'"{x}"' if " " in x else x


def node_upgrade_command(folder: str | Path, as_service: bool, python: str | None = None) -> str:
    """What the person at a lab PC runs. Reinstalling the service restarts it on the new version. The pip
    route names the interpreter the node runs on when `pip`/`mhp` on PATH belong to another environment,
    so the update lands where the node actually runs."""
    f = str(folder) if str(folder).startswith("<") else _q(Path(folder).expanduser().resolve())
    exe = Path(python or sys.executable)
    if exe.resolve().parent == (home() / "venv" / ("Scripts" if os.name == "nt" else "bin")).resolve():
        return f"npx -y openmhp-cli@latest node {f}"
    on_path = all((w := shutil.which(t)) and Path(w).resolve().parent == exe.resolve().parent for t in ("pip", "mhp"))
    pip, mhp = ("pip", "mhp") if on_path else (f"{_q(exe)} -m pip", f"{_q(exe)} -m openmhp.cli")
    if as_service:
        return f'{pip} install -U "openmhp[node]" && {mhp} node {f} --install-service'
    return f'{pip} install -U "openmhp[node]", then start `{mhp} node {f}` again'


def notice() -> str | None:
    """One plain sentence for the agent to pass on, or None when this install is current."""
    if disabled():
        return None
    latest = read_cache().get("latest")
    if not newer(latest):
        return None
    return (f"OpenMHP {latest} is available; this server runs {__version__}. Tell the user once, in one sentence, "
            f"and offer to run `{upgrade_command()}` for them, then restart the agent (or reconnect the openmhp MCP "
            "server) so the new version loads. Do not interrupt work in progress for it.")
