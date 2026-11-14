"""SSH access to a gateway for scientists' machines: keys, forced commands, and the sshd settings.

A scientist's machine reaches the gateway over SSH for two things only: the `mhp-gw` verbs and file
copies inside that scientist's own folder (see gw_shell). Nobody pastes keys by hand. `mhp agent
--join` sends the machine's public key with the pairing code; the gateway keeps it in the scientist's
profile; sshd asks the gateway for it at each login through AuthorizedKeysCommand, and every key comes
back bound to a forced command naming its scientist.

Two modes, set with `mhp gateway ssh`:

    single   every scientist logs in as one account (default `mhp`); the key decides who they are
    users    every scientist has their own Linux user `mhp-<name>` owning their folder (needs root)

    sudo mhp gateway ssh apply          writes the sshd snippet and the key helper; then reload sshd
"""
from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path

from . import scientists as S

KEY = re.compile(r"^(ssh-ed25519|sk-ssh-ed25519@openssh\.com|ecdsa-sha2-nistp(?:256|384|521)|"
                 r"sk-ecdsa-sha2-nistp256@openssh\.com|ssh-rsa) ([A-Za-z0-9+/]{40,}={0,3})(?: [^\r\n]*)?$")
USER_PREFIX = "mhp-"
SNIPPET_PATH = Path("/etc/ssh/sshd_config.d/openmhp.conf")
HELPER_PATH = Path("/usr/local/libexec/openmhp-keys")
HOST_KEYS = ("/etc/ssh/ssh_host_ed25519_key.pub", "/etc/ssh/ssh_host_ecdsa_key.pub", "/etc/ssh/ssh_host_rsa_key.pub")


def check_key(key: str) -> str:
    """A public key as `type base64`, its comment dropped. Anything else (options, two keys, a private key)
    is refused, so nothing a scientist sends can add options to the line sshd reads."""
    m = KEY.match((key or "").strip())
    if not m or "\n" in key.strip():
        raise ValueError("that is not one SSH public key (expected a line like 'ssh-ed25519 AAAA... comment')")
    return f"{m.group(1)} {m.group(2)}"


def login_for(name: str, cfg: dict) -> str:
    return USER_PREFIX + S.check_name(name) if cfg.get("mode") == "users" else cfg.get("login", "mhp")


def forced_command(name: str, cfg: dict) -> str:
    cmd = [cfg.get("python") or sys.executable, "-m", "openmhp.gw_shell", "--scientist", S.check_name(name),
           "--root", str(cfg.get("lab_root") or S.lab_root())]
    return " ".join(shlex.quote(c) for c in cmd)


def key_line(name: str, key: str, cfg: dict) -> str:
    cmd = forced_command(name, cfg).replace("\\", "\\\\").replace('"', '\\"')
    return f'command="{cmd}",restrict {check_key(key)} openmhp:{name}'


def keys_for(login: str, cfg: dict) -> list[str]:
    """The authorized_keys lines sshd should accept for `login`: every scientist's key in single mode,
    one scientist's in users mode, none for any other account."""
    root = Path(cfg.get("lab_root") or S.lab_root())
    if cfg.get("mode") == "users":
        if not login.startswith(USER_PREFIX):
            return []
        names = [login[len(USER_PREFIX):]]
    else:
        if login != cfg.get("login", "mhp"):
            return []
        names = S.names(root)
    out = []
    for name in names:
        try:
            prof = S.load_profile(name, root) or {}
            if prof.get("ssh_key"):
                out.append(key_line(name, prof["ssh_key"], cfg))
        except ValueError:
            continue                                   # a bad name or key never stops the others
    return out


def host_key(path: str | None = None) -> str | None:
    for p in ([path] if path else HOST_KEYS):
        try:
            return check_key(Path(p).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return None


def known_hosts_line(host: str, port: int, key: str) -> str:
    return (f"[{host}]:{port}" if port != 22 else host) + " " + check_key(key)


def sshd_snippet(cfg: dict) -> str:
    match = f"Match Group {cfg.get('group', 'mhp-scientists')}" if cfg.get("mode") == "users" else f"Match User {cfg.get('login', 'mhp')}"
    return "\n".join([
        "# OpenMHP gateway: scientists' machines may run mhp-gw and copy files in their own folder, nothing else.",
        "# Written by `mhp gateway ssh apply`. Keys come from the gateway, never from authorized_keys files.",
        match,
        "    AuthorizedKeysFile none",
        f"    AuthorizedKeysCommand {HELPER_PATH} %u",
        f"    AuthorizedKeysCommandUser {cfg.get('service_user', 'root')}",
        "    PasswordAuthentication no",
        "    KbdInteractiveAuthentication no",
        "    DisableForwarding yes",
        "    PermitTTY no",
        "",
    ])


def helper_script(cfg: dict) -> str:
    home = cfg.get("openmhp_home") or str(Path(os.environ.get("OPENMHP_HOME", "~/.openmhp")).expanduser())
    return "\n".join([
        "#!/bin/sh",
        "# sshd's AuthorizedKeysCommand for an OpenMHP gateway: prints the keys allowed for user $1.",
        f"OPENMHP_HOME={shlex.quote(home)} exec {shlex.quote(cfg.get('python') or sys.executable)} -m openmhp.ssh_access keys \"$1\"",
        "",
    ])


def system_user_plan(name: str, cfg: dict, *, user_exists=None, group_exists=None, service_group: str | None = None) -> list[list[str]]:
    """The commands that give scientist `name` their own Linux user owning their folder (users mode).
    Pure, so it is tested anywhere; `apply_system_user` runs it as root on the gateway.

    The folder is owned by mhp-<name> with the gateway service's group, mode 2770: the scientist and the
    gateway read and write it, other scientists cannot enter it. The run-ID counter at the lab root is
    shared with the scientists' group, since `mhp-gw open` runs as the scientist."""
    import grp
    import pwd

    def _user_exists(u):
        try:
            pwd.getpwnam(u)
            return True
        except KeyError:
            return False

    def _group_exists(g):
        try:
            grp.getgrnam(g)
            return True
        except KeyError:
            return False

    user_exists = user_exists or _user_exists
    group_exists = group_exists or _group_exists
    if service_group is None:
        service_group = grp.getgrgid(pwd.getpwnam(cfg["service_user"]).pw_gid).gr_name
    user, group = login_for(name, {**cfg, "mode": "users"}), cfg.get("group", "mhp-scientists")
    root = Path(cfg["lab_root"])
    home = S.folder(name, root)
    plan: list[list[str]] = []
    if not group_exists(group):
        plan.append(["groupadd", group])
    if not user_exists(user):
        plan.append(["useradd", "--home-dir", str(home), "--no-create-home", "--shell", "/bin/sh", "--gid", group,
                     "--comment", f"OpenMHP scientist {name}", user])
        plan.append(["usermod", "-p", "*", user])           # no password, but not locked: key logins still work
    plan += [["chown", "-R", f"{user}:{service_group}", str(home)],
             ["chmod", "2770", str(home)],
             ["chmod", "0755", str(root), str(root / "scientists")]]
    for f in ("run-ids.json", "run-ids.lock"):
        plan += [["touch", str(root / f)], ["chgrp", group, str(root / f)], ["chmod", "0664", str(root / f)]]
    return plan


def apply_system_user(name: str, cfg: dict) -> list[str]:
    """Run system_user_plan as root. Returns what was done; raises with the commands to run when not root."""
    import subprocess
    S.create(name, root=Path(cfg["lab_root"]))
    plan = system_user_plan(name, cfg)
    if not hasattr(os, "geteuid") or os.geteuid() != 0:
        raise PermissionError("creating a scientist's Linux user needs root. Run this with sudo, or run these once:\n  "
                              + "\n  ".join(" ".join(shlex.quote(c) for c in cmd) for cmd in plan))
    done = []
    for cmd in plan:
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"{' '.join(cmd)} failed: {(r.stderr or r.stdout).strip()[:300]}")
        done.append(" ".join(cmd))
    return done


def main(argv=None) -> int:
    """`python -m openmhp.ssh_access keys <user>`: what the helper runs. Prints nothing on any error, which
    sshd reads as "no keys", so a fault here locks scientists out rather than letting anyone in."""
    argv = sys.argv[1:] if argv is None else list(argv)
    if len(argv) != 2 or argv[0] != "keys":
        return 2
    try:
        from .gateway import load
        cfg = (load() or {}).get("ssh") or {}
        if not cfg:
            return 0
        for line in keys_for(argv[1], cfg):
            print(line)
    except Exception:                                  # noqa: BLE001
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
