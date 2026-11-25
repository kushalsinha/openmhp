"""Install `mhp node` as a background service, so a lab bench PC keeps serving its
instruments across reboots without a terminal staying open.

    mhp node ~/instruments --http 18900 --install-service
    mhp node --service-status
    mhp node --uninstall-service

Linux:   a systemd `--user` unit, enabled now and at login. Needs `systemctl` and a
         user session that lingers (`loginctl enable-linger $USER` if the bench PC
         is headless and nobody stays logged in).
Windows: started now, hidden (pythonw, no console window), and again at every login from a batch file in
         the current user's Startup folder. Needs no admin rights. It is not a Windows Service in the formal
         sense: it runs in the signed-in user's session, which is also where instrument software such as
         UNICORN, Empower and FloZF runs. A PC that restarts to the sign-in screen serves again once someone
         signs in (or set Windows to sign in automatically).
macOS:   a LaunchAgent, loaded now and at every login.

Every function that generates a service definition is pure (given the same
arguments, the same text back), so it is tested without touching the real OS.
Only `install`/`uninstall`/`status` actually call out to systemctl/launchctl or
touch the filesystem, and each reports what it did rather than raising, since a
lab bench PC is exactly the kind of machine where a stack trace helps no one.
"""
from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path

LABEL = "openmhp-node"


def record_path() -> Path:
    """Which Python and folder the installed service runs, so status can say how to update THAT install."""
    return Path(os.environ.get("OPENMHP_HOME", Path.home() / ".openmhp")).expanduser() / "node-service.json"


def installed_record() -> dict | None:
    try:
        return json.loads(record_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


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


def windowless(argv: list[str]) -> list[str]:
    """On Windows, the same command under pythonw.exe: no console window to close by mistake. Its output goes to
    ~/.openmhp/<name>.log (cli.main sends it there when there is no console)."""
    exe = Path(argv[0])
    if exe.name.lower() == "python.exe" and exe.with_name("pythonw.exe").is_file():
        return [str(exe.with_name("pythonw.exe")), *argv[1:]]
    return list(argv)


def _bat(argv: list[str]) -> str:
    quoted = " ".join(f'"{a}"' if " " in a else a for a in argv)
    return f'@echo off\r\nstart "" {quoted}\r\n'


def windows_startup_script(packages_dir: str | Path, http_base: int) -> str:
    return _bat(windowless(_command(packages_dir, http_base)))


# ---- paths --------------------------------------------------------------------------------
def _systemd_unit_path(label: str = LABEL) -> Path:
    return Path.home() / ".config" / "systemd" / "user" / f"{label}.service"


def _launchd_plist_path(label: str = LABEL) -> Path:
    short = "node" if label == LABEL else label.removeprefix("openmhp-")
    return Path.home() / "Library" / "LaunchAgents" / f"com.openmhp.{short}.plist"


def _windows_startup_path(label: str = LABEL) -> Path:
    import os
    startup = os.environ.get("APPDATA")
    base = Path(startup) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" if startup else Path.home()
    return base / f"{label}.bat"


def manager_off() -> bool:
    """OPENMHP_SERVICE_MANAGER=none: write service files under OPENMHP_HOME and never call systemctl, launchctl or
    the Startup folder. For tests and dry environments: nothing is installed on the machine they run on."""
    return os.environ.get("OPENMHP_SERVICE_MANAGER", "").lower() == "none"


def _manage(cmd: list[str], **kw):
    """Every call to the OS service manager goes through here, so `manager_off()` stops all of them."""
    if manager_off():
        import types
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")
    return subprocess.run(cmd, **kw)


def target_path(label: str = LABEL) -> Path:
    if manager_off():
        home = Path(os.environ.get("OPENMHP_HOME", Path.home() / ".openmhp")).expanduser()
        return home / "services" / f"{label}.service"
    system = platform.system()
    if system == "Linux":
        return _systemd_unit_path(label)
    if system == "Darwin":
        return _launchd_plist_path(label)
    if system == "Windows":
        return _windows_startup_path(label)
    raise NotImplementedError(f"no service integration for {system!r} yet; run the command in a terminal that stays open")


def _content(label: str, argv: list[str], description: str) -> str:
    """Service definition for any long-running `python -m openmhp.cli ...` command, per OS."""
    system = platform.system()
    cmd = " ".join(argv)
    if system == "Linux":
        return ("[Unit]\n" f"Description={description}\n" "After=network-online.target\n\n"
                "[Service]\n" f"ExecStart={cmd}\n" "Restart=on-failure\nRestartSec=3\n\n" "[Install]\nWantedBy=default.target\n")
    if system == "Darwin":
        short = "node" if label == LABEL else label.removeprefix("openmhp-")
        log = Path.home() / ".openmhp" / f"{short}.log"
        args = "".join(f"      <string>{a}</string>\n" for a in argv)
        return ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
                '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n<plist version="1.0">\n<dict>\n'
                f"  <key>Label</key><string>com.openmhp.{short}</string>\n  <key>ProgramArguments</key>\n  <array>\n{args}  </array>\n"
                "  <key>RunAtLoad</key><true/>\n  <key>KeepAlive</key><true/>\n"
                f"  <key>StandardOutPath</key><string>{log}</string>\n  <key>StandardErrorPath</key><string>{log}</string>\n"
                "</dict>\n</plist>\n")
    if system == "Windows":
        return _bat(windowless(argv))
    raise NotImplementedError(f"no service integration for {system!r} yet; run the command in a terminal that stays open")


_VERBS = {LABEL: ("node",), "openmhp-gateway": ("gateway", "serve"), "openmhp-watch": ("agent", "watch")}


def _verb(label: str) -> tuple[str, ...]:
    return _VERBS.get(label, ())


def start_windows(argv: list[str], label: str = LABEL) -> dict:
    """Windows has no service manager here: stop the copy that runs now, if any, then start this command
    detached and windowless, so it outlives the terminal that installed it. The Startup file starts it at login."""
    steps = []
    if manager_off():
        return {"ok": True, "steps": ["(service manager off: not started)"]}
    for pid, _ in _servers(label):
        steps.append(f"stopped the running copy (pid {pid})" if stop_process(pid) else f"could not stop pid {pid}")
    flags = sum(getattr(subprocess, f, 0) for f in ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP", "CREATE_NO_WINDOW"))
    try:
        p = subprocess.Popen(windowless(argv), creationflags=flags, close_fds=True, cwd=str(Path.home()),
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        return {"ok": False, "steps": steps, "error": f"could not start it: {type(e).__name__}: {e}"}
    steps.append(f"started in the background (pid {p.pid})")
    return {"ok": True, "steps": steps, "pid": p.pid}


def install_command(label: str, argv: list[str], description: str, dry_run: bool = False) -> dict:
    """Install any openmhp command as a login/boot service. Never raises."""
    system = platform.system()
    result = {"system": system, "dry_run": dry_run, "ok": True, "steps": []}
    try:
        path = target_path(label)
        text = _content(label, argv, description)
    except NotImplementedError as e:
        return {**result, "ok": False, "error": str(e), "path": "", "content": ""}
    result.update(path=str(path), content=text, command=" ".join(argv))
    if dry_run:
        result["note"] = "dry run: nothing was written or enabled"
        return result
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        result["steps"].append(f"wrote {path}")
        if system == "Linux":
            for cmd in (["systemctl", "--user", "daemon-reload"], ["systemctl", "--user", "enable", "--now", f"{label}.service"]):
                r = _manage(cmd, capture_output=True, text=True)
                result["steps"].append(f"{' '.join(cmd)}: {'ok' if r.returncode == 0 else r.stderr.strip()[:200]}")
                if r.returncode != 0:
                    result["ok"] = False
            if result["ok"]:
                result["note"] = ("running now, and at every login. On a headless machine where nobody stays logged in, "
                                  "also run: loginctl enable-linger $USER")
        elif system == "Darwin":
            r = _manage(["launchctl", "load", "-w", str(path)], capture_output=True, text=True)
            result["steps"].append(f"launchctl load -w: {'ok' if r.returncode == 0 else r.stderr.strip()[:200]}")
            result["ok"] = r.returncode == 0
            if result["ok"]:
                result["note"] = "running now, and at every login."
        elif system == "Windows":
            s = start_windows(argv, label)
            result["steps"] += s["steps"]
            result["ok"] = s["ok"]
            if not s["ok"]:
                result["error"] = s.get("error")
            result["note"] = "running now in the background, and again at every login."
    except OSError as e:
        result["ok"] = False
        result["error"] = f"{type(e).__name__}: {e}"
    return result


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
        # no explicit encoding on purpose: systemd and launchd read UTF-8, the locale's encoding on Linux and macOS,
        # but cmd.exe reads a .bat file in the console code page, so forcing UTF-8 would garble non-ASCII paths
        path.write_text(text)
        result["steps"].append(f"wrote {path}")
        if system == "Linux":
            for cmd in (["systemctl", "--user", "daemon-reload"], ["systemctl", "--user", "enable", "--now", f"{LABEL}.service"]):
                r = _manage(cmd, capture_output=True, text=True)
                result["steps"].append(f"{' '.join(cmd)}: {'ok' if r.returncode == 0 else r.stderr.strip()[:200]}")
                if r.returncode != 0:
                    result["ok"] = False
            if result["ok"]:
                result["note"] = ("running now, and at every login. On a headless bench PC where nobody stays logged "
                                  "in, also run: loginctl enable-linger $USER")
        elif system == "Darwin":
            r = _manage(["launchctl", "load", "-w", str(path)], capture_output=True, text=True)
            result["steps"].append(f"launchctl load -w: {'ok' if r.returncode == 0 else r.stderr.strip()[:200]}")
            result["ok"] = r.returncode == 0
            if result["ok"]:
                result["note"] = "running now, and at every login."
        elif system == "Windows":
            s = start_windows(_command(packages_dir, http_base))
            result["steps"] += s["steps"]
            result["ok"] = s["ok"]
            if s["ok"]:
                result["note"] = "running now in the background, and again at every login."
            else:
                result["error"] = s.get("error")
        result["command"] = " ".join(_command(packages_dir, http_base))
        record_path().parent.mkdir(parents=True, exist_ok=True)
        record_path().write_text(json.dumps({"python": sys.executable, "folder": str(Path(packages_dir).resolve()),
                                             "http": http_base}), encoding="utf-8")
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
            _manage(["systemctl", "--user", "disable", "--now", f"{LABEL}.service"], capture_output=True, text=True)
            result["steps"].append("systemctl --user disable --now")
        elif system == "Darwin" and path.is_file():
            _manage(["launchctl", "unload", str(path)], capture_output=True, text=True)
            result["steps"].append("launchctl unload")
        elif system == "Windows" and path.is_file() and not manager_off():
            for pid, _ in _servers(LABEL):
                result["steps"].append(f"stopped pid {pid}" if stop_process(pid) else f"could not stop pid {pid}")
        if path.is_file():
            path.unlink()
        if record_path().is_file():
            record_path().unlink()
            result["steps"].append(f"removed {path}")
        else:
            result["steps"].append(f"nothing installed at {path}")
    except OSError as e:
        result["ok"] = False
        result["error"] = f"{type(e).__name__}: {e}"
    return result


def restart(packages_dir: str | Path, http_base: int) -> dict:
    """Re-install the service so a running node picks up new packages: uninstall, then install."""
    u = uninstall()
    r = install(packages_dir, http_base)
    r["steps"] = u.get("steps", []) + r.get("steps", [])
    if not u.get("ok"):
        r["ok"] = False
        r["error"] = u.get("error")
    return r


def status() -> dict:
    system = platform.system()
    path = target_path()
    installed = path.is_file()
    result = {"system": system, "path": str(path), "installed": installed, "running": None}
    if not installed:
        return result
    try:
        if system == "Linux":
            r = _manage(["systemctl", "--user", "is-active", f"{LABEL}.service"], capture_output=True, text=True)
            result["running"] = r.stdout.strip() == "active"
        elif system == "Darwin":
            r = _manage(["launchctl", "list", "com.openmhp.node"], capture_output=True, text=True)
            result["running"] = r.returncode == 0
        elif system == "Windows":
            result["running"] = bool(_servers(LABEL)) if not manager_off() else None
            result["note"] = "runs in the background now and starts again at every login"
    except FileNotFoundError:
        result["running"] = None
        result["note"] = "installed but the OS service manager isn't on PATH to check"
    return result


# ---- any service by label (the gateway, the watcher): restart, what it runs, stray copies ------------------
def _short(label: str) -> str:
    return "node" if label == LABEL else label.removeprefix("openmhp-")


def service_python(label: str = LABEL) -> str | None:
    """The Python an installed service starts: the first word of its command. None when not installed."""
    try:
        text = target_path(label).read_text(encoding="utf-8", errors="replace")
    except (OSError, NotImplementedError):
        return None
    import re as _re
    m = (_re.search(r"^ExecStart=(\S+)", text, _re.M) or _re.search(r"<array>\s*<string>([^<]+)</string>", text)
         or _re.search(r'start ""\s+(?:/min\s+)?(?:"([^"]+)"|(\S+))', text))
    exe = next((g for g in m.groups() if g), None) if m else None
    if exe and exe.lower().endswith("pythonw.exe"):          # the windowless twin; python.exe prints the version
        exe = exe[:-len("pythonw.exe")] + "python.exe"
    return exe


def openmhp_version_of(python: str | None) -> str | None:
    """The OpenMHP a given Python imports (isolated, so the current folder cannot shadow it)."""
    if not python:
        return None
    try:
        r = subprocess.run([python, "-I", "-c", "import openmhp;print(openmhp.__version__)"],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def service_state(label: str = LABEL) -> dict:
    """installed, running (True, False or None when the OS cannot say), main_pid, python."""
    system = platform.system()
    try:
        path = target_path(label)
    except NotImplementedError:
        return {"installed": False, "running": None, "path": "", "main_pid": None, "python": None}
    out = {"installed": path.is_file(), "running": None, "path": str(path), "main_pid": None, "python": service_python(label)}
    if not out["installed"]:
        return out
    try:
        if system == "Linux":
            r = _manage(["systemctl", "--user", "show", "-p", "ActiveState", "-p", "MainPID", f"{label}.service"],
                               capture_output=True, text=True, timeout=10)
            kv = dict(line.split("=", 1) for line in r.stdout.splitlines() if "=" in line)
            out["running"] = kv.get("ActiveState") == "active"
            out["main_pid"] = int(kv.get("MainPID") or 0) or None
        elif system == "Darwin":
            r = _manage(["launchctl", "list", f"com.openmhp.{_short(label)}"], capture_output=True, text=True, timeout=10)
            import re as _re
            m = _re.search(r'"PID"\s*=\s*(\d+)', r.stdout)
            out["main_pid"] = int(m.group(1)) if m else None
            out["running"] = out["main_pid"] is not None
        elif system == "Windows" and _verb(label) and not manager_off():
            procs = _servers(label)
            out["running"] = bool(procs)
            out["main_pid"] = procs[0][0] if procs else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        pass
    return out


def restart_service(label: str = LABEL) -> dict:
    """Restart an installed service through the OS's own manager. Windows has none: the Startup file is run again."""
    system = platform.system()
    path = target_path(label)
    if not path.is_file():
        return {"ok": False, "steps": [], "error": f"no service installed ({path})"}
    try:
        if system == "Linux":
            cmd = ["systemctl", "--user", "restart", f"{label}.service"]
        elif system == "Darwin":
            cmd = ["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/com.openmhp.{_short(label)}"]
        elif system == "Windows":
            argv = _bat_argv(path.read_text(errors="replace"))
            if not argv:
                return {"ok": False, "steps": [], "error": f"cannot read the command in {path}"}
            s = start_windows(argv, label)
            return {"ok": s["ok"], "steps": s["steps"], "error": s.get("error")}
        else:
            return {"ok": False, "steps": [], "error": f"no service integration for {system!r}"}
        r = _manage(cmd, capture_output=True, text=True, timeout=60)
        return {"ok": r.returncode == 0, "steps": [" ".join(cmd) + (": ok" if r.returncode == 0 else f": {r.stderr.strip()[:200]}")],
                "error": None if r.returncode == 0 else (r.stderr.strip()[:200] or f"exit {r.returncode}")}
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "steps": [], "error": f"{type(e).__name__}: {e}"}


def _split_windows(cmd: str) -> list[str]:
    """A Windows command line as words, keeping quoted paths with spaces ("C:\\Program Files\\...") whole."""
    import shlex
    try:
        return shlex.split(cmd.replace("\\", "\\\\"), posix=True)
    except ValueError:
        return [w.strip('"') for w in cmd.split()]


def _servers(label: str) -> list[tuple[int, str]]:
    """Running copies of what this service serves. `mhp node add`, `setup` and the service flags are a person at
    the keyboard, not the server, and are left alone."""
    busy = re.compile(r"\bnode\s+(add|setup)\b|--(uninstall-service|service-status|check)\b")
    return [(pid, cmd) for pid, cmd in find_processes(_verb(label)) if not busy.search(cmd)] if _verb(label) else []


def _bat_argv(text: str) -> list[str]:
    """The command a Startup batch file starts: `start "" [/min] "C:\\...\\pythonw.exe" -m openmhp.cli ...`."""
    import shlex
    for line in text.splitlines():
        line = line.strip()
        if line.lower().startswith("start "):
            rest = re.sub(r'^start\s+""\s+(?:/min\s+)?', "", line, flags=re.I)
            try:
                return shlex.split(rest.replace("\\", "\\\\"), posix=True)
            except ValueError:
                return []
    return []


def is_openmhp_command(words: list[str], verb: tuple[str, ...]) -> bool:
    """True when the program itself is `mhp <verb...>`, `python [-flags] <path>/mhp <verb...>` or
    `python [-flags] -m openmhp.cli <verb...>`. Never a shell or grep whose arguments merely mention it
    (macOS joins a process's arguments into one line, so `zsh -c "... mhp gateway serve"` must not match)."""
    from pathlib import PureWindowsPath                    # splits on / and \ alike, whatever this OS is
    name = lambda w: PureWindowsPath(w).name.lower()
    n = len(verb)
    i = 0
    if words and re.match(r"(pythonw?[\d.]*|pyw?)(\.exe)?$", name(words[0])):
        i = 1
        while i < len(words) and words[i].startswith("-") and words[i] != "-m":
            i += 1                                         # interpreter flags such as -I or -u
        if i < len(words) and words[i] == "-m":
            if i + 1 >= len(words) or words[i + 1] != "openmhp.cli":
                return False
            i += 2
        elif i < len(words) and name(words[i]) in ("mhp", "mhp.exe", "mhp-script.py"):
            i += 1
        else:
            return False
    elif words and name(words[0]) in ("mhp", "mhp.exe"):
        i = 1
    else:
        return False
    return tuple(words[i:i + n]) == verb


def find_processes(verb: tuple[str, ...]) -> list[tuple[int, str]]:
    """This user's processes running `mhp <verb...>`: (pid, command line). Empty where the OS will not say."""
    system, found, me = platform.system(), [], os.getpid()
    try:
        if system == "Linux":
            uid = os.getuid()
            for d in Path("/proc").iterdir():
                if not d.name.isdigit() or int(d.name) == me:
                    continue
                try:
                    if d.stat().st_uid != uid:
                        continue
                    words = [w for w in (d / "cmdline").read_bytes().decode(errors="replace").split("\0") if w]
                except OSError:
                    continue
                if is_openmhp_command(words, verb):
                    found.append((int(d.name), " ".join(words)))
        elif system == "Darwin":
            r = subprocess.run(["ps", "-U", str(os.getuid()), "-o", "pid=,command="], capture_output=True, text=True, timeout=10)
            for line in r.stdout.splitlines():
                pid, _, cmd = line.strip().partition(" ")
                if pid.isdigit() and int(pid) != me and is_openmhp_command(cmd.split(), verb):
                    found.append((int(pid), cmd.strip()))
        elif system == "Windows":
            ps = ("Get-CimInstance Win32_Process | ForEach-Object { \"$($_.ProcessId)`t$($_.CommandLine)\" }")
            r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=30)
            for line in r.stdout.splitlines():
                pid, _, cmd = line.partition("\t")
                words = _split_windows(cmd)
                if pid.strip().isdigit() and int(pid) != me and is_openmhp_command(words, verb):
                    found.append((int(pid), cmd.strip()))
    except (OSError, subprocess.TimeoutExpired):
        pass
    return found


def stop_process(pid: int, wait_s: float = 8.0) -> bool:
    """Ask a process to stop, then insist. True once it is gone."""
    import signal
    import time as _t
    if platform.system() == "Windows":
        r = subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, text=True)
        return r.returncode == 0
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    end = _t.time() + wait_s
    while _t.time() < end:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        _t.sleep(0.2)
    try:
        os.kill(pid, signal.SIGKILL)
        _t.sleep(0.5)
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False
