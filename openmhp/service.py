"""Install `mhp node` as a background service, so a lab bench PC keeps serving its
instruments across reboots without a terminal staying open.

    mhp node ~/instruments --http 18900 --install-service
    mhp node --service-status
    mhp node --uninstall-service

Linux:   a systemd `--user` unit, enabled now and at login. Needs `systemctl` and a
         user session that lingers (`loginctl enable-linger $USER` if the bench PC
         is headless and nobody stays logged in).
Windows: a batch file in the current user's Startup folder. Any file there runs
         automatically at login; this is not a Windows Service in the formal
         sense, so it only starts once someone logs in, and needs no admin rights.
macOS:   a LaunchAgent, loaded now and at every login.

Every function that generates a service definition is pure (given the same
arguments, the same text back), so it is tested without touching the real OS.
Only `install`/`uninstall`/`status` actually call out to systemctl/launchctl or
touch the filesystem, and each reports what it did rather than raising, since a
lab bench PC is exactly the kind of machine where a stack trace helps no one.
"""
from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path

LABEL = "openmhp-node"


def _command(packages_dir: str | Path, http_base: int) -> list[str]:
    return [sys.executable, "-m", "openmhp.cli", "node", str(Path(packages_dir).resolve()), "--http", str(http_base)]


# ---- pure content generators, one per OS -------------------------------------------------
def systemd_unit(packages_dir: str | Path, http_base: int) -> str:
    cmd = " ".join(_command(packages_dir, http_base))
    return (
        "[Unit]\n"
        f"Description=OpenMHP node: serves device packages under {Path(packages_dir).resolve()}\n"
        "After=network-online.target\n\n"
        "[Service]\n"
        f"ExecStart={cmd}\n"
        "Restart=on-failure\n"
        "RestartSec=3\n\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def launchd_plist(packages_dir: str | Path, http_base: int, log_path: Path) -> str:
    args = _command(packages_dir, http_base)
    entries = "".join(f"        <string>{a}</string>\n" for a in args)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0"><dict>\n'
        "    <key>Label</key><string>com.openmhp.node</string>\n"
        "    <key>ProgramArguments</key><array>\n" + entries + "    </array>\n"
        "    <key>RunAtLoad</key><true/>\n"
        "    <key>KeepAlive</key><true/>\n"
        f"    <key>StandardOutPath</key><string>{log_path}</string>\n"
        f"    <key>StandardErrorPath</key><string>{log_path}</string>\n"
        "</dict></plist>\n"
    )


def windows_startup_script(packages_dir: str | Path, http_base: int) -> str:
    args = _command(packages_dir, http_base)
    quoted = " ".join(f'"{a}"' if " " in a else a for a in args)
    return f'@echo off\r\nstart "" /min {quoted}\r\n'


# ---- paths --------------------------------------------------------------------------------
def _systemd_unit_path() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / f"{LABEL}.service"


def _launchd_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / "com.openmhp.node.plist"


def _windows_startup_path() -> Path:
    import os
    startup = os.environ.get("APPDATA")
    base = Path(startup) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" if startup else Path.home()
    return base / f"{LABEL}.bat"


def target_path() -> Path:
    system = platform.system()
    if system == "Linux":
        return _systemd_unit_path()
    if system == "Darwin":
        return _launchd_plist_path()
    if system == "Windows":
        return _windows_startup_path()
    raise NotImplementedError(f"no service integration for {system!r} yet; run `mhp node` in a terminal that stays open")


def content_for(packages_dir: str | Path, http_base: int) -> str:
    system = platform.system()
    if system == "Linux":
        return systemd_unit(packages_dir, http_base)
    if system == "Darwin":
        return launchd_plist(packages_dir, http_base, Path.home() / ".openmhp" / "node.log")
    if system == "Windows":
        return windows_startup_script(packages_dir, http_base)
    raise NotImplementedError(f"no service integration for {system!r} yet; run `mhp node` in a terminal that stays open")


# ---- install / uninstall / status: the only functions that touch the real OS -------------
def install(packages_dir: str | Path, http_base: int, dry_run: bool = False) -> dict:
    """Write the service definition and (unless dry_run) enable and start it. Never raises;
    a lab bench PC is exactly the machine where a stack trace helps no one."""
    system = platform.system()
    path = target_path()
    text = content_for(packages_dir, http_base)
    result = {"system": system, "path": str(path), "content": text, "dry_run": dry_run, "ok": True, "steps": []}
    if dry_run:
        result["note"] = "dry run: nothing was written or enabled"
        return result
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        result["steps"].append(f"wrote {path}")
        if system == "Linux":
            for cmd in (["systemctl", "--user", "daemon-reload"], ["systemctl", "--user", "enable", "--now", f"{LABEL}.service"]):
                r = subprocess.run(cmd, capture_output=True, text=True)
                result["steps"].append(f"{' '.join(cmd)}: {'ok' if r.returncode == 0 else r.stderr.strip()[:200]}")
                if r.returncode != 0:
                    result["ok"] = False
            if result["ok"]:
                result["note"] = ("running now, and at every login. On a headless bench PC where nobody stays logged "
                                  "in, also run: loginctl enable-linger $USER")
        elif system == "Darwin":
            r = subprocess.run(["launchctl", "load", "-w", str(path)], capture_output=True, text=True)
            result["steps"].append(f"launchctl load -w: {'ok' if r.returncode == 0 else r.stderr.strip()[:200]}")
            result["ok"] = r.returncode == 0
            if result["ok"]:
                result["note"] = "running now, and at every login."
        elif system == "Windows":
            result["note"] = "will start at the next login. To start it now too, run the file it just wrote."
        result["command"] = " ".join(_command(packages_dir, http_base))
    except OSError as e:
        result["ok"] = False
        result["error"] = f"{type(e).__name__}: {e}"
    return result


def uninstall() -> dict:
    system = platform.system()
    path = target_path()
    result = {"system": system, "path": str(path), "ok": True, "steps": []}
    try:
        if system == "Linux" and path.is_file():
            subprocess.run(["systemctl", "--user", "disable", "--now", f"{LABEL}.service"], capture_output=True, text=True)
            result["steps"].append("systemctl --user disable --now")
        elif system == "Darwin" and path.is_file():
            subprocess.run(["launchctl", "unload", str(path)], capture_output=True, text=True)
            result["steps"].append("launchctl unload")
        if path.is_file():
            path.unlink()
            result["steps"].append(f"removed {path}")
        else:
            result["steps"].append(f"nothing installed at {path}")
    except OSError as e:
        result["ok"] = False
        result["error"] = f"{type(e).__name__}: {e}"
    return result


def status() -> dict:
    system = platform.system()
    path = target_path()
    installed = path.is_file()
    result = {"system": system, "path": str(path), "installed": installed, "running": None}
    if not installed:
        return result
    try:
        if system == "Linux":
            r = subprocess.run(["systemctl", "--user", "is-active", f"{LABEL}.service"], capture_output=True, text=True)
            result["running"] = r.stdout.strip() == "active"
        elif system == "Darwin":
            r = subprocess.run(["launchctl", "list", "com.openmhp.node"], capture_output=True, text=True)
            result["running"] = r.returncode == 0
        elif system == "Windows":
            result["running"] = None
            result["note"] = "starts at next login; Windows has no simple way to check without admin tools"
    except FileNotFoundError:
        result["running"] = None
        result["note"] = "installed but the OS service manager isn't on PATH to check"
    return result
