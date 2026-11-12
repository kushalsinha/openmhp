"""`mhp agent`: the agent-machine half of gateway pairing (SPEC 9.2), the mirror of `mhp node --join`.

    mhp agent --join https://gw.office ab12-cd34     pair this machine once, with a code from `mhp gateway pair-agent`
    mhp agent                                        which gateway this machine is paired with, and whether it answers
    mhp agent leave                                  forget the gateway (the operator revokes with `mhp gateway remove-agent`)

Joining downloads the gateway's certificate, shows its fingerprint, exchanges the code for an agent
token over POST /agent/join and saves ~/.openmhp/agent.json. From then on the client, `mhp lab` and
`mhp-mcp` present that token to the gateway's URLs and trust exactly the pinned certificate, so no
environment variable and no certificate copy is needed on an agent machine. The token never passes
through the operator's hands: the code is what travels in chat, lasts an hour and works once.
"""
from __future__ import annotations

import json
import os
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from .relay import HOME, fetch_cert, fingerprint, ssl_context

AGENT_FILE = HOME / "agent.json"
PIN_FILE = HOME / "agent-gateway-pin.pem"


def say(*lines: str) -> None:
    print("\n".join(lines), file=sys.stderr)


def load_agent_config() -> dict | None:
    return json.loads(AGENT_FILE.read_text(encoding="utf-8")) if AGENT_FILE.is_file() else None


def save_agent_config(cfg: dict) -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    AGENT_FILE.write_text(json.dumps(cfg, indent=1), encoding="utf-8")
    try:
        os.chmod(AGENT_FILE, 0o600)
    except OSError:
        pass


def join(gateway_url: str, code: str, name: str | None = None, *, quiet: bool = False) -> dict:
    """Pair this machine with a gateway once. Pins the gateway's certificate, exchanges the code for an
    agent token, saves agent.json. Raises SystemExit with a plain message on every failure a person can act on."""
    gateway_url = gateway_url.rstrip("/")
    if not gateway_url.startswith("https://"):
        raise SystemExit(f"the gateway address must start with https:// (got {gateway_url})")
    name = name or socket.gethostname().split(".")[0]
    try:
        pem = fetch_cert(gateway_url)
    except OSError as e:
        raise SystemExit(f"cannot reach {gateway_url} ({e}). Is `mhp gateway serve` running there, and can this "
                         "machine open the address in a browser?") from None
    HOME.mkdir(parents=True, exist_ok=True)
    PIN_FILE.write_text(pem, encoding="utf-8")
    fp = fingerprint(pem)
    if not quiet:
        say(f"gateway certificate fingerprint: {fp}", "  (compare with what `mhp gateway pair-agent` printed; stop if it differs)")
    ctx = ssl_context(str(PIN_FILE))
    req = urllib.request.Request(gateway_url + "/agent/join", method="POST",
                                 data=json.dumps({"code": code, "name": name}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=20) as r:
            ans = json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = (e.read() or b"").decode(errors="replace")
        if e.code == 403:
            raise SystemExit("the gateway refused the code. Agent codes last an hour and work once: ask the gateway "
                             "operator for a new one (`mhp gateway pair-agent` there) and retry.") from None
        raise SystemExit(f"the gateway answered {e.code}: {detail[:200]}") from None
    except OSError as e:
        raise SystemExit(f"could not talk to {gateway_url}: {e}") from None
    cfg = {"gateway": gateway_url, "directory": ans.get("directory") or gateway_url + "/directory/",
           "token": ans["agent_token"], "name": ans.get("name", name), "pin": str(PIN_FILE),
           "fingerprint": fp, "joined": time.strftime("%Y-%m-%dT%H:%M:%S")}
    save_agent_config(cfg)
    return cfg


def leave() -> int:
    cfg = load_agent_config()
    if cfg is None:
        say("this machine is not paired with a gateway.")
        return 1
    AGENT_FILE.unlink()
    if PIN_FILE.is_file():
        PIN_FILE.unlink()
    say(f"forgot gateway {cfg['gateway']} (was '{cfg['name']}'). The operator revokes the token with "
        f"`mhp gateway remove-agent {cfg['name']}`.")
    return 0


def access(url: str) -> tuple[str | None, ssl.SSLContext | None]:
    """The token and the TLS context to use for ``url``, when it is on the gateway this machine joined.
    (None, None) for any other URL, so the pin and the token are never offered elsewhere."""
    cfg = load_agent_config()
    if not cfg:
        return None, None
    gw = cfg.get("gateway", "").rstrip("/")
    if not gw or not (url == gw or url.startswith(gw + "/")):
        return None, None
    return cfg.get("token"), ssl_context(cfg.get("pin"))


def status() -> int:
    cfg = load_agent_config()
    if cfg is None:
        say("not paired with a gateway. Ask the operator for a code (`mhp gateway pair-agent` there), then:",
            "  mhp agent --join https://<gateway> <code>")
        return 1
    say(f"gateway {cfg['gateway']}   paired as '{cfg['name']}' on {cfg.get('joined', '?')}",
        f"directory {cfg['directory']}", f"certificate pinned: {cfg.get('fingerprint', '?')}   ({cfg.get('pin')})", f"settings: {AGENT_FILE}")
    token, ctx = access(cfg["gateway"])
    req = urllib.request.Request(cfg["gateway"] + "/", headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=8) as r:
            doc = json.loads(r.read())
        devs = doc.get("devices", [])
        say(f"gateway answers; {len(devs)} device(s) reachable" + (": " + ", ".join(devs[:6]) + (", ..." if len(devs) > 6 else "") if devs else ""))
        say("", "agents on this machine use it with:  mhp-mcp        (the directory is taken from agent.json)")
        return 0
    except urllib.error.HTTPError as e:
        if e.code == 401:
            say("the gateway no longer accepts this machine's token (removed there?). Pair again with a new code.")
        else:
            say(f"the gateway answered {e.code}")
        return 1
    except OSError as e:
        say(f"cannot reach the gateway ({e}). Is `mhp gateway serve` running there?")
        return 1


def main(verb: str | None, args: list[str], *, join_args: list[str] | None = None, name: str | None = None) -> int:
    if join_args:
        try:
            cfg = join(join_args[0], join_args[1], name=name)
        except SystemExit as e:
            say(f"COULD NOT JOIN THE GATEWAY: {e}")
            return 1
        say(f"paired with {cfg['gateway']} as '{cfg['name']}'; saved to {AGENT_FILE}", "",
            "agents on this machine now reach every instrument behind it:  mhp-mcp",
            f"  (or by hand:  mhp {cfg['directory']} find <what you need>)")
        return 0
    if verb in (None, "status"):
        return status()
    if verb == "leave":
        return leave()
    say(f"unknown agent command {verb!r}. One of: --join <gateway url> <code>, status, leave")
    return 2
