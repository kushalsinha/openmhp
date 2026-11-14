"""`mhp agent`: the agent-machine half of gateway pairing (SPEC 9.2), the mirror of `mhp node --join`.

    mhp agent --join https://gw.office ab12-cd34     pair this machine once, with a code from `mhp gateway pair-agent`
    mhp agent                                        which gateway this machine is paired with, and whether it answers
    mhp agent leave                                  forget the gateway (the operator revokes with `mhp gateway remove-agent`)

When the gateway offers SSH access (`mhp gateway ssh` there), joining also sends this machine's own
SSH public key (made once, under ~/.openmhp/ssh) and pins the gateway's SSH host key, and adds one
`Include` line to ~/.ssh/config. From then on, plain commands reach the scientist's folder there:

    ssh mhp-gateway mhp-gw open                       a new run; returns its ID
    rsync -a ./my-skills/ mhp-gateway:runs/<id>/in/   hand over skills, scripts and data
    rsync -a mhp-gateway:runs/<id>/out/ ./results/    bring results home

Joining downloads the gateway's certificate, shows its fingerprint, exchanges the code for an agent
token over POST /agent/join and saves ~/.openmhp/agent.json. From then on the client, `mhp lab` and
`mhp-mcp` present that token to the gateway's URLs and trust exactly the pinned certificate, so no
environment variable and no certificate copy is needed on an agent machine. The token never passes
through the operator's hands: the code is what travels in chat, lasts an hour and works once.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from .relay import HOME, fetch_cert, fingerprint, ssl_context

AGENT_FILE = HOME / "agent.json"
PIN_FILE = HOME / "agent-gateway-pin.pem"
SSH_DIR = HOME / "ssh"
SSH_KEY = SSH_DIR / "id_ed25519"
SSH_CONFIG = SSH_DIR / "config"
SSH_KNOWN = SSH_DIR / "known_hosts"
SSH_ALIAS = "mhp-gateway"
INCLUDE_MARK = "# added by mhp agent --join; removed by mhp agent leave"


def user_ssh_config() -> Path:
    return Path(os.environ.get("OPENMHP_USER_SSH_CONFIG") or Path.home() / ".ssh" / "config")


def ensure_ssh_key(name: str) -> str | None:
    """This machine's key for the gateway, made once. None when there is no ssh-keygen (SSH is then skipped)."""
    pub = SSH_KEY.with_suffix(".pub")
    if not pub.is_file():
        keygen = shutil.which("ssh-keygen")
        if keygen is None:
            return None
        SSH_DIR.mkdir(parents=True, exist_ok=True)
        r = subprocess.run([keygen, "-q", "-t", "ed25519", "-N", "", "-C", f"openmhp-{name}", "-f", str(SSH_KEY)],
                           capture_output=True, text=True)
        if r.returncode != 0 or not pub.is_file():
            return None
    return pub.read_text(encoding="utf-8").strip()


def write_ssh_access(ssh: dict) -> None:
    """The host entry for `ssh mhp-gateway`, the pinned host key, and one Include line in ~/.ssh/config."""
    from .ssh_access import known_hosts_line
    SSH_DIR.mkdir(parents=True, exist_ok=True)
    SSH_KNOWN.write_text(known_hosts_line(ssh["host"], int(ssh.get("port", 22)), ssh["host_key"]) + "\n", encoding="utf-8")
    q = lambda p: '"' + str(p) + '"'
    SSH_CONFIG.write_text("\n".join([
        f"Host {SSH_ALIAS}",
        f"    HostName {ssh['host']}",
        f"    Port {int(ssh.get('port', 22))}",
        f"    User {ssh['login']}",
        f"    IdentityFile {q(SSH_KEY)}",
        "    IdentitiesOnly yes",
        f"    UserKnownHostsFile {q(SSH_KNOWN)}",
        "    StrictHostKeyChecking yes",
        "    RequestTTY no",
        "",
    ]), encoding="utf-8")
    uc = user_ssh_config()
    cur = uc.read_text(encoding="utf-8") if uc.is_file() else ""
    line = f'Include "{SSH_CONFIG}"'
    if line not in cur:
        uc.parent.mkdir(parents=True, exist_ok=True)
        uc.write_text(f"{INCLUDE_MARK}\n{line}\n\n" + cur, encoding="utf-8")      # Include must come before any Host block
        try:
            os.chmod(uc, 0o600)
        except OSError:
            pass


def remove_ssh_access() -> None:
    uc = user_ssh_config()
    if uc.is_file():
        lines = uc.read_text(encoding="utf-8").split("\n")
        keep = [l for l in lines if l != INCLUDE_MARK and l != f'Include "{SSH_CONFIG}"']
        if keep != lines:
            while keep and keep[0] == "":
                keep.pop(0)
            uc.write_text("\n".join(keep), encoding="utf-8")
    for f in (SSH_CONFIG, SSH_KNOWN):
        if f.is_file():
            f.unlink()


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
    ssh_key = ensure_ssh_key(name)
    req = urllib.request.Request(gateway_url + "/agent/join", method="POST",
                                 data=json.dumps({"code": code, "name": name, "ssh_key": ssh_key}).encode(),
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
    ssh = ans.get("ssh")
    if ssh and not ssh.get("error"):
        write_ssh_access(ssh)
        cfg["ssh"] = {"alias": SSH_ALIAS, "host": ssh["host"], "port": ssh.get("port", 22), "login": ssh["login"],
                      "scientist": ssh["scientist"]}
    elif ssh and ssh.get("error"):
        cfg["ssh_error"] = ssh["error"]
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
    remove_ssh_access()
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
    if cfg.get("ssh"):
        say(f"runs and files over SSH: ssh {SSH_ALIAS} mhp-gw help   (scientist '{cfg['ssh']['scientist']}', "
            f"{cfg['ssh']['login']}@{cfg['ssh']['host']}:{cfg['ssh']['port']})")
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
        if cfg.get("ssh"):
            say("", f"runs and files on the gateway, as scientist '{cfg['ssh']['scientist']}':",
                f"  ssh {SSH_ALIAS} mhp-gw help",
                f"  rsync -a <folder>/ {SSH_ALIAS}:runs/<run id>/in/",
                "", "to hear about your runs (questions, plans to approve, results) even when no agent is open, run once:",
                "  mhp agent watch --install-service")
        elif cfg.get("ssh_error"):
            say("", f"the gateway did not set up SSH for this machine: {cfg['ssh_error']}")
        from . import skills_install as SK
        installed = [p for d in (SK.harness_dirs() or [SK.HARNESS_DIRS["Claude Code"]]) for p in SK.install(d)]
        say("", f"installed the OpenMHP skills for the agents on this machine ({len(installed)} copies), including "
            "openmhp-lab-gateway, which teaches them to talk to the gateway for you in plain English.",
            "They load the next time an agent starts; new OpenMHP versions update them by themselves.")
        return 0
    if verb in (None, "status"):
        return status()
    if verb == "leave":
        return leave()
    if verb == "watch":
        from . import watcher
        return watcher.main(args)
    if verb == "inbox":
        from . import watcher
        items = watcher.unread()
        if not items:
            say("no unread news from the lab gateway")
            return 0
        for it in items:
            print(f"{it['at']}  {it['run']}  {it['kind']}: {it['text']}")
        if "--keep" not in args:
            watcher.mark_read(items)
        return 0
    say(f"unknown agent command {verb!r}. One of: --join <gateway url> <code>, status, leave, watch, inbox")
    return 2
