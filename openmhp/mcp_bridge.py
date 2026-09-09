"""MHP -> MCP bridge: the first of the three control surfaces.

Designed for labs with thousands of devices. The tool surface is EIGHT tools,
constant in the number of devices, and the agent's context never holds more
than the cards it searched for and the one descriptor it chose to open.

    mhp_find      search the directory        (deferred loading: cards, not descriptors)
    mhp_describe  open one descriptor         (card | summary | full | select one action)
    mhp_read / mhp_write / mhp_invoke / mhp_job / mhp_estop
    mhp_run       run an orchestration script (programmatic calling: intermediate data
                  stays in the script; only what it prints reaches the model)

Every tool carries input_examples, because a schema cannot teach conventions.

    mhp-mcp --directory http://directory:18900                  # big lab
    mhp-mcp thermo=http://bench:18921 arm=local:openmhp.devices.sim_arm:SimArm   # small lab
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import threading
import traceback

from .client import Lab, RemoteError
from .directory import Directory

TOOLS = [
    {"name": "mhp_find",
     "description": ("Search the lab directory for devices. Returns compact cards (id, class, location, one-line notes, "
                     "names of signals/settings/actions, state). Use this FIRST; never assume a device id. "
                     "Then open the one you need with mhp_describe. Filters: class, tags, location, state='idle'."),
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string", "description": "free text: what you need the device to do"},
         "class": {"type": "string"}, "tags": {"type": "array", "items": {"type": "string"}},
         "location": {"type": "string"}, "state": {"type": "string", "enum": ["idle", "busy", "fault", "estop"]},
         "limit": {"type": "integer", "default": 5}}},
     "input_examples": [
         {"query": "heat a 96-well plate to 95 C", "class": "thermocycler", "state": "idle"},
         {"query": "move plates between deck and thermocycler", "location": "bay 3"},
         {"class": "microscope", "tags": ["confocal"], "limit": 10}]},
    {"name": "mhp_describe",
     "description": ("Open a device, one level at a time. detail='summary' (default) returns the card, the owner's "
                     "operating INSTRUCTIONS (read them), a slim table of every signal/setting/action with units, limits "
                     "and approval level, and the list of bundled resources. select={'actions':['name']} loads the full "
                     "spec (params, examples, notes) of just the items you will use. resource='references/x.md' or "
                     "'scripts/x.py' reads one bundled file (manual excerpts, SOPs, ready-made mhp_run scripts). "
                     "detail='full' dumps the whole descriptor; rarely needed."),
     "inputSchema": {"type": "object", "properties": {
         "device": {"type": "string"}, "detail": {"type": "string", "enum": ["card", "summary", "full"]},
         "select": {"type": "object", "description": "{'signals'|'settings'|'actions': [names]}"},
         "resource": {"type": "string", "description": "path of a bundled resource to read"}},
                     "required": ["device"]},
     "input_examples": [
         {"device": "thermocycler-01"},
         {"device": "thermocycler-01", "select": {"actions": ["run_protocol"], "settings": ["target_temperature"]}},
         {"device": "thermocycler-01", "resource": "references/protocols.md"},
         {"device": "arm-01", "resource": "scripts/plate_to_thermocycler.py"}]},
    {"name": "mhp_read", "description": "Read one or more signals. Omit names to read all.",
     "inputSchema": {"type": "object", "properties": {"device": {"type": "string"},
                                                      "names": {"type": "array", "items": {"type": "string"}}}, "required": ["device"]},
     "input_examples": [{"device": "thermocycler-01", "names": ["block_temperature", "lid_closed"]}, {"device": "arm-01"}]},
    {"name": "mhp_write",
     "description": ("Write a setting (setpoint). The driver enforces descriptor limits and refuses out-of-range values with "
                     "LimitViolation. Settings with approval=confirm need approved=true, which you may pass only after a human "
                     "has confirmed. dryRun=true checks every gate without touching hardware."),
     "inputSchema": {"type": "object", "properties": {"device": {"type": "string"}, "name": {"type": "string"}, "value": {},
                                                      "approved": {"type": "boolean"}, "dryRun": {"type": "boolean"}},
                     "required": ["device", "name", "value"]},
     "input_examples": [{"device": "thermocycler-01", "name": "target_temperature", "value": 95},
                        {"device": "arm-01", "name": "speed", "value": 30, "dryRun": True}]},
    {"name": "mhp_invoke",
     "description": ("Invoke an action; returns a job. Long actions run on the device without you; poll with mhp_job or pass "
                     "wait=true for short ones. Interlocks and approval levels from the descriptor are enforced."),
     "inputSchema": {"type": "object", "properties": {"device": {"type": "string"}, "name": {"type": "string"},
                                                      "params": {"type": "object"}, "approved": {"type": "boolean"},
                                                      "dryRun": {"type": "boolean"}, "wait": {"type": "boolean"}},
                     "required": ["device", "name"]},
     "input_examples": [
         {"device": "arm-01", "name": "home", "wait": True},
         {"device": "arm-01", "name": "pick_plate", "params": {"location": "deck_A1"}, "wait": True},
         {"device": "thermocycler-01", "name": "run_protocol",
          "params": {"steps": [{"temp": 95, "hold_s": 30}, {"temp": 58, "hold_s": 30}, {"temp": 72, "hold_s": 45}], "cycles": 30}},
         {"device": "thermocycler-01", "name": "open_lid", "approved": True}]},
    {"name": "mhp_job", "description": "Get status/progress/result of a job, or cancel it.",
     "inputSchema": {"type": "object", "properties": {"device": {"type": "string"}, "id": {"type": "string"},
                                                      "cancel": {"type": "boolean"}}, "required": ["device", "id"]},
     "input_examples": [{"device": "thermocycler-01", "id": "job_04324008"}, {"device": "thermocycler-01", "id": "job_04324008", "cancel": True}]},
    {"name": "mhp_estop",
     "description": "EMERGENCY STOP one device, or every device this session has touched with device='*'. Always allowed. Use whenever anything looks unsafe.",
     "inputSchema": {"type": "object", "properties": {"device": {"type": "string"}, "reason": {"type": "string"}}, "required": ["device"]},
     "input_examples": [{"device": "arm-01", "reason": "person inside keep-out ring"}, {"device": "*", "reason": "smoke"}]},
    {"name": "mhp_run",
     "description": ("Run a Python orchestration script against the lab and return ONLY what it prints (capped). Use for "
                     "multi-step protocols, loops, or anything that would otherwise pull large intermediate data (traces, "
                     "images, thousands of readings) into your context. The script sees `lab` (Lab): lab.find(query, cls=...), "
                     "lab['device-id'].read/write/invoke/wait/status. Safety gates still apply to every call the script makes."),
     "inputSchema": {"type": "object", "properties": {"script": {"type": "string"},
                                                      "timeout_s": {"type": "number", "default": 600}}, "required": ["script"]},
     "input_examples": [
         {"script": "t = lab['thermocycler-01']\nwith t:\n    j = t.wait(t.invoke('run_protocol', steps=[{'temp':95,'hold_s':30}], cycles=5))\nprint(j['result'])"},
         {"script": ("import statistics\nreadings = [lab['thermocycler-01'].read('block_temperature') for _ in range(200)]\n"
                     "print('mean', statistics.mean(readings), 'sd', statistics.pstdev(readings))"), "timeout_s": 60}]},
]

RUN_OUTPUT_CAP = 8000   # chars of script stdout returned to the model


class Bridge:
    def __init__(self, targets: dict[str, str] | None = None, directory=None):
        if directory is None and targets:
            directory = Directory.from_targets(targets)      # cards only; connections are lazy
        self.lab = Lab(targets, directory)

    # ---- tools ------------------------------------------------------------
    def call_tool(self, name: str, a: dict):
        lab = self.lab
        if name == "mhp_find":
            return lab.find(a.get("query", ""), limit=int(a.get("limit", 5)), cls=a.get("class"),
                            tags=a.get("tags"), location=a.get("location"), state=a.get("state"))
        if name == "mhp_estop":
            return lab.estop_all(a.get("reason", "")) if a["device"] == "*" else lab[a["device"]].estop(a.get("reason", ""))
        if name == "mhp_run":
            return self.run_script(a["script"], float(a.get("timeout_s", 600)))
        dev = lab[a["device"]]
        if name == "mhp_describe":
            if a.get("resource"):
                return dev.call("resources/read", {"path": a["resource"]})
            p = {"detail": a.get("detail", "summary")}
            if a.get("select"):
                p["select"] = a["select"]
            return dev.call("device/describe", p)
        if name == "mhp_read":
            return dev.call("signals/read", {"names": a["names"]} if a.get("names") else {})
        if name == "mhp_write":
            return dev.write(a["name"], a["value"], a.get("approved", False), a.get("dryRun", False))
        if name == "mhp_invoke":
            job = dev.invoke(a["name"], a.get("approved", False), a.get("dryRun", False), **a.get("params", {}))
            return dev.wait(job) if a.get("wait") and not a.get("dryRun") else job
        if name == "mhp_job":
            return dev.cancel(a["id"]) if a.get("cancel") else dev.status(a["id"])
        raise ValueError(f"unknown tool {name}")

    def run_script(self, script: str, timeout_s: float) -> dict:
        """Programmatic tool calling. Reference implementation runs in-process so
        device state is shared; production hosts should sandbox this."""
        buf, result = io.StringIO(), {}

        def target():
            try:
                with contextlib.redirect_stdout(buf):
                    exec(compile(script, "<mhp_run>", "exec"), {"lab": self.lab, "__name__": "__mhp_run__"})
                result["ok"] = True
            except RemoteError as e:                        # a safety gate refused something
                result["ok"], result["error"] = False, {"mhpError": {"code": e.code, "message": e.message, "data": e.data}}
            except Exception as e:                          # noqa: BLE001
                tb = traceback.extract_tb(e.__traceback__)
                line = next((f.lineno for f in reversed(tb) if f.filename == "<mhp_run>"), None)
                result["ok"], result["error"] = False, f"{type(e).__name__}: {e}" + (f" (script line {line})" if line else "")

        t = threading.Thread(target=target, daemon=True)
        t.start(); t.join(timeout_s)
        if t.is_alive():
            result.update(ok=False, error=f"script still running after {timeout_s}s; devices keep their jobs, check with mhp_job")
        out = buf.getvalue()
        return {**result, "stdout": out[:RUN_OUTPUT_CAP], "truncated": len(out) > RUN_OUTPUT_CAP}

    # ---- MCP protocol (stdio, newline-delimited JSON-RPC) ------------------
    def handle(self, msg: dict):
        m, p, mid = msg.get("method"), msg.get("params") or {}, msg.get("id")
        if m == "initialize":
            return self._ok(mid, {"protocolVersion": p.get("protocolVersion", "2025-06-18"),
                                  "capabilities": {"tools": {}, "resources": {}},
                                  "serverInfo": {"name": "openmhp-bridge", "version": "0.2.0"}})
        if m == "notifications/initialized" or mid is None:
            return None
        if m == "ping":
            return self._ok(mid, {})
        if m == "tools/list":
            return self._ok(mid, {"tools": TOOLS})
        if m == "resources/list":            # only devices this session has opened; the directory is the catalogue
            res = []
            for n, dev in self.lab.devices.items():
                res.append({"uri": f"mhp://{n}/descriptor", "name": f"{n} descriptor", "mimeType": "application/json"})
                for path in dev.call("resources/list")["resources"]:
                    res.append({"uri": f"mhp://{n}/{path}", "name": f"{n} {path}", "mimeType": "text/plain"})
            return self._ok(mid, {"resources": res})
        if m == "resources/read":
            _, rest = p["uri"].split("//", 1)
            n, _, path = rest.partition("/")
            if path == "descriptor":
                text, mime = json.dumps(self.lab[n].describe(), indent=2), "application/json"
            else:
                text, mime = self.lab[n].call("resources/read", {"path": path})["text"], "text/plain"
            return self._ok(mid, {"contents": [{"uri": p["uri"], "mimeType": mime, "text": text}]})
        if m == "tools/call":
            try:
                res = self.call_tool(p["name"], p.get("arguments") or {})
                return self._ok(mid, {"content": [{"type": "text", "text": json.dumps(res, indent=1)}]})
            except RemoteError as e:
                txt = json.dumps({"mhpError": {"code": e.code, "message": e.message, "data": e.data}})
                return self._ok(mid, {"content": [{"type": "text", "text": txt}], "isError": True})
            except Exception as e:                # noqa: BLE001
                return self._ok(mid, {"content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}], "isError": True})
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"unknown method {m}"}}

    @staticmethod
    def _ok(mid, result):
        return {"jsonrpc": "2.0", "id": mid, "result": result}


def serve_mcp_http(bridge: Bridge, host: str = "127.0.0.1", port: int = 18800) -> None:
    """MCP Streamable HTTP (JSON responses): POST /mcp. Lets any harness that speaks
    HTTP MCP (not just stdio launchers) attach to the lab."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_POST(self):
            if self.path.rstrip("/") not in ("/mcp", ""):
                self.send_response(404); self.end_headers(); return
            n = int(self.headers.get("Content-Length", 0))
            try:
                msg = json.loads(self.rfile.read(n))
            except json.JSONDecodeError:
                self.send_response(400); self.end_headers(); return
            resp = bridge.handle(msg)
            body = json.dumps(resp).encode() if resp is not None else b""
            self.send_response(200 if resp is not None else 202)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body)
        def do_GET(self):                       # no server-initiated stream in this reference build
            self.send_response(405); self.end_headers()

    print(f"MHP MCP bridge listening on http://{host}:{port}/mcp", file=sys.stderr)
    ThreadingHTTPServer((host, port), H).serve_forever()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    directory, http_port = None, None
    if "--directory" in argv:
        i = argv.index("--directory")
        from .client import connect
        directory = connect(argv[i + 1], "directory")
        argv = argv[:i] + argv[i + 2:]
    if "--http" in argv:
        i = argv.index("--http")
        http_port = int(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    targets = dict(arg.split("=", 1) for arg in argv)
    if not targets and directory is None:
        print(__doc__, file=sys.stderr)
        return 2
    bridge = Bridge(targets, directory)
    if http_port:
        return serve_mcp_http(bridge, port=http_port)
    for line in sys.stdin:
        if not line.strip():
            continue
        resp = bridge.handle(json.loads(line))
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    sys.exit(main())
