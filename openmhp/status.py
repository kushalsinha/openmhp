"""`mhp status`: this machine, in one answer. What it is set up as (agent machine, instrument PC, lab gateway), the
state of each part, and the one next step for each part that needs one.

    mhp status            plain lines for a person
    mhp status --json     the same, for an agent or a script

Exit code: 0 when nothing needs doing, 1 when something does (each such part names its next step).
Read-only: it never changes, starts or installs anything.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from . import __version__


def part(name: str, state: str, detail: str = "", next_step: str | None = None) -> dict:
    from .states import check_status_part
    check_status_part(name, state)                     # only declared states: these words are documented (SPEC 10.2)
    return {"part": name, "state": state, "detail": detail, **({"next": next_step} if next_step else {})}


def install_part() -> dict:
    from . import update_check as U
    latest = U.latest_known()
    if U.newer(latest):
        return part("install", "outdated", f"OpenMHP {__version__} ({sys.executable}); {latest} is out", U.upgrade_command())
    return part("install", "current", f"OpenMHP {__version__} ({sys.executable})")


def agent_parts() -> list[dict]:
    from . import agent as A, skills_install as SK
    out = []
    cfg = A.load_agent_config()
    if cfg is not None:
        try:
            import urllib.error
            import urllib.request
            token, ctx = A.access(cfg["gateway"])
            req = urllib.request.Request(cfg["gateway"] + "/", headers={"Authorization": f"Bearer {token}"})
            with urllib.request.urlopen(req, context=ctx, timeout=6) as r:
                doc = json.loads(r.read())
            out.append(part("gateway link", "connected", f"{cfg['gateway']} as '{cfg['name']}', "
                            f"{len(doc.get('devices', []))} instrument(s) reachable"))
        except urllib.error.HTTPError as e:
            out.append(part("gateway link", "unpaired" if e.code in (401, 403) else "error", f"{cfg['gateway']} answered {e.code}",
                            "pair again: ask the operator for a code (mhp gateway pair-agent there), then "
                            f"mhp agent --join {cfg['gateway']} <code> --name <your name>" if e.code in (401, 403) else None))
        except Exception as e:                                   # noqa: BLE001
            out.append(part("gateway link", "unreachable", f"{cfg['gateway']}: {e}",
                            "check the network or VPN; the operator can check the gateway with mhp gateway status"))
        if cfg.get("ssh"):
            out.append(part("runs over SSH", "set up", f"as scientist '{cfg['ssh']['scientist']}' (ssh mhp-gateway mhp-gw help)"))
        elif cfg.get("ssh_error"):
            out.append(part("runs over SSH", "not set up", cfg["ssh_error"],
                            "ask the gateway operator to run mhp gateway ssh, then pair again"))
    rows = SK.status()
    if rows:
        bad = [r for r in rows if r["state"] in ("missing", "outdated")]
        mine = [r for r in rows if r["state"] in ("changed", "newer")]
        detail = f"{len(rows) - len(bad) - len(mine)} current" + (f", {len(bad)} missing or outdated" if bad else "") \
            + (f", {len(mine)} changed by hand or newer, left alone" if mine else "")
        out.append(part("agent skills", "needs update" if bad else "current", detail,
                        "mhp skills install" if bad else None))
    return out


def node_parts() -> list[dict]:
    from . import relay as R, service as svc
    from .node_add import default_dir, short
    from .node_setup import preflight_problems
    rec = svc.installed_record() or {}
    root = Path(rec.get("folder") or default_dir())
    folders = sorted(p.parent for p in root.glob("*/DEVICE.md")) if root.is_dir() else []
    st = svc.service_state()
    if not folders and not st["installed"] and R.load_node_config() is None:
        return []
    out = []
    problems = preflight_problems(folders, "127.0.0.1", int(rec.get("http") or 18900), check_ports=False)
    out.append(part("instruments", "ready" if folders and not problems else "not ready" if folders else "none",
                    f"{len(folders)} package(s) in {short(root)}" + (": " + "; ".join(problems) if problems else ""),
                    None if folders and not problems else
                    (problems[0].split("Run:", 1)[1].strip() if problems and "Run:" in problems[0] else "mhp node add <package>")))
    if st["installed"]:
        if not root.is_dir():
            out.append(part("background service", "broken", f"it serves {short(root)}, which no longer exists",
                            "mhp node <devices folder> --install-service   (or mhp node --uninstall-service)"))
        else:
            word = {True: "running", False: "stopped", None: "installed"}[st["running"]]
            out.append(part("background service", word, f"serves {short(root)}",
                            None if st["running"] is not False else f"mhp node {short(root)} --install-service"))
    elif folders:
        out.append(part("background service", "not installed", "the instruments are served only while a window runs mhp node",
                        f"mhp node {short(root)} --install-service"))
    cfg = R.load_node_config()
    if cfg is not None:
        link = R.load_link() or {}
        state = link.get("state", "unknown")
        fix = None if state in ("connected", "unknown", "unreachable") else \
            f"pair again: mhp gateway pair on the gateway, then  mhp node --join {cfg['gateway']} <code>"
        out.append(part("gateway link", state, f"{cfg['gateway']} as '{cfg.get('name')}'"
                        + (f" ({link.get('detail')}, since {link.get('since')})" if link.get("detail") else ""), fix))
    return out


def gateway_parts() -> list[dict]:
    from . import gateway as G, service as svc
    state = G.load()
    if state is None:
        return []
    out = []
    live = G._live()
    st = svc.service_state(G.SERVICE)
    if live is None:
        out.append(part("gateway", "not running", G.agent_url(state),
                        "mhp gateway restart" if st["installed"] else "mhp gateway serve --install-service"))
    elif live.get("openmhp") != __version__:
        out.append(part("gateway", "running old code", f"{G.agent_url(state)} runs OpenMHP {live.get('openmhp')}, "
                        f"this install is {__version__}", "mhp gateway restart"))
    else:
        nodes = live.get("nodes", {})
        on = sum(1 for n in nodes.values() if n.get("online"))
        out.append(part("gateway", "running", f"{G.agent_url(state)}, {on}/{len(nodes)} lab PC(s) online"))
    if not st["installed"]:
        out.append(part("gateway service", "not installed", "it stops when its terminal closes",
                        "mhp gateway serve --install-service"))
    return out


def collect() -> dict:
    roles = {"agent machine": agent_parts(), "instrument PC": node_parts(), "lab gateway": gateway_parts()}
    roles = {k: v for k, v in roles.items() if v}
    todo = [p for ps in [[install_part()], *roles.values()] for p in ps if p.get("next")]
    return {"openmhp": __version__, "install": install_part(), "roles": roles, "todo": todo}


def main(args: list[str]) -> int:
    doc = collect()
    if "--json" in args:
        print(json.dumps(doc, indent=1))
        return 1 if doc["todo"] else 0
    i = doc["install"]
    print(f"{i['detail']}" + (f"   -> {i['next']}" if i.get("next") else ""))
    if not doc["roles"]:
        print("\nThis machine is not set up as anything yet. Depending on what it is for:",
              "  where your agent runs:            mhp skills install, then register mhp-mcp with your agent  (mhp guide quickstart)",
              "  wired to an instrument:           mhp node add <package>            (mhp guide instruments lists them)",
              "  the lab's gateway:                mhp gateway init", sep="\n")
        return 1
    for role, parts in doc["roles"].items():
        print(f"\n{role}")
        for p in parts:
            print(f"  {p['part']:<19} {p['state']:<15} {p['detail']}")
            if p.get("next"):
                print(f"  {'':<19} next: {p['next']}")
    print("\n" + ("Nothing needs doing." if not doc["todo"] else f"{len(doc['todo'])} thing(s) to do, each with its next step above."))
    return 1 if doc["todo"] else 0
