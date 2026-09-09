"""MHP Directory: find the right device among thousands without loading them all.

Lesson from MCP: putting every tool definition in context cost ~55k tokens for
five servers and made selection *worse*. MHP therefore never hands an agent the
full device list. It hands it a search box.

    directory/search {query, class, tags, location, state, limit, live}  -> ranked cards
    directory/get    {id}                                                -> card + target, live state
    directory/stats  {}                                                  -> counts by class / state

A card is ~40 tokens. A full descriptor is loaded only for the device the agent
picks, via device/describe on that device (see Driver.rpc_device_describe).

State is never trusted from the index. The directory indexes everything about
a device that is *static* (identity, location, tags, capability names) and
asks the device itself for its state at query time: the top candidates of a
search are pinged in parallel with a short timeout, and ``directory/get``
always pings. A device that does not answer is reported as ``unreachable``.
Ranking is a small BM25 over id, class, make, model, location, tags, notes
and the names of signals/settings/actions.
"""
from __future__ import annotations

import json
import math
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from . import PROTOCOL_VERSION
from .driver import MethodNotFound, UnknownName

_TOKEN = re.compile(r"[a-z0-9]+")
PING_TIMEOUT_S = 0.5        # per device, at search time
STATE_TTL_S = 2.0           # a ping this recent is reused
CANDIDATES_PER_RESULT = 4   # ping this many times `limit` candidates before applying a state filter


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(str(text).lower().replace("_", " "))


def card_text(card: dict) -> str:
    return " ".join(str(card.get(k, "")) for k in ("id", "class", "make", "model", "location", "description", "notes")) + " " + \
        " ".join(card.get("tags", [])) + " " + " ".join(card.get("signals", []) + card.get("settings", []) + card.get("actions", []))


class Directory:
    """In-memory index of device cards with live state probing."""

    def __init__(self, ping_timeout: float = PING_TIMEOUT_S, state_ttl: float = STATE_TTL_S):
        self.cards: dict[str, dict] = {}                 # id -> card (static fields)
        self.targets: dict[str, str] = {}                # id -> connection target
        self._probes: dict[str, Callable[[], str]] = {}  # id -> callable returning live state
        self._clients: dict[str, Any] = {}               # id -> cached Device client for remote pings
        self._state: dict[str, tuple[str, float]] = {}   # id -> (state, when)
        self._tf: dict[str, Counter] = {}
        self._df: Counter = Counter()
        self._len: dict[str, int] = {}
        self.ping_timeout, self.state_ttl = ping_timeout, state_ttl
        self._pool = ThreadPoolExecutor(64)
        self.updated = time.time()

    # ---- building --------------------------------------------------------
    def add(self, card: dict, target: str, probe: Callable[[], str] | None = None) -> None:
        card = dict(card)
        indexed_state = card.pop("state", None)          # state is not part of the index
        cid = card["id"]
        if cid in self._tf:
            for t in self._tf[cid]:
                self._df[t] -= 1
        toks = _tokens(card_text(card))
        self.cards[cid], self.targets[cid] = card, target
        self._tf[cid], self._len[cid] = Counter(toks), len(toks)
        for t in self._tf[cid]:
            self._df[t] += 1
        if probe is not None:
            self._probes[cid] = probe
        if indexed_state:
            self._state[cid] = (indexed_state, 0.0)      # known once, already stale
        self.updated = time.time()

    def add_driver(self, driver, target: str) -> None:
        """In-process driver: probe its state directly, no transport."""
        self.add(driver.card(), target, probe=lambda: driver.state)

    @classmethod
    def from_targets(cls, targets: dict[str, str], workers: int = 32) -> "Directory":
        """Connect to each target once for its card; keep the client for pings."""
        from .client import connect
        d = cls()

        def fetch(item):
            name, target = item
            dev = connect(target, name)
            return dev.call("device/describe", {"detail": "card"}), target, dev

        with ThreadPoolExecutor(workers) as ex:
            for card, target, dev in ex.map(fetch, targets.items()):
                d.add(card, target)
                d._clients[card["id"]] = dev
        return d

    @classmethod
    def from_manifest(cls, path: str) -> "Directory":
        d = cls()
        for row in json.load(open(path)):
            d.add(row["card"], row["target"])
        return d

    def save_manifest(self, path: str) -> None:
        json.dump([{"card": c, "target": self.targets[i]} for i, c in self.cards.items()], open(path, "w"), indent=1)

    # ---- live state ------------------------------------------------------
    def _ping(self, cid: str) -> str:
        if cid in self._probes:
            return self._probes[cid]()
        from .client import connect
        dev = self._clients.get(cid)
        if dev is None:
            dev = self._clients[cid] = connect(self.targets[cid], cid)
        return dev.call("ping")["state"]

    def live_state(self, cid: str) -> str:
        cached = self._state.get(cid)
        if cached and time.time() - cached[1] < self.state_ttl:
            return cached[0]
        fut = self._pool.submit(self._ping, cid)
        try:
            state = fut.result(timeout=self.ping_timeout)
        except Exception:                                 # noqa: BLE001  timeout, refused, protocol error
            self._clients.pop(cid, None)                  # reconnect next time
            state = "unreachable"
        self._state[cid] = (state, time.time())
        return state

    def refresh(self, ids: list[str]) -> dict[str, str]:
        """Ping many devices in parallel; returns id -> state."""
        futs = {cid: self._pool.submit(self.live_state, cid) for cid in ids}
        return {cid: f.result() for cid, f in futs.items()}

    # ---- search ----------------------------------------------------------
    def search(self, query: str = "", *, cls: str | None = None, tags: list[str] | None = None,
               location: str | None = None, state: str | None = None, limit: int = 5,
               live: bool = True) -> list[dict]:
        n = max(1, len(self.cards))
        avg = (sum(self._len.values()) / n) if n else 1
        q = _tokens(query)
        scored = []
        for cid, card in self.cards.items():
            if cls and card.get("class") != cls:
                continue
            if tags and not set(tags) <= set(card.get("tags", [])):
                continue
            if location and location.lower() not in str(card.get("location", "")).lower():
                continue
            s = 0.0
            tf = self._tf[cid]
            for t in q:
                if t in tf:
                    idf = math.log(1 + (n - self._df[t] + 0.5) / (self._df[t] + 0.5))
                    s += idf * tf[t] * 2.2 / (tf[t] + 1.2 * (0.25 + 0.75 * self._len[cid] / avg))
            if q and s == 0:
                continue
            scored.append((s, cid))
        scored.sort(key=lambda x: (-x[0], x[1]))

        # Ask the top candidates how they are right now, then apply the state filter.
        pool = scored[: limit * CANDIDATES_PER_RESULT] if state else scored[:limit]
        states = self.refresh([cid for _, cid in pool]) if live else \
            {cid: self._state.get(cid, ("unknown", 0))[0] for _, cid in pool}
        out = []
        for s, cid in pool:
            st = states[cid]
            if state and st != state:
                continue
            out.append({**self.cards[cid], "state": st, "target": self.targets[cid], "score": round(s, 3)})
            if len(out) == limit:
                break
        return out

    def stats(self) -> dict:
        return {"devices": len(self.cards), "updated": self.updated,
                "by_class": dict(Counter(c["class"] for c in self.cards.values())),
                "by_state": dict(Counter(s for s, _ in self._state.values())),
                "state_note": "by_state counts devices pinged recently; unpinged devices are absent"}

    # ---- RPC surface (so a Directory can be served like a device) --------
    def rpc(self, method: str, params: dict, client: str = "anon") -> Any:
        p = params or {}
        if method == "initialize":
            return {"protocolVersion": PROTOCOL_VERSION, "role": "directory",
                    "capabilities": {"search": True, "liveState": True, "devices": len(self.cards)}}
        if method == "ping":
            return {"ok": True, "state": "idle"}
        if method == "directory/search":
            return {"results": self.search(p.get("query", ""), cls=p.get("class"), tags=p.get("tags"),
                                          location=p.get("location"), state=p.get("state"),
                                          limit=int(p.get("limit", 5)), live=p.get("live", True))}
        if method == "directory/get":
            cid = p["id"]
            if cid not in self.cards:
                raise UnknownName(f"no device {cid}")
            return {**self.cards[cid], "state": self.live_state(cid), "target": self.targets[cid]}
        if method == "directory/stats":
            return self.stats()
        raise MethodNotFound(f"unknown method {method}")

    # so transport.serve_http/serve_stdio can host a directory unchanged
    descriptor = {"device": {"id": "directory", "class": "directory"}}
    subscribers: list = []
