"""`--version` on every machine. A long-running process keeps the code it started with, so on the gateway and
on an instrument PC the version that matters is the one the running service has, not only the one `pip` installed.

    mhp --version              this OpenMHP, and which Python it runs in
    mhp gateway --version      ... and what the gateway service starts and what the running gateway answers
    mhp node --version         ... and what the instrument PC's service starts
    mhp agent --version        ... and what the gateway this machine joined runs
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

from . import __version__


def say(*lines: str) -> None:
    for line in lines:
        print(line)


def this_install() -> list[str]:
    from . import update_check as U
    lines = [f"OpenMHP {__version__}   ({sys.executable})"]
    latest = U.latest_known()
    if U.newer(latest):
        lines.append(f"  {latest} is out:  {U.upgrade_command()}")
    return lines


def _service(label: str, what: str) -> list[str]:
    from . import service as svc
    st = svc.service_state(label)
    if not st["installed"]:
        return [f"{what} service: not installed"]
    v = svc.openmhp_version_of(st["python"])
    word = {True: "running", False: "stopped", None: "installed"}[st["running"]]
    line = (f"{what} service ({word}) starts {st['python'] or '?'}, which has OpenMHP {v}" if v else
            f"{what} service ({word}) starts {st['python'] or '?'}, which cannot import OpenMHP (is that Python gone?)")
    return [line] + ([f"  not this {__version__}: install the service again with this mhp to move it"] if v and v != __version__ else [])


def gateway() -> list[str]:
    from . import gateway as G
    lines = _service(G.SERVICE, "gateway")
    if G.load() is None:
        return lines + ["no gateway set up on this machine (mhp gateway init)"]
    live = G._live()
    if live is None:
        lines.append("running gateway: none answers (mhp gateway restart)")
    else:
        v = live.get("openmhp")
        lines.append(f"running gateway: OpenMHP {v or 'an older version'}"
                     + ("" if v == __version__ else "   (started before the update: mhp gateway restart)"))
    return lines


def node() -> list[str]:
    from . import service as svc
    rec = svc.installed_record() or {}
    lines = _service(svc.LABEL, "instrument")
    if rec.get("folder"):
        lines.append(f"  serving {rec['folder']}")
    return lines


def agent() -> list[str]:
    from . import agent as A
    cfg = A.load_agent_config()
    if cfg is None:
        return ["not joined to a gateway (mhp agent --join <gateway url> <code> --name <your name>)"]
    try:
        token, ctx = A.access(cfg["gateway"])
        req = urllib.request.Request(cfg["gateway"] + "/", headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, context=ctx, timeout=8) as r:
            doc = json.loads(r.read())
        v = doc.get("openmhp")
        return [f"gateway {cfg['gateway']} (joined as '{cfg['name']}'): OpenMHP {v or '0.11.1 or older'}"]
    except urllib.error.HTTPError as e:
        return [f"gateway {cfg['gateway']}: answered {e.code}" + ("; this machine's token is not accepted there" if e.code == 401 else "")]
    except Exception as e:                                           # noqa: BLE001
        return [f"gateway {cfg['gateway']}: not reachable ({e})"]


def main(role: str | None = None) -> int:
    say(*this_install())
    extra = {"gateway": gateway, "node": node, "agent": agent}.get(role or "")
    if extra:
        say(*extra())
    return 0
