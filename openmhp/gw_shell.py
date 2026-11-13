"""`mhp-gw`: what a scientist's machine can do on the gateway over SSH, and nothing else.

The gateway's SSH server runs this as a forced command for each scientist's key:

    command="mhp-gw --scientist alice --root /srv/openmhp",no-pty,no-port-forwarding,... ssh-ed25519 AAAA...

so whatever the scientist's agent asks for arrives in SSH_ORIGINAL_COMMAND and is handled here:

    ssh gw mhp-gw open                 a new run in this scientist's folder; returns its ID and where to copy files
    ssh gw mhp-gw list                 this scientist's runs
    ssh gw mhp-gw status <run id>      one run's state

    rsync -a <folder>/ gw:runs/<run id>/in/        copy skills, scripts and data in
    rsync -a gw:runs/<run id>/out/ <here>/         copy results out (also preview/)
    scp -O -r <folder> gw:runs/<run id>/in/        the same with scp, in its classic mode

rsync is the way to copy. File copies run rsync or scp on the gateway only for paths inside the scientist's own folder: into a
run's in/, out of its preview/ and out/. scp from OpenSSH 9 on speaks SFTP unless given -O, and SFTP
cannot be limited this way, so it is refused with a hint.

Every answer is one JSON object on stdout. Exit codes: 0 done, 2 waiting for a person, 3 refused,
4 not found. Anything not listed is refused, so there is no shell and no path outside the
scientist's own folder.
"""
from __future__ import annotations

import json
import os
import posixpath
import re
import shlex
import sys
from pathlib import Path

from . import scientists as S

OK, WAITING, REFUSED, NOT_FOUND = 0, 2, 3, 4
VERBS = {
    "open": "a new run in your folder; copy your skills, scripts and data into its in/ folder with rsync",
    "list": "your runs and their states",
    "status": "status <run id>: one run's state",
    "request": "request <run id> [--harness claude-code] < request.md: what you need, in plain English; a planner starts",
    "wait": "wait <run id> [--since <ts>] [--timeout <s>]: block until there is news (a question, a charter, a state change)",
    "show": "show <run id>: the run's charter to approve, its state and any open questions",
    "approve": "approve <run id> --charter-digest <digest>: the scientist approves exactly that charter; the run starts",
    "message": "message <run id> <text, or on stdin>: tell the running agent something",
    "answer": "answer <run id> <question id> <text, or on stdin>: answer the run's question",
    "stop": "stop <run id>: stop now; the agent cleans up as the charter says",
    "help": "this list",
}
WAIT_S = 60                                    # how long a request waits for the supervisor before saying "pending"


SFTP_HINT = ("copy files with rsync (rsync -a <folder>/ <gateway>:runs/<run id>/in/); scp works only in its "
             "classic mode, with -O")
RSYNC_LONG = {"--server", "--sender", "--dirs", "--recursive", "--links", "--times", "--perms", "--owner", "--group",
              "--devices", "--specials", "--hard-links", "--executability", "--omit-dir-times", "--partial", "--delete", "--delete-before", "--delete-during", "--delete-delay",
              "--delete-after", "--numeric-ids", "--safe-links", "--append", "--append-verify", "--inplace",
              "--no-implied-dirs", "--ignore-errors", "--force", "--size-only", "--ignore-times", "--checksum",
              "--compress", "--prune-empty-dirs"}
RSYNC_LONG_VALUED = ("--info=", "--debug=", "--compress-level=", "--checksum-choice=", "--compress-choice=",
                     "--timeout=", "--bwlimit=", "--min-size=", "--max-size=", "--modify-window=")
SHORT_CLUSTER = re.compile(r"^-[A-Za-z0-9.]+$")          # what an rsync client sends, e.g. -logDtpre.iLsfxCIvu
SCP_FLAGS = {"-r", "-d", "-p", "-v", "-q"}


class Shell:
    def __init__(self, scientist: str, root: Path | None = None, out=None, env=None, execvp=None, err=None, stdin=None,
                 wait_s: float | None = None):
        self.scientist = S.check_name(scientist)
        self.root = root
        self.out = out if out is not None else sys.stdout
        self.err = err if err is not None else sys.stderr
        self.env = os.environ if env is None else env
        self.execvp = execvp or os.execvp
        self.stdin = stdin if stdin is not None else sys.stdin
        self.wait_s = WAIT_S if wait_s is None else wait_s

    def answer(self, code: int, **obj) -> int:
        self.out.write(json.dumps({"ok": code == OK, **obj}, default=str) + "\n")
        self.out.flush()
        return code

    def refuse(self, why: str, code: int = REFUSED) -> int:
        return self.answer(code, error=why, verbs=VERBS)

    def refuse_copy(self, why: str, code: int = REFUSED) -> int:
        """A refused file copy: on stderr, which rsync and scp show as text. Their stdout is the copy protocol."""
        self.err.write(f"mhp-gw: {why}\n")
        self.err.flush()
        return code

    def run(self) -> int:
        original = self.env.get("SSH_ORIGINAL_COMMAND", "").strip()
        if not original:
            return self.refuse("this connection only accepts commands, for example: ssh <gateway> mhp-gw open. "
                               "If you were copying files: " + SFTP_HINT)
        try:
            argv = shlex.split(original)
        except ValueError as e:
            return self.refuse(f"could not read the command: {e}")
        if argv and Path(argv[0]).name == "mhp-gw":
            argv = argv[1:]
        if not argv:
            argv = ["help"]
        prog = Path(argv[0]).name
        if prog in ("sftp", "sftp-server", "internal-sftp"):
            return self.refuse_copy(SFTP_HINT)
        if prog in ("rsync", "scp"):
            try:
                args = self.copy_args(prog, argv[1:])
            except (ValueError, LookupError) as e:
                return self.refuse_copy(str(e), NOT_FOUND if isinstance(e, LookupError) else REFUSED)
            os.chdir(S.folder(self.scientist, self.root))
            self.execvp(prog, [prog, *args])                   # replaces this process; returns only in tests
            return OK
        verb, args = argv[0], argv[1:]
        handler = getattr(self, "verb_" + verb, None) if verb in VERBS else None
        if handler is None:
            return self.refuse(f"{verb!r} is not something this gateway does for scientists")
        try:
            return handler(args)
        except (ValueError, LookupError) as e:
            return self.refuse(str(e), NOT_FOUND if isinstance(e, LookupError) else REFUSED)

    # ---- file copies -------------------------------------------------------------------------
    def place(self, raw: str, receiving: bool) -> str:
        """The path a copy may touch, relative to the scientist's folder, or an error that says why not.
        Receiving (a copy TO the gateway) lands only in runs/<id>/in/; sending only from preview/ or out/."""
        p = raw[2:] if raw.startswith("~/") else raw
        if p.startswith("/"):                          # absolute: only the scientist's own folder, as a prefix
            d = S.folder(self.scientist, self.root)
            for base in {d.as_posix().rstrip("/"), d.resolve().as_posix().rstrip("/")}:
                if p == base or p.startswith(base + "/"):
                    p = p[len(base):].lstrip("/")
                    break
            else:
                raise ValueError(f"{raw} is outside your folder on the gateway")
        norm = posixpath.normpath(p) if p else ""
        parts = norm.split("/") if norm not in ("", ".") else []
        if ".." in parts:
            raise ValueError(f"{raw}: '..' is not allowed")
        allowed = ("in",) if receiving else ("preview", "out")
        if len(parts) < 3 or parts[0] != "runs" or not S.RUN_ID.match(parts[1]) or parts[2] not in allowed:
            where = "into runs/<run id>/in/" if receiving else "from runs/<run id>/preview/ or runs/<run id>/out/"
            raise ValueError(f"{raw}: files can only be copied {where}")
        if not S.run_folder(self.scientist, parts[1], self.root).is_dir():
            raise LookupError(f"no run {parts[1]} in your folder (open one with: mhp-gw open)")
        return "/".join(parts) + ("/" if raw.endswith("/") and len(parts) > 0 else "")

    def copy_args(self, prog: str, args: list[str]) -> list[str]:
        if prog == "rsync":
            if "--server" not in args or "." not in args:
                raise ValueError("rsync here runs only as the far end of a copy (rsync -a <from> <gateway>:<to>)")
            dot = args.index(".")
            opts, paths = args[:dot], args[dot + 1:]
            for o in opts:
                if o.startswith("--"):
                    if o not in RSYNC_LONG and not o.startswith(RSYNC_LONG_VALUED):
                        raise ValueError(f"rsync option {o} is not allowed on this gateway")
                elif not SHORT_CLUSTER.match(o):
                    raise ValueError(f"rsync option {o!r} is not allowed on this gateway")
            if not paths:
                raise ValueError("rsync named no path")
            receiving = "--sender" not in opts
            placed = [self.place(x, receiving) for x in paths]
            return opts + (["--safe-links"] if receiving and "--safe-links" not in opts else []) + ["."] + placed
        # scp, classic protocol: scp -t <dest> (copy to the gateway) or scp -f <src> (copy from it)
        flags = [a for a in args if a.startswith("-")]
        paths = [a for a in args if not a.startswith("-")]
        direction = [f for f in flags if f in ("-t", "-f")]
        if len(direction) != 1 or any(f not in SCP_FLAGS | {"-t", "-f", "--"} for f in flags) or len(paths) != 1:
            raise ValueError("scp here takes one path, copied with -r if it is a folder; " + SFTP_HINT)
        rest = [f for f in flags if f != "--"]
        return rest + ["--", self.place(paths[0], receiving=direction[0] == "-t")]

    # ---- verbs -------------------------------------------------------------------------------
    def verb_help(self, args) -> int:
        return self.answer(OK, scientist=self.scientist, verbs=VERBS)

    def verb_open(self, args) -> int:
        meta = S.open_run(self.scientist, self.root)
        return self.answer(OK, run=meta["id"], state=meta["state"], upload=f"runs/{meta['id']}/in/",
                           note=f"copy your folder into upload with rsync: rsync -a <folder>/ <gateway>:runs/{meta['id']}/in/")

    def verb_list(self, args) -> int:
        return self.answer(OK, scientist=self.scientist,
                           runs=[{k: r.get(k) for k in ("id", "state", "created")} for r in S.runs(self.scientist, self.root)])

    # ---- requests the supervisor acts on ---------------------------------------------------
    def _run(self, run_id: str) -> dict:
        meta = S.load_run(self.scientist, S.check_run_id(run_id), self.root)
        if meta is None:
            raise LookupError(f"no run {run_id} in your folder")
        return meta

    def _text(self, rest: list[str]) -> str:
        text = " ".join(rest).strip()
        if not text and self.stdin is not None and not getattr(self.stdin, "isatty", lambda: False)():
            text = self.stdin.read().strip()
        if not text:
            raise ValueError("say something: put the text after the arguments, or on stdin")
        return text

    def request(self, run_id: str, body: dict) -> int:
        """Leave the request in the run's inbox for the supervisor, and wait for its answer."""
        import time
        self._run(run_id)
        inbox = S.run_folder(self.scientist, run_id, self.root) / "inbox"
        inbox.mkdir(exist_ok=True)
        name = f"{time.strftime('%Y%m%dT%H%M%S')}-{os.getpid()}-{body['kind']}"
        tmp = inbox / (name + ".tmp")
        tmp.write_text(json.dumps(body), encoding="utf-8")
        os.replace(tmp, inbox / (name + ".json"))
        done = inbox / (name + ".done.json")
        end = time.time() + self.wait_s
        while time.time() < end:
            if done.is_file():
                ans = json.loads(done.read_text(encoding="utf-8"))
                done.unlink()
                if ans.get("ok"):
                    return self.answer(OK, **{k: v for k, v in ans.items() if k != "ok"})
                return self.refuse(ans.get("error", "refused"), NOT_FOUND if ans.get("not_found") else REFUSED)
            time.sleep(0.2)
        return self.answer(WAITING, run=run_id, pending=body["kind"],
                           note="the gateway has the request but has not acted on it yet; check again with mhp-gw status")

    def verb_request(self, args) -> int:
        if not args:
            return self.refuse("request needs a run ID (from mhp-gw open), and the request on stdin")
        harness = None
        if len(args) == 3 and args[1] == "--harness":
            harness = args[2]
        elif len(args) != 1:
            return self.refuse("request <run id> [--harness <name>], with the request on stdin")
        return self.request(args[0], {"kind": "request", "text": self._text([]), "harness": harness})

    def verb_wait(self, args) -> int:
        import time
        if not args:
            return self.refuse("wait needs a run ID")
        run_id, opts = args[0], dict(zip(args[1::2], args[2::2]))
        try:
            since = float(opts.get("--since", 0))
            timeout = min(float(opts.get("--timeout", 300)), 3600)
        except ValueError:
            return self.refuse("--since and --timeout take numbers")
        self._run(run_id)
        log = S.run_folder(self.scientist, run_id, self.root) / "events.jsonl"
        news = {"question", "charter_proposed", "charter_revised", "state", "finish", "report"}
        end = time.time() + timeout
        while True:
            events = []
            if log.is_file():
                for line in log.read_text(encoding="utf-8").splitlines():
                    try:
                        ev = json.loads(line)
                    except ValueError:
                        continue
                    if ev.get("ts", 0) > since and ev.get("kind") in news:
                        events.append(ev)
            if events or time.time() >= end:
                meta = self._run(run_id)
                return self.answer(OK if events else WAITING, run=run_id, state=meta.get("state"), events=events,
                                   since=max([since] + [e["ts"] for e in events]),
                                   open_questions=meta.get("open_questions") or {})
            time.sleep(0.5)

    def verb_show(self, args) -> int:
        if len(args) != 1:
            return self.refuse("show needs one run ID")
        meta = self._run(args[0])
        d = S.run_folder(self.scientist, args[0], self.root)
        charter = (d / "charter.md").read_text(encoding="utf-8") if (d / "charter.md").is_file() else None
        return self.answer(OK, run=meta, charter=charter, charter_digest=meta.get("charter_digest"),
                           open_questions=meta.get("open_questions") or {})

    def verb_approve(self, args) -> int:
        if len(args) != 3 or args[1] != "--charter-digest":
            return self.refuse("approve needs: approve <run id> --charter-digest <digest from mhp-gw show>")
        return self.request(args[0], {"kind": "approve", "digest": args[2]})

    def verb_message(self, args) -> int:
        if not args:
            return self.refuse("message needs a run ID and the text")
        return self.request(args[0], {"kind": "message", "text": self._text(args[1:])})

    def verb_answer(self, args) -> int:
        if len(args) < 2:
            return self.refuse("answer needs a run ID, a question ID and the text")
        return self.request(args[0], {"kind": "answer", "question": args[1], "text": self._text(args[2:])})

    def verb_stop(self, args) -> int:
        if len(args) != 1:
            return self.refuse("stop needs one run ID")
        return self.request(args[0], {"kind": "stop"})

    def verb_status(self, args) -> int:
        if len(args) != 1:
            return self.refuse("status needs one run ID, for example: mhp-gw status R-2611-0042")
        meta = S.load_run(self.scientist, S.check_run_id(args[0]), self.root)
        if meta is None:
            raise LookupError(f"no run {args[0]} in your folder")
        return self.answer(OK, run=meta)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    scientist, root = None, None
    while argv:
        a = argv.pop(0)
        if a == "--scientist" and argv:
            scientist = argv.pop(0)
        elif a == "--root" and argv:
            root = Path(argv.pop(0))
        else:
            print(json.dumps({"ok": False, "error": f"unexpected argument {a!r}"}))
            return REFUSED
    if not scientist:
        print(json.dumps({"ok": False, "error": "mhp-gw runs only as a gateway's forced command, with --scientist"}))
        return REFUSED
    try:
        return Shell(scientist, root).run()
    except ValueError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return REFUSED


if __name__ == "__main__":
    sys.exit(main())
