"""The run agent's own tools, as a small MCP server (stdio) started inside its session:

    ask_scientist   a question for the scientist, with what was tried and what the run does meanwhile
    report          a progress note for the scientist
    finish          the run is done: a summary and suggested next experiments

Each tool calls the gateway with the run's token (OPENMHP_RUN_TOKEN, OPENMHP_GATEWAY, SSL_CERT_FILE), so
it can speak only for its own run. The answers come back later, as a new turn of the session.
"""
from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.error
import urllib.request

TOOLS = [
    {"name": "ask_scientist",
     "description": "Ask the scientist something only they can answer or do: a decision outside the charter, a "
                    "judgement on a strange result, or a task in the lab (re-seat a cell, refill a reservoir). Say what "
                    "you tried. Their answer arrives as a later turn; until then do what `meanwhile` says.",
     "inputSchema": {"type": "object", "properties": {
         "question": {"type": "string"},
         "tried": {"type": "string", "description": "what you already did or checked"},
         "meanwhile": {"type": "string", "enum": ["wait", "continue"],
                       "description": "wait: hold the instruments safe until answered; continue: keep working on other parts"},
         "needs_lab": {"type": "boolean", "description": "true when someone has to go to the lab"}},
         "required": ["question", "meanwhile"]}},
    {"name": "report",
     "description": "A short progress note for the scientist: what was done, what was learned, what is next.",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
    {"name": "finish",
     "description": "End the run: the objective is met, a stop condition holds, or the budget is spent. Leave the "
                    "instruments in the charter's cleanup state first. Results must already be in the out/ folder.",
     "inputSchema": {"type": "object", "properties": {
         "summary": {"type": "string"},
         "next_experiments": {"type": "array", "items": {"type": "string"}},
         "outcome": {"type": "string", "enum": ["objective met", "stop condition", "budget spent", "could not continue"]}},
         "required": ["summary", "outcome"]}},
]


def call(path: str, body: dict) -> dict:
    base = os.environ["OPENMHP_GATEWAY"].rstrip("/")
    ctx = ssl.create_default_context(cafile=os.environ.get("SSL_CERT_FILE") or None)
    ctx.check_hostname = False                           # the certificate file is the gateway's own: it is the pin
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {os.environ['OPENMHP_RUN_TOKEN']}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": (e.read() or b"").decode(errors="replace")[:500]}


def handle(msg: dict) -> dict | None:
    mid, method, p = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": p.get("protocolVersion", "2025-06-18"),
                                                        "capabilities": {"tools": {}},
                                                        "serverInfo": {"name": "openmhp-run", "version": "1"}}}
    if mid is None:
        return None
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name, args = p.get("name"), p.get("arguments") or {}
        if name not in ("ask_scientist", "report", "finish"):
            return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": f"unknown tool {name}"}], "isError": True}}
        ans = call(f"/runs/{name}", args)
        return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": json.dumps(ans)}],
                                                        "isError": not ans.get("ok", False)}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"unknown method {method}"}}


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            out = handle(json.loads(line))
        except Exception as e:                           # noqa: BLE001
            out = {"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": str(e)}}
        if out is not None:
            sys.stdout.write(json.dumps(out) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
