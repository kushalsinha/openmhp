"""`mhp agent watch`: the scientist's machine keeps one outbound connection to the gateway and hears about
their runs as things happen. A gateway cannot reach a laptop that sleeps or sits behind a firewall, so the
laptop listens instead, over the same SSH access pairing set up:

    ssh mhp-gateway mhp-gw watch --since <last news>      held open; reconnects after sleep or a dropped link

For each piece of news it leaves a note in ~/.openmhp/inbox/ and raises a desktop notification. When a run
ends it pulls the results with rsync into ~/openmhp-runs/<run id>/, checks every file against the run's
manifest, and acknowledges them, after which the gateway deletes its copy (it keeps them 7 days at most).

    mhp agent watch                       run in this window
    mhp agent watch --install-service     keep it running in the background, across reboots
    mhp agent inbox                       unread news (an agent reads this when the scientist asks)
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from .relay import HOME

INBOX = HOME / "inbox"
CURSOR = HOME / "watch-cursor.json"
ALIAS = "mhp-gateway"


def results_root() -> Path:
    return Path(os.environ.get("OPENMHP_RESULTS") or Path.home() / "openmhp-runs").expanduser()


def say(*lines: str) -> None:
    print("\n".join(lines), file=sys.stderr)


# ---- the inbox ----------------------------------------------------------------------------------
def note(run: str, kind: str, text: str, **extra) -> Path:
    INBOX.mkdir(parents=True, exist_ok=True)
    t = time.time()
    path = INBOX / f"{time.strftime('%Y%m%dT%H%M%S', time.localtime(t))}-{run}-{kind}-{int(t * 1000) % 1000:03d}.json"
    path.write_text(json.dumps({"run": run, "kind": kind, "text": text, "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                "read": False, **extra}, indent=1), encoding="utf-8")
    return path


def unread() -> list[dict]:
    out = []
    for p in sorted(INBOX.glob("*.json")) if INBOX.is_dir() else []:
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not doc.get("read"):
            out.append({**doc, "file": str(p)})
    return out


def mark_read(items: list[dict]) -> None:
    for it in items:
        p = Path(it["file"])
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
            doc["read"] = True
            p.write_text(json.dumps(doc, indent=1), encoding="utf-8")
        except (OSError, ValueError):
            pass


def notify(title: str, text: str) -> None:
    """A desktop notification where the OS offers one; silent otherwise. Never raises."""
    if os.environ.get("OPENMHP_NO_NOTIFY"):
        return
    try:
        system = platform.system()
        if system == "Darwin":
            esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')
            subprocess.run(["osascript", "-e", f'display notification "{esc(text)}" with title "{esc(title)}"'],
                           capture_output=True, timeout=10)
        elif system == "Linux" and shutil.which("notify-send"):
            subprocess.run(["notify-send", title, text], capture_output=True, timeout=10)
    except Exception:                                  # noqa: BLE001
        pass


# ---- results ------------------------------------------------------------------------------------
def verify(folder: Path) -> list[str]:
    """Files that do not match the manifest, or are missing; empty when everything arrived intact."""
    manifest = folder / "manifest.sha256"
    if not manifest.is_file():
        return ["manifest.sha256 is missing"]
    bad = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, _, name = line.partition("  ")
        f = folder / name
        if not f.is_file():
            bad.append(f"{name}: missing")
        elif hashlib.sha256(f.read_bytes()).hexdigest() != digest:
            bad.append(f"{name}: changed")
    return bad


class Watcher:
    def __init__(self, ssh: list[str] | None = None, host: str = ALIAS, results: Path | None = None):
        self.ssh = ssh or ["ssh"]                        # the ssh program and options; the host is separate
        self.host = host
        self.results = results or results_root()
        self.stop = threading.Event()

    def gw(self, *args: str, timeout: float = 120) -> tuple[int, dict]:
        p = subprocess.run([*self.ssh, self.host, "mhp-gw", *args], capture_output=True, text=True, timeout=timeout)
        try:
            return p.returncode, json.loads(p.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            return p.returncode, {"ok": False, "error": (p.stderr or p.stdout)[-500:]}

    def pull(self, run: str) -> dict:
        dest = self.results / run
        dest.mkdir(parents=True, exist_ok=True)
        rsh = " ".join(self.ssh)
        p = subprocess.run(["rsync", "-a", "-e", rsh, f"{self.host}:runs/{run}/out/", f"{dest}/"],
                           capture_output=True, text=True, timeout=3600)
        if p.returncode != 0:
            return {"ok": False, "error": (p.stderr or p.stdout)[-500:]}
        bad = verify(dest)
        if bad:
            return {"ok": False, "error": "results did not arrive intact: " + "; ".join(bad[:5]), "folder": str(dest)}
        code, ans = self.gw("ack", run)
        if code != 0:
            return {"ok": False, "folder": str(dest), "error": "the results are here and intact, but the gateway did not "
                    f"take the acknowledgement: {ans.get('error') or ans}"}
        return {"ok": True, "folder": str(dest), "ack": ans}

    def handle(self, ev: dict) -> None:
        kind, run = ev.get("kind"), ev.get("run", "?")
        if kind == "question":
            lab = " (someone needs to go to the lab)" if ev.get("needs_lab") else ""
            note(run, "question", f"{run} asks{lab}: {ev.get('question')}", question=ev.get("id"), needs_lab=ev.get("needs_lab"))
            notify(f"Lab run {run} has a question", ev.get("question", "")[:200])
        elif kind in ("charter_proposed", "charter_revised"):
            note(run, kind, f"{run}: a charter is ready to approve. Ask your agent to show it.", digest=ev.get("digest"))
            notify(f"Lab run {run}", "A plan is ready for your approval")
        elif kind == "state" and ev.get("state") == "running" and ev.get("previous") == "queued":
            note(run, "started", f"{run} has started.")
            notify(f"Lab run {run}", "Started")
        elif kind == "results_ready":
            got = self.pull(run)
            if got["ok"]:
                note(run, "results", f"{run} ended; its results are in {got['folder']}.", folder=got["folder"])
                notify(f"Lab run {run} ended", f"Results in {got['folder']}")
            else:
                note(run, "results_failed", f"{run} ended, but its results could not be brought home: {got['error']}. "
                     "The gateway keeps them for 7 days after the run ended.", error=got["error"])
                notify(f"Lab run {run} ended", "Results could not be downloaded yet")
        elif kind == "state" and ev.get("state") in ("failed", "interrupted"):
            note(run, ev["state"], f"{run} is {ev['state']}: {ev.get('why', '')}")
            notify(f"Lab run {run}", f"{ev['state']}: {ev.get('why', '')[:160]}")

    # ---- the long-lived stream -----------------------------------------------------------------
    def cursor(self) -> float:
        try:
            return float(json.loads(CURSOR.read_text(encoding="utf-8"))["since"])
        except (OSError, ValueError, KeyError):
            return 0.0

    def save_cursor(self, since: float) -> None:
        HOME.mkdir(parents=True, exist_ok=True)
        CURSOR.write_text(json.dumps({"since": since}), encoding="utf-8")

    def run_once(self, for_s: float | None = None) -> None:
        args = [*self.ssh, self.host, "mhp-gw", "watch", "--since", repr(self.cursor())]
        if for_s is not None:
            args += ["--for", str(for_s)]
        p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        try:
            for line in p.stdout:
                if self.stop.is_set():
                    break
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if ev.get("kind") != "heartbeat":
                    try:
                        self.handle(ev)
                    except Exception as e:                 # noqa: BLE001  one bad event must not stop the watch
                        say(f"watch: could not handle {ev.get('kind')}: {e}")
                    self.save_cursor(max(self.cursor(), float(ev.get("ts", 0))))
        finally:
            if p.poll() is None:
                p.terminate()
            p.wait(timeout=10)

    def forever(self) -> None:
        backoff = 1.0
        while not self.stop.is_set():
            started = time.time()
            try:
                self.run_once()
            except OSError as e:
                say(f"watch: {e}")
            if time.time() - started > 60:
                backoff = 1.0
            self.stop.wait(backoff)
            backoff = min(backoff * 2, 60)


def main(args: list[str]) -> int:
    if args and args[0] == "--install-service":
        from . import service as svc
        r = svc.install_command("openmhp-watch", [sys.executable, "-m", "openmhp.cli", "agent", "watch"],
                                "OpenMHP: news and results from your lab runs")
        for step in r.get("steps", []):
            say(f"  {step}")
        say(("installed. " + r.get("note", "")) if r["ok"] else f"FAILED: {r.get('error') or 'see above'}")
        return 0 if r["ok"] else 1
    say(f"watching your lab runs through {ALIAS}; news goes to {INBOX}, results to {results_root()}. Ctrl-C to stop.")
    try:                                   # a long-lived process on the scientist's machine: keep their skills current
        from .skills_install import notice as skills_notice
        if n := skills_notice():
            say(f"skills: {n}")
    except Exception as e:                 # noqa: BLE001  (never stop watching over a skill copy)
        say(f"skills: could not check for updates ({e})")
    try:
        Watcher().forever()
    except KeyboardInterrupt:
        pass
    return 0
