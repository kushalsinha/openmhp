"""Runs, the run log, and protocol planning.

A *run* is one execution of an orchestration script (mhp_run). Each run gets a
folder under ~/.openmhp/runs/<run-id>/ with script.py, stdout.txt, meta.json and
whatever files the script saves there (the script sees `run_dir`). Runs can
execute in the background. Each run has its own session: its leases are its own,
and they are released when the run ends.

Script output goes to the run only: scripts get a `print` bound to the run's
output file. Nothing redirects the process's stdout, which the MCP transport owns.

The *run log* is an append-only JSONL file per day under ~/.openmhp/log/, with a
sequence number that continues across restarts and each record chained to the one
before it, so an edit after the fact is detectable. Every call a direct tool or a
run script makes through the lab's clients is recorded, with the run id. The same
class keeps each instrument's own record under ~/.openmhp/records/<device>/, which
the driver writes whoever asked and over whatever transport (SPEC 3.5).

*Plan mode* executes a script against a PlanLab: reads are real, every write and
invoke is a dry run through the driver's gates, other mutating requests are
recorded but not executed, jobs complete instantly, time is virtual, and the
number of steps is bounded. A plan predicts one path through the script; loops
that wait on live readings cannot be predicted and are recorded as one step
(``wait_until``) or truncate the plan.
"""
from __future__ import annotations

import builtins
import collections
import hashlib
import json
import os
import re
import sys
import threading
import time
import traceback
import types
import uuid
import weakref
from pathlib import Path

from .client import Device, Lab, RemoteError, loaded_package_folders
from .driver import InterlockOpen

HOME = Path(os.environ.get("OPENMHP_HOME", Path.home() / ".openmhp"))
STDOUT_CAP = 8000                 # chars returned to the model
TAIL_CAP = 64_000                 # chars kept in memory per run
DISK_CAP = 10_000_000             # chars written to stdout.txt per run
RUN_ID = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")


# ------------------------------------------------------------------ run log ---- #
class RunLog:
    """Append-only JSONL, one file per day, with every record chained to the one before it.

    Each record carries ``prev``, the digest of the record before it, and ``hash``, its own.
    Both are recomputable from the line itself, so a changed value, a deleted line and a
    reordered pair each break the chain where they happened, and ``audit()`` says where.

    This is tamper-*evidence*, not tamper-proofing: whoever can write the file can rewrite the
    chain along with it, and signing the head is listed in SPEC 16 as unspecified. What it ends
    is a record that answered ``complete: true`` after a reading had been changed and a refusal
    deleted -- the state in which an edit left no trace at all. A record that failed to reach
    disk leaves the same break as a deleted one, which is the truth: the file is missing a line.
    """

    GENESIS = "0" * 32                               # what the first record of all follows

    def __init__(self, home: Path | None = None, subdir: str = "log"):
        self.dir = (home or HOME) / subdir
        self._lock = threading.Lock()
        self.recent: list[dict] = []                 # ring buffer for fast `since`
        self.write_errors = 0
        self.seq, self.head = self._tail_on_disk()

    def _files(self) -> list[Path]:
        return sorted(self.dir.glob("*.jsonl")) if self.dir.is_dir() else []

    @classmethod
    def digest(cls, ev: dict) -> str:
        """A record's own digest: every field of it except the digest, and except `persisted`,
        which is this process's note to itself and never reaches the file."""
        body = {k: v for k, v in ev.items() if k not in ("hash", "persisted")}
        return hashlib.sha256(json.dumps(body, sort_keys=True, default=str,
                                         separators=(",", ":")).encode("utf-8")).hexdigest()[:32]

    def _tail_on_disk(self) -> tuple[int, str]:
        """The sequence number and digest the next record has to follow."""
        for f in reversed(self._files()):
            try:
                lines = [l for l in f.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
            except OSError:
                continue
            for line in reversed(lines):
                try:
                    e = json.loads(line)
                    return int(e["seq"]), str(e.get("hash") or self.GENESIS)
                except (ValueError, KeyError, TypeError):
                    continue
        return 0, self.GENESIS

    def write(self, kind: str, **fields) -> dict:
        ev = {"ts": time.time(), "kind": kind, **fields}
        with self._lock:
            self.seq += 1
            ev["seq"], ev["prev"] = self.seq, self.head
            ev["hash"] = self.head = self.digest(ev)
            self.recent.append(ev)
            del self.recent[:-500]
            try:
                self.dir.mkdir(parents=True, exist_ok=True)
                with open(self.dir / (time.strftime("%Y-%m-%d") + ".jsonl"), "a", encoding="utf-8") as f:
                    f.write(json.dumps(ev, default=str) + "\n")
            except OSError as e:
                self.write_errors += 1
                ev["persisted"] = False
                print(f"[openmhp] run log write failed ({e}); history on disk is incomplete, and the chain "
                      f"breaks at seq {ev['seq']}", file=sys.stderr)
        return ev

    # ---- reading it back, and checking it ---------------------------------- #
    @classmethod
    def _step(cls, st: dict, e: dict) -> None:
        """Check one record against the one before it. `st` carries the walk."""
        seq = e.get("seq")
        if "hash" not in e:
            st["unchained"] += 1
            st["prev"] = None                        # nothing for the next record to follow
        else:
            st["chained"] += 1
            if e["hash"] != cls.digest(e):
                st["broken"].append({"seq": seq, "kind": "rewritten",
                                     "problem": "contents do not match this record's own digest"})
            elif st["prev"] is not None and e.get("prev") != st["prev"]:
                st["broken"].append({"seq": seq, "kind": "chain",
                                     "problem": "does not follow the record before it; one was removed, "
                                                "reordered or rewritten"})
            st["prev"] = e["hash"]
        if st["last_seq"] is not None and seq != st["last_seq"] + 1:
            st["broken"].append({"seq": seq, "kind": "missing",
                                 "problem": f"the sequence jumps from {st['last_seq']} to {seq}"})
        if isinstance(seq, int):
            st["last_seq"] = seq

    @staticmethod
    def _walk(prev: str | None = None) -> dict:
        return {"prev": prev, "last_seq": None, "broken": [], "chained": 0, "unchained": 0}

    @staticmethod
    def _missing(verdict: dict) -> bool:
        return any(b.get("kind") in ("missing", "unreadable") for b in verdict["broken"])

    @staticmethod
    def _verdict(st: dict, records: int) -> dict:
        return {"ok": not st["broken"], "records": records, "chained": st["chained"],
                **({"unchained": st["unchained"]} if st["unchained"] else {}),
                "broken": st["broken"][:10],
                **({"more": len(st["broken"]) - 10} if len(st["broken"]) > 10 else {})}

    @classmethod
    def verify(cls, events: list[dict], *, prev: str | None = None) -> dict:
        """Check records against their own digests and against each other. `prev` is the digest
        the first one must follow, when the caller knows it; a window that starts mid-chain
        does not, so the first link is taken on trust and every later one is checked."""
        st = cls._walk(prev)
        for e in events:
            cls._step(st, e)
        return cls._verdict(st, len(events))

    def audit(self) -> dict:
        """Walk every record on disk and check the chain from the first line to the last.

        This is the question `complete` was never able to answer: not "did I serve you
        everything I have" but "is what is on disk still what was written".
        """
        st, records, files = self._walk(self.GENESIS), 0, []
        for f in self._files():
            files.append(f.name)
            try:
                with open(f, encoding="utf-8", errors="replace") as fh:
                    for n, line in enumerate(fh, 1):
                        if not line.strip():
                            continue
                        try:
                            e = json.loads(line)
                        except json.JSONDecodeError:
                            st["broken"].append({"file": f.name, "line": n, "kind": "unreadable",
                                                 "problem": "not a JSON record"})
                            st["prev"] = None
                            continue
                        records += 1
                        self._step(st, e)
            except OSError as e:
                st["broken"].append({"file": f.name, "kind": "unreadable", "problem": f"unreadable ({e})"})
                st["prev"] = None
        return {**self._verdict(st, records), "files": files, "head": self.head,
                "writeErrors": self.write_errors,
                "note": "tamper-evident, not tamper-proof: whoever can write these files can "
                        "rewrite the chain with them"}

    def window(self, seq: int, limit: int = 100) -> dict:
        """Events with seq > `seq`. Falls back to disk when the cursor is older than memory.

        `complete` says whether this is everything after the cursor; `verified` says whether
        the records still match their own digests and each other. Served from memory, verified
        says nothing about the files -- `audit()` is what reads those.
        """
        with self._lock:
            oldest = self.recent[0]["seq"] if self.recent else self.seq + 1
            if seq + 1 >= oldest:
                events = [e for e in self.recent if e["seq"] > seq][:limit]
                v = self.verify(events)
                return {"events": events, "seq": self.seq,
                        "complete": self.write_errors == 0 and not self._missing(v),
                        "verified": {**v, "of": "memory"}}
        events, first_seen = [], None
        for f in self._files():
            try:
                for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
                    try:
                        e = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if first_seen is None:
                        first_seen = e.get("seq")
                    if e.get("seq", 0) > seq:
                        events.append(e)
                        if len(events) >= limit:
                            v = self.verify(events)
                            return {"events": events, "seq": self.seq,
                                    "complete": (first_seen is not None and first_seen <= seq + 1
                                                 and not self._missing(v)),
                                    "verified": {**v, "of": "disk"}}
            except OSError:
                continue
        v = self.verify(events)
        return {"events": events, "seq": self.seq,
                "complete": (self.write_errors == 0 and (first_seen is None or first_seen <= seq + 1)
                             and not self._missing(v)),
                "verified": {**v, "of": "disk"}}

    def since(self, seq: int, limit: int = 100) -> list[dict]:
        return self.window(seq, limit)["events"]


# --------------------------------------------------------------------- runs ---- #
class RunOutput:
    """File-backed script output with a bounded in-memory tail."""

    def __init__(self, path: Path):
        self._f = open(path, "a", encoding="utf-8")
        self._tail: collections.deque[str] = collections.deque()
        self._tail_len = 0
        self.written = 0
        self._lock = threading.Lock()

    def write(self, s: str) -> int:
        with self._lock:
            if self.written < DISK_CAP:
                chunk = s[: DISK_CAP - self.written]
                self._f.write(chunk)
                if len(chunk) < len(s):
                    self._f.write("\n[output truncated: disk cap reached]\n")
                self._f.flush()
            self.written += len(s)
            self._tail.append(s)
            self._tail_len += len(s)
            while self._tail_len > TAIL_CAP and len(self._tail) > 1:
                self._tail_len -= len(self._tail.popleft())
        return len(s)

    def flush(self) -> None:
        pass

    def getvalue(self) -> str:
        with self._lock:
            return "".join(self._tail)

    def close(self) -> None:
        with self._lock:
            self._f.close()


class Run:
    def __init__(self, name: str, script: str, home: Path):
        self.id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
        self.name, self.script = name, script
        self.dir = home / "runs" / self.id
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "script.py").write_text(script, encoding="utf-8")
        self.state, self.started, self.finished = "running", time.time(), None
        self.error: str | None = None
        self.out = RunOutput(self.dir / "stdout.txt")
        self.thread: threading.Thread | None = None

    @property
    def buf(self) -> RunOutput:                     # backward-compatible name
        return self.out

    def meta(self) -> dict:
        return {"id": self.id, "name": self.name, "state": self.state, "started": self.started, "finished": self.finished,
                "error": self.error, "dir": str(self.dir), "pid": os.getpid()}

    def save(self):
        (self.dir / "meta.json").write_text(json.dumps(self.meta(), indent=1), encoding="utf-8")

    def files(self) -> list[str]:
        return sorted(p.relative_to(self.dir).as_posix() for p in self.dir.rglob("*") if p.is_file())


class PlanTruncated(BaseException):
    """Raised when a rehearsal exceeds its step budget; BaseException so scripts cannot swallow it."""


def _virtual_time_module(plan: "PlanLab") -> types.ModuleType:
    real = time
    vt = types.ModuleType("time")
    for k in dir(real):
        if not k.startswith("_"):
            setattr(vt, k, getattr(real, k))
    clock = {"t": real.time(), "m": real.monotonic()}

    def sleep(s):
        s = max(0.0, float(s))
        clock["t"] += s
        clock["m"] += s
        plan.virtual_seconds += s
    vt.sleep = sleep
    vt.time = lambda: clock["t"]
    vt.monotonic = lambda: clock["m"]
    return vt


# ------------------------------------------------------------------ what a script may reach ---- #
#
# A run script is code the host executes (SPEC 7.6), and the host is the trusted side of the protocol, so a
# script written by a model sits inside the trust boundary while its author does not. The device objects the
# SDK hands a *person* carry handles that go past the gates on purpose -- the in-process driver, the untracked
# transport call, a Lab with an approver of its own -- and a script picks them up with one attribute lookup.
# These facades hand a script the audited protocol surface instead. That is an API boundary, not a sandbox:
# it removes the handles rather than the capability, so what it buys is that the gated path is the only one a
# script is given, and that reaching for the others is refused in terms that name the right call and written
# to the run log. Containing code that goes looking anyway needs a process boundary: host the devices out of
# process (`mhp node`, http targets, so this process holds no driver at all) or run the bridge
# with --no-scripts.
DEVICE_API = ("read", "read_all", "write", "invoke", "run_method", "wait", "wait_until", "status", "pause",
              "resume", "cancel", "estop", "reset", "acquire", "release", "describe", "resources", "resource",
              "limits", "methods", "method", "method_find", "method_diff", "method_save", "method_retire",
              "call", "subscribe")
LAB_API = ("find", "estop_all", "shutdown_all", "describe_all", "planning")

_INSTEAD = {
    "driver": "the in-process driver object. on_write and on_invoke are vendor hooks, called only after the "
              "gates have passed, so reaching them skips limits, interlocks, device state, the lease and the "
              "audit record. Use dev.write(name, value) and dev.invoke(name, **params).",
    "_raw_call": "the untracked transport call: it skips the host's approval handling and the audit record. "
                 "Use dev.call(method, params).",
    "_send": "the transport itself. Use dev.call(method, params).",
    "child": "a Lab with hooks of its own; a Lab without an approver passes `approved: true` through "
             "unchecked, and one without an observer records nothing. Use the lab you were given.",
    "approver": "the host's confirmation channel. A script cannot answer for a person; ask through the "
                "device (approval=confirm is put to them by the host).",
    "observer": "the audit hook. What a run does is recorded whether the script likes it or not.",
}

_BEHIND: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()      # facade -> (wrapped object, blocked hook)

# ------------------------------------------------------------------ what a script may import, and write ---- #
#
# Two guards, in the same spirit as the facades above and with the same honest limit: they remove
# the obvious reach rather than containing code that goes looking. What makes a safety value
# actually unchangeable from a script is on the device side -- the driver seals the rules it
# enforces and refuses to actuate if that seal is broken, and a package whose files changed is not
# loaded until a person accepts it. These two keep a script from getting as far as trying, and make
# the attempt a refusal in the run log rather than a silent edit.
#
# Both are bypassable from inside the process by design of the language: ``__builtins__`` is
# reachable, and ``Path.write_text`` does not go through this ``open``. Containing code that works
# around them needs a process boundary: host the devices out of process (`mhp node`, http targets)
# or run the bridge with --no-scripts.
_BLOCKED_IMPORTS = {
    "openmhp": "the host that is running this script. openmhp.client holds the in-process drivers, "
               "openmhp.driver the safety gates themselves, and openmhp.fleet the configuration a "
               "person accepted. A script is given `lab`: use lab['<device-id>'] and the device API.",
    "gc": "the object graph of this process, which reaches every driver in it. "
          "Use lab['<device-id>'] and the device API.",
}
_WRITE_MODES = frozenset("wxa+")


def _import_guard(real_import, blocked, override=None):
    """``__import__`` for a run: refuses the host's own internals, and `override` wins for the rest."""
    def guarded(name, globals=None, locals=None, fromlist=(), level=0):
        top = (name or "").split(".")[0]
        if top in _BLOCKED_IMPORTS:
            blocked(f"import:{name}")
            raise ImportError(f"a run script cannot import '{name}': {_BLOCKED_IMPORTS[top]}")
        if override is not None and name in override:
            return override[name]
        return real_import(name, globals, locals, fromlist, level)
    return guarded


def _write_refused(path, run_dir: Path, homes: tuple[Path, ...] = ()) -> str | None:
    """Why a run may not write here, or None. Reads are not restricted; only writes."""
    try:
        p = Path(os.fsdecode(path) if not isinstance(path, (str, Path)) else path).resolve()
    except (OSError, ValueError, TypeError):
        return None                                   # a file descriptor or something exotic: not a path we police
    if p == run_dir or run_dir in p.parents:
        return None                                   # its own folder, always
    for folder in loaded_package_folders():
        if p == folder or folder in p.parents:
            return (f"{p} is inside the device package at {folder}. A package is what the runtime enforces -- "
                    "limits, interlocks, approval levels, the safety block -- so changing one is the owner's "
                    "decision, made outside a run and accepted deliberately (mhp_lab op='reload'). "
                    "Write what this run produces to run_dir.")
    for home in homes:
        if p == home or home in p.parents:
            return (f"{p} is inside the host's own configuration at {home} (the fleet record of what was "
                    "accepted, the device packages, the run log). Write what this run produces to run_dir.")
    return None


def _open_guard(real_open, blocked, run_dir: Path, homes: tuple[Path, ...] = ()):
    def guarded(file, mode="r", *a, **kw):
        if isinstance(mode, str) and (set(mode) & _WRITE_MODES):
            why = _write_refused(file, run_dir, homes)
            if why is not None:
                blocked(f"write:{file}")
                raise PermissionError(f"a run script cannot write here: {why}")
        return real_open(file, mode, *a, **kw)
    return guarded


class _ScriptFacade:
    """Delegates the calls in ``_API`` and refuses everything else.

    The wrapped object is held outside the facade, so the facade carries no attribute that leads back to it
    and every name the API does not list reaches ``__getattr__``.
    """

    _API: tuple[str, ...] = ()

    def __init__(self, wrapped, blocked):
        _BEHIND[self] = (wrapped, blocked)

    def __getattr__(self, attr):
        if attr.startswith("__") and attr.endswith("__"):           # Python's own lookups, not the script's
            raise AttributeError(attr)
        wrapped, blocked = _BEHIND[self]
        if attr in self._API:
            return getattr(wrapped, attr)
        blocked(attr)
        raise AttributeError(f"a run script cannot reach '{attr}': " +
                             _INSTEAD.get(attr, f"a script works through the device API ({', '.join(self._API)})."))


class ScriptDevice(_ScriptFacade):
    """The device a script sees: the primitives, jobs, methods and leases, and no way around their gates."""

    _API = DEVICE_API

    @property
    def name(self) -> str:
        return _BEHIND[self][0].name

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()

    def __repr__(self):
        return f"<device {self.name}>"


class ScriptLab(_ScriptFacade):
    """The lab a script sees. ``lab['id']`` returns a ScriptDevice, in a run and in a plan alike."""

    _API = LAB_API

    def __init__(self, lab, blocked):
        super().__init__(lab, blocked)
        self._devices: dict[str, ScriptDevice] = {}                 # facades only; one per name, as the Lab caches

    def __getitem__(self, name: str) -> ScriptDevice:
        if name not in self._devices:
            lab, blocked = _BEHIND[self]
            self._devices[name] = ScriptDevice(lab[name], blocked)
        return self._devices[name]

    def __contains__(self, name: str) -> bool:
        return name in _BEHIND[self][0]

    def __repr__(self):
        return "<lab>"


class Runs:
    def __init__(self, lab: Lab, log: RunLog, home: Path | None = None, observer=None):
        self.lab, self.log, self.home = lab, log, home or HOME
        self.observer = observer                     # callable(event) for audited run calls
        self.runs: dict[str, Run] = {}
        self._mark_interrupted()

    def _protected(self) -> tuple[Path, ...]:
        """The host's own configuration: this process's home and the default one, resolved."""
        out = []
        for h in (self.home, HOME):
            try:
                r = Path(h).resolve()
            except (OSError, ValueError):
                continue
            if r not in out:
                out.append(r)
        return tuple(out)

    def _mark_interrupted(self) -> None:
        base = self.home / "runs"
        if not base.is_dir():
            return
        for d in base.iterdir():
            m = d / "meta.json"
            if not m.is_file():
                continue
            try:
                meta = json.loads(m.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if meta.get("state") == "running" and not _pid_alive(meta.get("pid")):
                meta.update(state="interrupted", error="the process running this script ended before it finished")
                try:
                    m.write_text(json.dumps(meta, indent=1), encoding="utf-8")
                except OSError:
                    pass

    def start(self, script: str, name: str = "run", timeout_s: float = 600, background: bool = False,
              lab: Lab | None = None, params: dict | None = None, plan: "PlanLab | None" = None) -> dict:
        run = Run(name, script, self.home)
        self.runs[run.id] = run
        run.save()
        self.log.write("run/start", run=run.id, name=name, background=background, plan=plan is not None,
                       script_sha=hashlib.sha256(script.encode("utf-8")).hexdigest()[:12])
        own_lab = None
        if plan is not None:
            run_lab = plan
        elif lab is not None:
            run_lab = lab
        else:
            obs = (lambda ev, rid=run.id: self.observer({**ev, "run": rid})) if self.observer else None
            run_lab = own_lab = self.lab.child(session=f"run-{run.id}", observer=obs)

        def run_print(*a, **k):
            k.setdefault("file", run.out)
            builtins.print(*a, **k)

        def blocked(attr, rid=run.id):
            self.log.write("script/blocked", run=rid, attribute=attr)

        env = {"lab": ScriptLab(run_lab, blocked), "run_dir": str(run.dir), "run_id": run.id,
               "__name__": "__mhp_run__", "__mhp_params__": dict(params or {}), "print": run_print}
        run_root = run.dir.resolve()
        override = {"time": _virtual_time_module(plan)} if plan is not None else None
        env["__builtins__"] = {**builtins.__dict__, "print": run_print,
                               "__import__": _import_guard(builtins.__import__, blocked, override),
                               "open": _open_guard(builtins.open, blocked, run_root, self._protected())}

        def target():
            try:
                exec(compile(script, f"<mhp_run:{run.id}>", "exec"), env)
                run.state = "done"
            except PlanTruncated as e:
                run.state, run.error = "truncated", str(e)
            except RemoteError as e:
                run.state, run.error = "failed", json.dumps({"mhpError": {"code": e.code, "message": e.message, "data": e.data}}, default=str)
            except Exception as e:                          # noqa: BLE001
                tb = traceback.extract_tb(e.__traceback__)
                line = next((f.lineno for f in reversed(tb) if f.filename.startswith("<mhp_run")), None)
                run.state, run.error = "failed", f"{type(e).__name__}: {e}" + (f" (script line {line})" if line else "")
            finally:
                if own_lab is not None:
                    own_lab.close()                         # releases this run's leases
                run.finished = time.time()
                run.out.close()
                run.save()
                self.log.write("run/finish", run=run.id, state=run.state, error=run.error)

        run.thread = threading.Thread(target=target, name=f"mhp-run-{run.id}", daemon=True)
        run.thread.start()
        if background:
            return {"run": run.meta(), "note": "running in the background; check with mhp_data op='runs' or op='read' run=<id> path='stdout.txt'"}
        run.thread.join(timeout_s)
        if run.thread.is_alive():
            return {"run": run.meta(), "stdout": self._out(run), "note": f"still running after {timeout_s}s; it continues in the background"}
        return self.result(run)

    def result(self, run: Run) -> dict:
        out = {"run": run.meta(), "ok": run.state == "done", "stdout": self._out(run),
               "files": [f for f in run.files() if f not in ("script.py", "meta.json", "stdout.txt")]}
        if run.error:
            try:
                out["error"] = json.loads(run.error)
            except (json.JSONDecodeError, TypeError):
                out["error"] = run.error
        return out

    @staticmethod
    def _out(run: Run) -> str:
        s = run.out.getvalue()
        return s[-STDOUT_CAP:] if len(s) > STDOUT_CAP else s

    def list(self) -> list[dict]:
        live = {r.id: r.meta() for r in self.runs.values()}
        base = self.home / "runs"
        if base.is_dir():
            for d in sorted(base.iterdir()):
                if d.name not in live and (d / "meta.json").is_file():
                    try:
                        live[d.name] = json.loads((d / "meta.json").read_text(encoding="utf-8"))
                    except json.JSONDecodeError:
                        pass
        return sorted(live.values(), key=lambda m: m["started"], reverse=True)[:50]

    def resolve(self, run_id: str) -> Path:
        if run_id in ("latest", "", None):
            runs = self.list()
            if not runs:
                raise FileNotFoundError("no runs yet")
            run_id = runs[0]["id"]
        if not isinstance(run_id, str) or not RUN_ID.match(run_id):
            raise FileNotFoundError(f"not a run id: {run_id!r}")
        root = (self.home / "runs").resolve()
        d = (root / run_id).resolve()
        if d.parent != root or not d.is_dir():
            raise FileNotFoundError(f"no run {run_id}")
        return d

    def read(self, run_id: str, rel: str, cap: int = 64_000) -> dict:
        d = self.resolve(run_id)
        p = (d / rel).resolve()
        if d not in p.parents:
            raise PermissionError(rel)
        if not p.is_file():
            raise FileNotFoundError(rel)
        if p.suffix.lower() in (".txt", ".md", ".csv", ".json", ".py", ".yaml", ".yml", ".log", ".jsonl"):
            with open(p, encoding="utf-8", errors="replace") as f:
                text = f.read(cap + 1)
            return {"run": d.name, "path": rel, "text": text[:cap], "truncated": len(text) > cap}
        return {"run": d.name, "path": rel, "bytes": p.stat().st_size, "text": None, "note": "binary; copy from " + str(p)}


def _pid_alive(pid) -> bool:
    if not isinstance(pid, int):
        return False
    if pid == os.getpid():
        return False                                # a run from this process not in self.runs did not survive
    if os.name == "nt":                             # signal 0 is CTRL_C_EVENT on Windows, not a probe
        return _windows_pid_alive(pid)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _windows_pid_alive(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes
    if not 0 < pid <= 0xFFFFFFFF:                   # a DWORD; ctypes would silently truncate anything larger
        return False
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    h = k32.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ctypes.get_last_error() == 5         # ERROR_ACCESS_DENIED: it exists; any other failure: it is gone
    try:
        code = wintypes.DWORD()
        return bool(k32.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259     # STILL_ACTIVE
    finally:
        k32.CloseHandle(h)


# --------------------------------------------------------------------- plan ---- #
_PLAN_READ_ONLY = {"initialize", "ping", "device/describe", "signals/list", "signals/read", "settings/list",
                   "methods/list", "methods/get", "methods/find", "methods/diff",
                   "actions/list", "jobs/status", "jobs/list", "safety/limits", "resources/list", "resources/read"}


class PlanDevice:
    """Wraps a Device: reads are real, writes/invokes are dry runs, nothing else mutates."""

    def __init__(self, dev: Device, plan: "PlanLab", name: str):
        self._dev, self._planlab, self.name = dev, plan, name
        self._n = 0

    def _step(self, kind: str, target: str, value=None, **extra) -> dict:
        self._n += 1
        return self._planlab.add_step({"device": self.name, "kind": kind, "target": target,
                                       **({"value": value} if value is not None else {}), **extra})

    def _judge(self, e: dict, fn) -> dict:
        try:
            r = fn()
            e["gate"] = "ok"
            if r.get("needsApproval"):
                e["asks_human"] = True
            for k in ("needsLease", "leaseHeldBy", "busyNow"):
                if r.get(k):
                    e.setdefault("notes", {})[k] = r[k]
            return r
        except RemoteError as err:
            if err.code == InterlockOpen.code:
                e["gate"] = "INTERLOCK_OPEN_NOW"
                e["note"] = f"{err.message} (a live reading; earlier steps may change it at run time)"
            else:
                e["gate"] = "REFUSED"
            e["error"] = err.message
            return {}

    def read(self, *names):
        v = self._dev.read(*names)
        self._step("read", ",".join(names), value=v, live=True)
        return v

    def write(self, name, value, approved=False, dry_run=False):
        e = self._step("write", name, value=value)
        self._judge(e, lambda: self._dev.write(name, value, dry_run=True))
        return {"ok": e["gate"] == "ok", "planned": True}

    def invoke(self, name, approved=False, dry_run=False, **params):
        e = self._step("invoke", name, params=params)
        self._judge(e, lambda: self._dev.call("actions/invoke", {"name": name, "params": params, "dryRun": True}))
        if e.get("gate") == "ok" and self._spec("actions", name).get("duration") == "long":
            e["long_running"] = True
        return {"id": f"plan_{self._n}", "action": name, "state": "planned", "progress": 0.0, "result": None}

    def run_method(self, name, overrides=None, *, project=None, version=None, run_project=None, compound=None, wait=True, timeout=None):
        """M10: a method run in a plan is a dry-run invoke with the resolved parameters; the step names the method."""
        m = self._dev.method(name, project, version)
        mref = {"name": m["name"], "project": m["project"], **({"version": version} if version else {}),
                **({"overrides": overrides} if overrides else {})}
        e = self._step("invoke", m["action"], method={"project": m["project"], "name": m["name"], "version": m["version"], "hash": m["hash"],
                                                       **({"overrides": overrides} if overrides else {})},
                       **({"project": run_project} if run_project else {}))
        self._judge(e, lambda: self._dev.call("actions/invoke", {"name": m["action"], "method": mref, "dryRun": True,
                                                                  **({"project": run_project} if run_project else {}),
                                                                  **({"compound": compound} if compound else {})}))
        if e.get("gate") == "ok" and self._spec("actions", m["action"]).get("duration") == "long":
            e["long_running"] = True
        job = {"id": f"plan_{self._n}", "action": m["action"], "state": "planned", "progress": 0.0, "result": None,
               "method": e["method"], "project": run_project or m["project"]}
        return self.wait(job) if wait else job

    def methods(self, *a, **kw): return self._dev.methods(*a, **kw)
    def method_find(self, *a, **kw): return self._dev.method_find(*a, **kw)
    def method(self, *a, **kw): return self._dev.method(*a, **kw)
    def method_diff(self, *a, **kw): return self._dev.method_diff(*a, **kw)

    def method_save(self, method, note=None):
        self._step("rpc", "methods/save", params={"method": {k: method.get(k) for k in ("name", "project", "action", "compounds")}},
                   gate="not executed in plan")
        return {"planned": True, "saved": {"name": method.get("name"), "project": method.get("project")}}

    def method_retire(self, name, project=None):
        self._step("rpc", "methods/delete", params={"name": name, "project": project}, gate="not executed in plan")
        return {"planned": True}

    def wait(self, job, poll=0.2, timeout=None):
        return {**job, "state": "done", "progress": 1.0, "result": {"planned": True}}

    def wait_until(self, signal, test, *, timeout, poll=1.0, label=""):
        v = self._dev.read(signal)
        self._step("wait_until", signal, value=v, condition=label or "condition", timeout_s=timeout,
                   note="not waited in a plan; the run polls the live signal")
        return v

    def status(self, job):
        return self.wait(job)

    def cancel(self, job): self._step("cancel", str(job)); return self.wait(job)
    def pause(self, job): self._step("pause", str(job)); return job
    def resume(self, job): self._step("resume", str(job)); return job
    def estop(self, reason=""): self._step("estop", "*", reason=reason); return {"planned": True}
    def reset(self): self._step("reset", "*"); return {"planned": True}
    def acquire(self, ttl=60): self._step("lease", "acquire"); return {"planned": True}
    def release(self): self._step("lease", "release"); return {"planned": True}
    def describe(self, detail="full"): return self._dev.describe(detail)
    def read_all(self): return self.read()

    def call(self, method, params=None):
        params = params or {}
        if method in _PLAN_READ_ONLY:
            return self._dev.call(method, params)
        if method == "settings/write":
            return self.write(params.get("name"), params.get("value"))
        if method == "actions/invoke":
            if params.get("method"):
                mref = params["method"] if isinstance(params["method"], dict) else {"name": params["method"]}
                return {"job": self.run_method(mref["name"], mref.get("overrides"), project=mref.get("project"),
                                               version=mref.get("version"), run_project=params.get("project"),
                                               compound=params.get("compound"), wait=False)}
            return {"job": self.invoke(params.get("name"), **(params.get("params") or {}))}
        self._step("rpc", method, params=params, gate="not executed in plan")
        return {"planned": True}

    def __enter__(self): self.acquire(); return self
    def __exit__(self, *a): self.release()

    def _spec(self, section, name):
        try:
            items = self._dev.call("device/describe", {"select": {section: [name]}})[section]
            return items[0] if items else {}
        except RemoteError:
            return {}


class PlanLab:
    planning = True

    def __init__(self, lab: Lab, max_steps: int = 300):
        self._lab, self.plan = lab, []
        self.max_steps = max_steps
        self.virtual_seconds = 0.0
        self._cache: dict[str, PlanDevice] = {}

    def add_step(self, entry: dict) -> dict:
        if len(self.plan) >= self.max_steps:
            raise PlanTruncated(f"plan stopped after {self.max_steps} steps")
        entry = {"step": len(self.plan) + 1, **entry}
        self.plan.append(entry)
        return entry

    def __getitem__(self, name):
        if name not in self._cache:
            self._cache[name] = PlanDevice(self._lab[name], self, name)
        return self._cache[name]

    def __contains__(self, name) -> bool:
        return name in self._lab

    def find(self, *a, **k): return self._lab.find(*a, **k)
    def estop_all(self, reason=""): self.add_step({"device": "*", "kind": "estop"}); return {}

    def close(self): self._lab.close()

    def summary(self, run_state: str = "done", error=None) -> dict:
        refused = [e for e in self.plan if e.get("gate") == "REFUSED"]
        interlocks = [e for e in self.plan if e.get("gate") == "INTERLOCK_OPEN_NOW"]
        asks = [e for e in self.plan if e.get("asks_human")]
        if refused:
            verdict = "would be refused at step %d: %s" % (refused[0]["step"], refused[0]["error"])
        elif run_state == "truncated":
            verdict = (f"truncated after {len(self.plan)} steps: the script keeps going (it likely loops on live readings, "
                       "which a rehearsal cannot change); the steps shown passed the gates")
        elif run_state == "failed":
            verdict = "script stopped before completing the plan: " + json.dumps(error, default=str)[:200]
        else:
            verdict = ("ok; %d step(s) need a person's confirmation" % len(asks)) if asks else "ok; no confirmation needed"
        if interlocks and not refused:
            verdict += "; %d step(s) depend on interlocks that are open right now" % len(interlocks)
        return {"steps": self.plan, "refused": refused, "asks_human": asks, "interlocks_open_now": interlocks,
                "virtual_seconds": round(self.virtual_seconds, 1), "verdict": verdict,
                "caveat": "A plan follows one path through the script using current readings; branches that depend on "
                          "readings during the run may differ."}
