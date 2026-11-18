"""Files that other threads and processes read while they are rewritten: a run's state, its answers, its usage.

Written to one side and moved into place, so a reader sees the old file or the new one, never half of either.
POSIX lets a file be replaced while someone reads it; Windows refuses the move ("Access is denied") while any
reader has it open, and opening one mid-move can be refused the same way. Readers hold these files for
microseconds, so both sides wait a moment and try again instead of failing a scientist's stop or approval.
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

RETRY_S = 2.0


def replace_when_free(tmp: Path, final: Path, within: float = RETRY_S) -> None:
    """Move `tmp` onto `final`, waiting out a reader that has `final` open (Windows)."""
    deadline = time.time() + within
    while True:
        try:
            os.replace(tmp, final)
            return
        except PermissionError:
            if time.time() >= deadline:
                raise
            time.sleep(0.01)


def write_text(path: Path, text: str) -> None:
    """Replace `path` whole. The side file is this thread's own, so two writers never share one."""
    path = Path(path)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        replace_when_free(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def read_text(path: Path, within: float = RETRY_S) -> str:
    """Read `path`, waiting out a writer that is moving a new copy into place (Windows)."""
    deadline = time.time() + within
    while True:
        try:
            return Path(path).read_text(encoding="utf-8")
        except PermissionError:
            if time.time() >= deadline:
                raise
            time.sleep(0.01)
