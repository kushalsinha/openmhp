"""`mhp-gw`: what a scientist's machine can do on the gateway over SSH, and nothing else.

The gateway's SSH server runs this as a forced command for each scientist's key:

    command="mhp-gw --scientist alice --root /srv/openmhp",no-pty,no-port-forwarding,... ssh-ed25519 AAAA...

so whatever the scientist's agent asks for arrives in SSH_ORIGINAL_COMMAND and is handled here:

    ssh gw mhp-gw open                 a new run in this scientist's folder; returns its ID and where to copy files
    ssh gw mhp-gw list                 this scientist's runs
    ssh gw mhp-gw status <run id>      one run's state

Every answer is one JSON object on stdout. Exit codes: 0 done, 2 waiting for a person, 3 refused,
4 not found. Anything not listed is refused, so there is no shell and no path outside the
scientist's own folder.
"""
from __future__ import annotations

import json
import os
import shlex
import sys
from pathlib import Path

from . import scientists as S

OK, WAITING, REFUSED, NOT_FOUND = 0, 2, 3, 4
VERBS = {
    "open": "a new run in your folder; copy your skills, scripts and data into its in/ folder",
    "list": "your runs and their states",
    "status": "status <run id>: one run's state",
    "help": "this list",
}


class Shell:
    def __init__(self, scientist: str, root: Path | None = None, out=None, env=None):
        self.scientist = S.check_name(scientist)
        self.root = root
        self.out = out if out is not None else sys.stdout
        self.env = os.environ if env is None else env

    def answer(self, code: int, **obj) -> int:
        self.out.write(json.dumps({"ok": code == OK, **obj}, default=str) + "\n")
        self.out.flush()
        return code

    def refuse(self, why: str, code: int = REFUSED) -> int:
        return self.answer(code, error=why, verbs=VERBS)

    def run(self) -> int:
        original = self.env.get("SSH_ORIGINAL_COMMAND", "").strip()
        if not original:
            return self.refuse("this connection only accepts commands, for example: ssh <gateway> mhp-gw open")
        try:
            argv = shlex.split(original)
        except ValueError as e:
            return self.refuse(f"could not read the command: {e}")
        if argv and Path(argv[0]).name == "mhp-gw":
            argv = argv[1:]
        if not argv:
            argv = ["help"]
        verb, args = argv[0], argv[1:]
        handler = getattr(self, "verb_" + verb, None) if verb in VERBS else None
        if handler is None:
            return self.refuse(f"{verb!r} is not something this gateway does for scientists")
        try:
            return handler(args)
        except (ValueError, LookupError) as e:
            return self.refuse(str(e), NOT_FOUND if isinstance(e, LookupError) else REFUSED)

    # ---- verbs -------------------------------------------------------------------------------
    def verb_help(self, args) -> int:
        return self.answer(OK, scientist=self.scientist, verbs=VERBS)

    def verb_open(self, args) -> int:
        meta = S.open_run(self.scientist, self.root)
        return self.answer(OK, run=meta["id"], state=meta["state"], upload=f"runs/{meta['id']}/in/",
                           note="copy your folder into upload, for example: scp -O -r <folder> <gateway>:" + f"runs/{meta['id']}/in/")

    def verb_list(self, args) -> int:
        return self.answer(OK, scientist=self.scientist,
                           runs=[{k: r.get(k) for k in ("id", "state", "created")} for r in S.runs(self.scientist, self.root)])

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
