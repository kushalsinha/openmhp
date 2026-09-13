"""MHP -> MCP bridge: the first of the three control surfaces.

Designed for labs with thousands of devices. The tool surface is eight operating
tools plus three for the lab (mhp_lab, mhp_data, mhp_method), constant in the
number of devices; the agent's context never holds more than the cards it
searched for and the one descriptor it chose to open.

    mhp_find      search the directory        (deferred loading: cards, not descriptors)
    mhp_describe  open one descriptor         (card | summary | full | select one action | a resource)
    mhp_read / mhp_write / mhp_invoke / mhp_job / mhp_estop
    mhp_run       run a script or recipe      (plan=true rehearses it; background=true for long runs)
    mhp_lab       the lab: status, scan, add, onboard, recipes, safety card, events
    mhp_data      runs and their files (readings, images, logs); updates pushed by devices
    mhp_method    methods: named, versioned parameter sets per project and compound

Every tool carries input_examples, because a schema cannot teach conventions.
Human confirmation uses MCP elicitation when the harness supports it.

    mhp-mcp                                                     # your lab: ~/.openmhp/fleet.json (mhp_lab manages it)
    mhp-mcp --directory http://directory:18900                  # big lab with a shared directory
    mhp-mcp thermo=http://bench:18921 arm=pkg:./devices/arm-01  # explicit devices
"""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import hmac
import os
import secrets
import uuid

from . import __version__
from .client import Lab, RemoteError, _inprocess, _remote, drop_inprocess
from .directory import Directory
from .driver import ApprovalRequired
from .fleet import safe_id
from .runs import PlanLab, RunLog, Runs

SUPPORTED_MCP_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
RESULT_CAP = 4000        # bytes of a job result kept in logs and update buffers; the full result stays on the job


def _cap(result):
    """A job result small enough for a log line: bulky arrays (a chromatogram trace) are replaced by their size."""
    if result is None:
        return None
    try:
        if len(json.dumps(result, default=str)) <= RESULT_CAP:
            return result
    except (TypeError, ValueError):
        return str(result)[:RESULT_CAP]
    if isinstance(result, dict):
        out = {}
        for k, v in result.items():
            s = json.dumps(v, default=str)
            out[k] = v if len(s) <= 800 else f"<{type(v).__name__} of {len(v) if hasattr(v, '__len__') else '?'} items, {len(s)} bytes; read the job result>"
        return out
    return str(result)[:RESULT_CAP]
_OBSERVED_KINDS = {"settings/write": "write", "actions/invoke": "invoke", "signals/read": "read", "jobs/pause": "job/pause",
                   "jobs/resume": "job/resume", "jobs/cancel": "job/cancel", "safety/estop": "estop", "safety/reset": "reset",
                   "session/acquire": "lease/acquire", "session/release": "lease/release"}

TOOLS = [
    {"name": "mhp_find",
     "description": ("Search the lab directory for devices. Returns compact cards (id, class, location, description, "
                     "names of signals/settings/actions, live state). Use this FIRST; never assume a device id. "
                     "Then open the one you need with mhp_describe. Filters: class, tags, location, state='idle'. "
                     "Empty result? mhp_lab op='status' says how to add devices."),
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
     "description": ("Write a setting (setpoint). The driver checks the value's type and the descriptor limits and refuses "
                     "anything else (InvalidValue, LimitViolation). Settings with approval=confirm need a person's yes: the server "
                     "asks them itself through MCP elicitation; you cannot approve on their behalf, and without elicitation such "
                     "settings are unavailable. dryRun=true checks every gate without touching hardware."),
     "inputSchema": {"type": "object", "properties": {"device": {"type": "string"}, "name": {"type": "string"}, "value": {},
                                                      "dryRun": {"type": "boolean"}},
                     "required": ["device", "name", "value"]},
     "input_examples": [{"device": "thermocycler-01", "name": "target_temperature", "value": 95},
                        {"device": "arm-01", "name": "speed", "value": 30, "dryRun": True}]},
    {"name": "mhp_invoke",
     "description": ("Invoke an action; returns a job. Long actions run on the device without you; poll with mhp_job or pass "
                     "wait=true for short ones. Parameters, interlocks and approval levels from the descriptor are enforced; "
                     "confirm-gated actions are put to a person by the server through elicitation, and you cannot approve them. "
                     "A job in state waiting_operator is waiting for a person at the instrument."),
     "inputSchema": {"type": "object", "properties": {"device": {"type": "string"}, "name": {"type": "string"},
                                                      "params": {"type": "object"}, "dryRun": {"type": "boolean"},
                                                      "wait": {"type": "boolean"},
                                                      "method": {"type": "object", "description": "run a saved method instead of raw params: {name, version?, overrides?}"},
                                                      "project": {"type": "string", "description": "the project this run belongs to (recorded with the job)"},
                                                      "compound": {"type": "string", "description": "what is being run (lets the device point at its methods)"}},
                     "required": ["device", "name"]},
     "input_examples": [
         {"device": "arm-01", "name": "home", "wait": True},
         {"device": "arm-01", "name": "pick_plate", "params": {"location": "deck_A1"}, "wait": True},
         {"device": "thermocycler-01", "name": "run_protocol",
          "params": {"steps": [{"temp": 95, "hold_s": 30}, {"temp": 58, "hold_s": 30}, {"temp": 72, "hold_s": 45}], "cycles": 30}},
         {"device": "thermocycler-01", "name": "open_lid", "wait": True}]},
    {"name": "mhp_job", "description": "Get status/progress/result of a job; or pause, resume or cancel it. Pause lets a person step in without an e-stop. Actions that cannot pause or cancel safely refuse (NotSupported); mhp_estop always works.",
     "inputSchema": {"type": "object", "properties": {"device": {"type": "string"}, "id": {"type": "string"},
                                                      "op": {"type": "string", "enum": ["status", "pause", "resume", "cancel"]},
                                                      "cancel": {"type": "boolean", "description": "legacy: same as op='cancel'"}}, "required": ["device", "id"]},
     "input_examples": [{"device": "thermocycler-01", "id": "job_04324008"}, {"device": "thermocycler-01", "id": "job_04324008", "op": "pause"},
                        {"device": "thermocycler-01", "id": "job_04324008", "op": "cancel"}]},
    {"name": "mhp_estop",
     "description": "EMERGENCY STOP one device, or every device this session has touched with device='*'. Always allowed. Use whenever anything looks unsafe.",
     "inputSchema": {"type": "object", "properties": {"device": {"type": "string"}, "reason": {"type": "string"}}, "required": ["device"]},
     "input_examples": [{"device": "arm-01", "reason": "person inside keep-out ring"}, {"device": "*", "reason": "smoke"}]},
    {"name": "mhp_run",
     "description": ("Run a Python orchestration script, or a named recipe, against the lab. Returns ONLY what it prints (capped), "
                     "so large intermediate data never enters your context. The script sees `lab`, `run_dir` (a folder to save "
                     "files into, later readable with mhp_data) and, for recipes, `PARAMS`. "
                     "plan=true REHEARSES the script: reads are real, every write and invoke is a dry run through all safety gates, "
                     "no hardware moves, and you get the ordered plan with the steps a human must confirm and the steps that would be "
                     "refused. Show the plan to the user before the real run of anything that heats or moves. "
                     "background=true starts a long run and returns immediately; follow it with mhp_data. "
                     "Every call the script makes passes the same gates as a direct tool call."),
     "inputSchema": {"type": "object", "properties": {
         "script": {"type": "string"}, "recipe": {"type": "string", "description": "name from mhp_lab op='recipes'"},
         "params": {"type": "object", "description": "recipe PARAMS overrides"}, "name": {"type": "string", "description": "label for the run"},
         "plan": {"type": "boolean"}, "background": {"type": "boolean"}, "timeout_s": {"type": "number", "default": 600}}},
     "input_examples": [
         {"recipe": "pcr-with-plate-transfer", "params": {"cycles": 30, "plate_slot": "deck_A1"}, "plan": True},
         {"recipe": "pcr-with-plate-transfer", "params": {"cycles": 30, "plate_slot": "deck_A1"}, "name": "pcr plate 7"},
         {"recipe": "periodic-readings", "params": {"device": "incubator-02", "signals": ["temperature", "co2"], "hours": 12}, "background": True},
         {"script": "t = lab['thermocycler-01']\nwith t:\n    j = t.wait(t.invoke('run_protocol', steps=[{'temp':95,'hold_s':30}], cycles=5))\nprint(j['result'])"},
         {"script": ("import statistics\nreadings = [lab['thermocycler-01'].read('block_temperature') for _ in range(200)]\n"
                     "print('mean', statistics.mean(readings), 'sd', statistics.pstdev(readings))"), "timeout_s": 60}]},
    {"name": "mhp_lab",
     "description": ("Manage the lab itself (not a device). START HERE with op='status' when the user wants to set up or add "
                     "instruments: it says what to do next. op='onboard' runs a guided interview for a new instrument: the server "
                     "returns questions to ask the human (`ask`) and the shape to return (`shape`); send answers back with "
                     "answers={...} and id=...; if the user has a manual or SOP, read it and submit everything you can in ONE answers "
                     "call, then confirm limits with the human; when complete the SERVER WRITES the whole device package, validates it, "
                     "produces a SAFETY CARD to read back, and tells you to op='add' it. Hand-operated ('manual') and serial/USB "
                     "('serial') instruments need no code. op='scan' finds MHP devices on the network not yet in the lab (hosts=[...] "
                     "to probe specific machines). op='add' registers a target: http://host:port, a package folder, a package id under "
                     "~/.openmhp/devices, or github:owner/repo/path (community packages; sim=true adds its simulated twin for rehearsal). "
                     "op='registry' searches known community packages. op='recipes' searches tested cross-instrument procedures to run "
                     "with mhp_run. op='safety_card' reviews a device before first use. op='events' returns what happened since a "
                     "sequence number (job finished, e-stop, refusals). op='location' records where an instrument stands (id, location); ask the human for it after adding a shared package, because a package cannot know. "
                     "op='list'/'remove'/'reload'/'home' manage membership (reload after a package's files change; release hands this session's leases back); op='new'/'write'/"
                     "'validate' are for agents that write package files themselves."),
     "inputSchema": {"type": "object", "properties": {
         "op": {"type": "string", "enum": ["status", "scan", "add", "onboard", "recipes", "registry", "safety_card", "events",
                                           "location", "remove", "reload", "release", "list", "new", "write", "validate", "home"]},
         "force": {"type": "boolean", "description": "remove/reload: proceed even if the device has active jobs"},
         "answers": {"type": "object", "description": "onboard: {question key: answer in the given shape}"},
         "target": {"type": "string", "description": "add: http://host:port | pkg:/folder | folder | package id | github:owner/repo/path"},
         "sim": {"type": "boolean", "description": "add: use the package's simulated twin"},
         "location": {"type": "string", "description": "add/location: where the instrument stands, e.g. 'bay 3, fume hood 2'"},
         "id": {"type": "string", "description": "device id (remove/new/write/validate/safety_card/onboard)"},
         "query": {"type": "string", "description": "recipes/registry: what you are looking for"},
         "since": {"type": "integer", "description": "events: last seen seq"},
         "hosts": {"type": "array", "items": {"type": "string"}, "description": "scan: hosts to probe besides localhost"},
         "class": {"type": "string"}, "description": {"type": "string"},
         "files": {"type": "object", "description": "write: {relative path: text}"}},
                     "required": ["op"]},
     "input_examples": [
         {"op": "status"}, {"op": "scan"}, {"op": "add", "target": "http://192.168.1.40:18921"},
         {"op": "onboard"},
         {"op": "onboard", "id": "c-mag-hs-7-01", "answers": {"make": "IKA", "model": "C-MAG HS 7", "nickname": "hood hotplate", "kind": "serial",
                                                              "port": "/dev/ttyUSB0", "location": "fume hood 2", "tags": ["heating", "stirring"], "class": "hotplate"}},
         {"op": "recipes", "query": "pcr with plate transfer"},
         {"op": "registry", "query": "ika hotplate"}, {"op": "add", "target": "github:kushalsinha/openmhp/packages/ika-c-mag-hs7"},
         {"op": "add", "target": "github:kushalsinha/openmhp/packages/ika-c-mag-hs7", "sim": True},
         {"op": "location", "id": "ika-c-mag-hs7-01", "location": "fume hood 2"},
         {"op": "safety_card", "id": "c-mag-hs-7-01"}, {"op": "events", "since": 0}, {"op": "list"}]},
    {"name": "mhp_data",
     "description": ("Runs and their files. op='runs' lists runs (newest first, with state). op='list' lists files a run saved to its "
                     "run_dir (readings.csv, images, logs, events.jsonl: what its devices pushed while it ran). op='read' returns a text "
                     "file (capped) from a run: run='latest' or an id, path='stdout.txt' for the script output, 'readings.csv' for data. "
                     "op='log' returns the lab's run log entries. op='updates' returns what a device PUSHED recently without being asked: "
                     "signal updates (a GC's last_result after every injection), job progress and completions; device=<id>, "
                     "optional signal=<name>, since=<ts>. Use it in an adaptive loop to see each new result before deciding the next run."),
     "inputSchema": {"type": "object", "properties": {
         "op": {"type": "string", "enum": ["runs", "list", "read", "log", "updates"]},
         "device": {"type": "string", "description": "updates: device id"}, "signal": {"type": "string", "description": "updates: only this signal"},
         "run": {"type": "string", "description": "run id or 'latest'"}, "path": {"type": "string"},
         "since": {"type": "integer"}, "limit": {"type": "integer"}}, "required": ["op"]},
     "input_examples": [{"op": "runs"}, {"op": "list", "run": "latest"}, {"op": "read", "run": "latest", "path": "stdout.txt"},
                        {"op": "read", "run": "20260909-1402-a1b2", "path": "readings.csv"}, {"op": "log", "since": 0, "limit": 50},
                        {"op": "updates", "device": "gc-01", "signal": "last_result", "limit": 5}]},
    {"name": "mhp_method",
     "description": ("Methods: the instrument's own named, versioned parameter sets (an HPLC or GC method, a PCR program), kept on "
                     "the device per project and filed by compound. Any device answers; only devices whose descriptor marks an action "
                     "methods: true keep them (mhp_describe summary shows `methods`). BEFORE invoking a method-driven action: "
                     "op='find' with the compound and the project. `choice`='one': run it. 'several': ASK THE PERSON which one "
                     "(an autonomous loop with a declared project takes the project's own). 'none': ask the person for the parameters, "
                     "run once with explicit params, then op='save' them under the project so the next run finds them. Invoking a "
                     "method-driven action with neither method nor params is refused with MethodRequired, carrying the same choice. "
                     "op='save' is checked by the device through its own parameter gate before anything is written; the device "
                     "assigns version and hash, keeps every earlier version, and stamps every run with them. op='run' runs a method; "
                     "`overrides` change a parameter for this run only, the way an adaptive loop nudges a flow between injections; "
                     "when the tuned values work, op='save' them as the next version. Names are 'project/method' or a bare method "
                     "with project (default _shared). op='retire' keeps the file and hides it from find."),
     "inputSchema": {"type": "object", "properties": {
         "op": {"type": "string", "enum": ["find", "list", "get", "save", "run", "diff", "retire"]},
         "device": {"type": "string", "description": "the instrument; methods live on it"},
         "compound": {"type": "string"}, "project": {"type": "string", "description": "find/list: filter; get/run/save: the method's project"},
         "action": {"type": "string", "description": "find/list: only methods for this action"},
         "name": {"type": "string", "description": "get/run/retire: 'project/method' or a bare method id"},
         "method": {"type": "object", "description": "save: {name, project?, action, params, compounds, author?, notes?, source?, derived_from?}"},
         "version": {"type": "integer"}, "overrides": {"type": "object", "description": "run: parameter overrides for this run only"},
         "run_project": {"type": "string", "description": "run: the project this run belongs to, if not the method's own"},
         "wait": {"type": "boolean", "description": "run: wait for the job (default true)"},
         "retired": {"type": "boolean", "description": "list: include retired methods"},
         "a": {"type": "string"}, "b": {"type": "string"}, "a_version": {"type": "integer"}, "b_version": {"type": "integer"},
         "query": {"type": "string"}, "note": {"type": "string", "description": "save: why this version"}},
                     "required": ["op", "device"]},
     "input_examples": [
         {"op": "find", "device": "gc-01", "compound": "ethanol", "project": "solvent-screen"},
         {"op": "save", "device": "gc-01", "method": {"name": "ethanol-ipa", "project": "solvent-screen", "action": "run_method",
                                                       "compounds": ["ethanol", "isopropanol"], "source": {"kind": "person", "ref": "R. Patel, method sheet 2026-09"},
                                                       "params": {"oven_program": [{"temp": 60, "hold_s": 60}, {"temp": 200, "ramp_c_min": 20, "hold_s": 30}],
                                                                  "injection_volume_ul": 1, "carrier_flow_ml_min": 1.5, "sample": "ethanol isopropanol"}}},
         {"op": "run", "device": "gc-01", "name": "solvent-screen/ethanol-ipa"},
         {"op": "run", "device": "gc-01", "name": "solvent-screen/ethanol-ipa", "overrides": {"carrier_flow_ml_min": 1.0}},
         {"op": "diff", "device": "gc-01", "a": "solvent-screen/ethanol-ipa", "a_version": 1},
         {"op": "list", "device": "thermocycler-01", "compound": "plasmid-x"}]},
]

INSTRUCTIONS = (
    "OpenMHP gives you safe control of laboratory and factory instruments. The user may be a scientist who does not "
    "program; do the work for them and ask only for what you cannot know.\n"
    "- To operate: mhp_find (search by what you need) -> mhp_describe (read the owner's operating instructions) -> "
    "mhp_read the interlocks -> mhp_run plan=true to rehearse multi-step work and show the plan -> run -> verify with "
    "mhp_read. Refusals are safety limits; report them, do not work around them. approval=confirm means a person must "
    "say yes: the server asks them itself through elicitation, and you cannot approve for them. If your harness has no "
    "elicitation, confirm-gated steps are unavailable; tell the user. Operator-run instruments wait for a person to "
    "acknowledge each step.\n"
    "- Prefer recipes (mhp_lab op='recipes') over writing scripts from scratch; adapt PARAMS, plan, then run. Long work: "
    "mhp_run background=true, then mhp_data to read stdout and saved files.\n"
    "- To set up or add instruments: mhp_lab op='status' tells you what to do next. op='scan' finds instruments already "
    "on the network; op='add' registers one (also github: community packages, sim=true for a simulated twin). "
    "op='onboard' interviews the human (relay each question in plain words, return answers in the given shape; submit "
    "everything a manual tells you in one call) and then the server writes and validates the device package itself and "
    "gives you a safety card to read back; finish with op='add'.\n"
    "- Instruments that run methods (GC, HPLC, MS, PXRD, a thermocycler's programs) keep them on the device, per project and "
    "compound. Before invoking any action marked methods: true, ask the device: mhp_method op='find' with the compound and "
    "the project. One match: run it. Several: ask the person which (an autonomous loop with a declared project takes the "
    "project's own). None: ask the person for the parameters, run once with them, then op='save' under the project. Adapt "
    "between runs with `overrides`; save what worked as the next version. Results are pushed: mhp_data op='updates' shows "
    "each new result (a run's events.jsonl keeps them) so you can decide the next run without polling.\n"
    "- mhp_estop is always allowed. Use it the moment anything looks wrong. mhp_job op='pause' lets a human step in."
)

PROMPTS = {
    "setup-my-lab": ("Set up OpenMHP for this user: find or onboard their instruments.",
                     "Help me connect my lab instruments so you can control them. Start with mhp_lab op='status', then scan my network for "
                     "instruments that already speak OpenMHP and offer to add them. For any instrument that is not found, interview me with "
                     "mhp_lab op='onboard', one question at a time in plain language, and build its device package. Read the safety card "
                     "and operating instructions back to me at the end for review."),
    "add-instrument": ("Onboard one instrument by interview; the server writes the package.",
                       "I want to add an instrument to my lab. Use mhp_lab op='onboard' and ask me its questions one at a time, in plain "
                       "words. If I give you a manual, read it first and submit what it tells you, then confirm the limits with me. If I do "
                       "not know a value, leave it out rather than guessing. When the package is written, read me the safety card, add it "
                       "with op='add', then show me its operating procedure."),
    "run-experiment": ("Plan, confirm and run a procedure on connected instruments.",
                       "Run the following on my instruments. Look for a matching recipe with mhp_lab op='recipes' first. Find the right "
                       "devices with mhp_find, read their operating instructions with mhp_describe, then REHEARSE with mhp_run plan=true and "
                       "show me the plan: every step, every point where you will ask me, anything that would be refused. Only after I say go, "
                       "run it (background=true if it takes more than a few minutes) and report what you actually read from the instruments."
                       "\n\nProcedure: "),
    "lab-status": ("What is connected, what is running, what happened recently.",
                   "Give me a short status of my lab: mhp_lab op='status' and op='list' for the devices, mhp_data op='runs' for runs in "
                   "progress or recently finished, and mhp_lab op='events' for anything notable (refusals, e-stops, finished jobs). "
                   "Keep it to a few lines."),
}


class Bridge:
    """The MCP host side. Trust model: the bridge (host) is trusted; the model is not. The model cannot approve
    confirm-gated operations: the bridge asks a person and binds the answer to the exact request, for direct tool
    calls and for run scripts alike."""

    def __init__(self, targets: dict[str, str] | None = None, directory=None, fleet=None, home: Path | None = None):
        self.fleet = fleet
        self._onboarding = None
        self._hooked: set[int] = set()
        self.client_caps: dict = {}
        self.send_request = None          # set by the stdio loop: callable(method, params) -> result
        self.send_notification = None     # set by the stdio loop: callable(method, params)
        from .runs import HOME
        self.home = home or (fleet.path.parent if fleet is not None else HOME)
        self.log = RunLog(self.home)
        self._updates: dict[str, list[dict]] = {}          # device -> recent pushed events (ring buffer)
        self._run_devices: dict[str, set[str]] = {}         # run id -> devices it has touched
        self._updates_lock = threading.Lock()
        if fleet is not None:
            directory, targets = fleet.directory(), fleet.targets
        elif directory is None and targets:
            directory = Directory.from_targets(targets)      # cards only; connections are lazy
        elif directory is None:
            directory = Directory()
        self.lab = Lab(targets, directory, session=f"bridge-{uuid.uuid4().hex[:8]}", approver=self._approve,
                       observer=self._observe, on_connect=self._on_connect)
        self.runs = Runs(self.lab, self.log, self.home, observer=self._observe)

    # ---- tools ------------------------------------------------------------
    def call_tool(self, name: str, a: dict):
        lab = self.lab
        if name == "mhp_find":
            return lab.find(a.get("query", ""), limit=int(a.get("limit", 5)), cls=a.get("class"),
                            tags=a.get("tags"), location=a.get("location"), state=a.get("state"))
        if name == "mhp_estop":
            if a["device"] == "*":
                r = lab.estop_all(a.get("reason", ""))
            else:
                r = self._device(a["device"]).estop(a.get("reason", ""))
            self.notify_harness("error", f"E-STOP {a['device']}: {a.get('reason', '')}")
            return r
        if name == "mhp_run":
            return self.run_tool(a)
        if name == "mhp_lab":
            return self.lab_op(a)
        if name == "mhp_data":
            return self.data_op(a)
        if name == "mhp_method":
            return self.method_op(a)
        dev = self._device(a["device"])
        if name == "mhp_describe":
            if a.get("resource"):
                return dev.call("resources/read", {"path": a["resource"]})
            p = {"detail": a.get("detail", "summary")}
            if a.get("select"):
                p["select"] = a["select"]
            return dev.call("device/describe", p)
        if name == "mhp_read":
            return dev.call("signals/read", {"names": a["names"]} if a.get("names") else {})
        if name == "mhp_write":                  # any model-supplied `approved` is ignored
            return dev.call("settings/write", {"name": a.get("name"), "value": a.get("value"), "dryRun": a.get("dryRun") is True})
        if name == "mhp_invoke":
            req = {"name": a.get("name"), "params": a.get("params") or {}, "dryRun": a.get("dryRun") is True}
            for k in ("method", "project", "compound"):        # a saved method in place of params; provenance for the run
                if a.get(k):
                    req[k] = a[k]
            r = dev.call("actions/invoke", req)
            if a.get("dryRun") is True:
                return r
            job = r["job"]
            if a.get("wait"):
                job = dev.wait(job)
                self.log.write("job", device=a["device"], action=a["name"], state=job["state"], result=job.get("result"))
            return job
        if name == "mhp_job":
            op = a.get("op") or ("cancel" if a.get("cancel") else "status")
            fn = {"status": dev.status, "pause": dev.pause, "resume": dev.resume, "cancel": dev.cancel}[op]
            return fn(a["id"])
        raise ValueError(f"unknown tool {name}")

    def _device(self, name: str):
        return self.lab[name]

    def _on_connect(self, name: str, dev) -> None:
        """Every connection (in-process, HTTP via its SSE stream, stdio) relays what the device pushes. One
        subscription per underlying driver or transport, however many clients (bridge, runs, plans) open it."""
        key = id(getattr(dev, "driver", None) or dev)
        if key in self._hooked:
            return
        self._hooked.add(key)
        dev.subscribe(lambda msg, n=name: self._device_event(n, msg))

    _LOGGED_EVENTS = ("jobs/finished", "safety/estop", "safety/reset", "safety/fault", "jobs/paused",
                      "operator/instruction", "methods/saved")

    def _device_event(self, device: str, msg: dict):
        m = msg.get("method", "").replace("notifications/", "")
        params = msg.get("params") or {}
        # 1. every pushed event is kept per device, so an agent can ask "what came in since" without polling
        rec = {"ts": time.time(), "event": m, "device": device}
        if m == "signals/update":
            rec.update(signal=params.get("name"), value=params.get("value"))
        elif "job" in params:
            j = params["job"]
            rec.update(job=j.get("id"), action=j.get("action"), state=j.get("state"), progress=j.get("progress"),
                       **({"method": j["method"]} if j.get("method") else {}), **({"project": j["project"]} if j.get("project") else {}),
                       **({"result": _cap(j.get("result"))} if m == "jobs/finished" else {}),
                       **{k: v for k, v in params.items() if k != "job"})
        else:
            rec.update(params)
        with self._updates_lock:
            buf = self._updates.setdefault(device, [])
            buf.append(rec)
            del buf[:-500]
        # 2. runs that touched this device get it in their own events.jsonl
        for rid, devs in list(self._run_devices.items()):
            run = self.runs.runs.get(rid)
            if device in devs and run is not None and run.state == "running":
                try:
                    with open(run.dir / "events.jsonl", "a") as f:
                        f.write(json.dumps({**rec, "run": rid}, default=str) + "\n")
                except OSError:
                    pass
        # 3. the notable ones go to the lab's run log and to the harness
        if m in self._LOGGED_EVENTS:
            ev = self.log.write("device/" + m, device=device, **{k: v for k, v in params.items() if k != "job"},
                                **({"job": params["job"]["id"], "state": params["job"]["state"], "method": params["job"].get("method"),
                                    "result": _cap(params["job"].get("result"))} if "job" in params else {}))
            level = "error" if ("estop" in m or "fault" in m) else "info"
            self.notify_harness(level, f"{device}: {m} " + json.dumps({k: v for k, v in ev.items() if k not in ("ts", "kind", "seq", "device")}, default=str)[:300])

    def updates(self, device: str, signal: str | None = None, since: float = 0.0, limit: int = 20) -> dict:
        with self._updates_lock:
            buf = list(self._updates.get(device, []))
        out = [r for r in buf if r["ts"] > since and (signal is None or r.get("signal") == signal)]
        return {"device": device, "updates": out[-limit:], "latest_ts": buf[-1]["ts"] if buf else None,
                "note": "pushed by the device as it happened; nothing here was polled"}

    def _observe(self, ev: dict) -> None:
        """Audit every call made through the lab's clients: direct tools and run scripts."""
        method, params = ev.get("method"), ev.get("params") or {}
        kind = _OBSERVED_KINDS.get(method, method)
        fields = {"device": ev.get("device"), "session": ev.get("session")}
        if ev.get("run"):
            fields["run"] = ev["run"]
            if ev.get("device"):
                self._run_devices.setdefault(ev["run"], set()).add(ev["device"])
        if method == "settings/write":
            fields.update(name=params.get("name"), value=params.get("value"), dry_run=params.get("dryRun") is True)
        elif method == "actions/invoke":
            fields.update(name=params.get("name"), params=params.get("params") or None, dry_run=params.get("dryRun") is True)
            job = (ev.get("result") or {}).get("job") if isinstance(ev.get("result"), dict) else None
            if params.get("method") or (job and job.get("method")):
                fields["method"] = (job or {}).get("method") or params.get("method")     # provenance: name, version, hash
            if params.get("project") or (job and job.get("project")):
                fields["project"] = (job or {}).get("project") or params.get("project")
        elif method == "signals/read":
            fields.update(names=params.get("names"), values=(ev.get("result") or {}).get("values"))
        elif params:
            fields["params"] = params
        if ev.get("confirmed"):
            fields["confirmed_by"] = "a person, via elicitation"
        if "error" in ev:
            self.log.write("refused", op=kind, code=ev["error"]["code"], message=ev["error"]["message"], **fields)
        else:
            self.log.write(kind, ok=True, **fields)

    def _approve(self, dev, method: str, params: dict) -> bool:
        """The only path to `approved: true`. Asks a person about this exact request."""
        name = params.get("name")
        if method == "settings/write":
            what = f"{dev.name}: set {name} = {json.dumps(params.get('value'), default=str)}"
        else:
            args = params.get("params") or {}
            what = f"{dev.name}: run {name}" + (f" with {json.dumps(args, default=str)}" if args else "")
        if not self.can_elicit():
            self.log.write("confirm/unavailable", device=dev.name, name=name)
            raise _remote(ApprovalRequired.code,
                          f"'{name}' needs a person's confirmation, and this harness has no trusted confirmation channel "
                          "(MCP elicitation). Ask the user to do this step at the instrument or from a harness that supports "
                          "elicitation.", {"approval": "confirm", "channel": "unavailable"})
        spec = self._spec(dev, "settings" if method == "settings/write" else "actions", name)
        ans = self.elicit(what + "?" + (f" Note from the owner: {spec['notes']}" if spec.get("notes") else ""))
        self.log.write("confirm", device=dev.name, name=name, answer=ans, request=params)
        return ans == "accept"

    def can_elicit(self) -> bool:
        return bool(self.send_request) and "elicitation" in (self.client_caps or {})

    def elicit(self, message: str) -> str:
        """Ask the human through MCP elicitation. Returns 'accept', 'decline' or 'cancel'."""
        try:
            res = self.send_request("elicitation/create", {
                "message": message,
                "requestedSchema": {"type": "object", "properties": {"confirm": {"type": "boolean", "title": "Confirm", "description": "Yes to allow this once"}},
                                    "required": ["confirm"]}})
        except Exception as e:                                # noqa: BLE001
            return f"error: {e}"
        action = (res or {}).get("action", "cancel")
        if action == "accept" and not (res.get("content") or {}).get("confirm", True):
            return "decline"
        return action

    @staticmethod
    def _spec(dev, section, name) -> dict:
        try:
            items = dev.call("device/describe", {"select": {section: [name]}})[section]
            return items[0] if items else {}
        except RemoteError:
            return {}

    def notify_harness(self, level: str, text: str):
        if self.send_notification:
            try:
                self.send_notification("notifications/message", {"level": level, "logger": "openmhp", "data": text})
            except Exception:                                  # noqa: BLE001
                pass

    # ---- runs, recipes, plans ---------------------------------------------------
    def run_tool(self, a: dict) -> dict:
        from . import recipes as R
        script, name, params = a.get("script"), a.get("name") or "run", a.get("params") or {}
        if not isinstance(params, dict):
            raise ValueError("params must be an object")
        if a.get("recipe"):
            r = R.get(a["recipe"], self._recipes())
            if r is None:
                return {"error": f"no recipe {a['recipe']!r}", "available": [x["name"] for x in R.search("", self._recipes(), limit=50)]}
            script = R.with_params(r["source"])
            name = a.get("name") or r["name"]
        if not script:
            raise ValueError("mhp_run needs script or recipe")
        if a.get("plan"):
            plan = PlanLab(self.lab.child(session=f"plan-{uuid.uuid4().hex[:8]}", observer=None))
            res = self.runs.start(script, name=f"plan:{name}", timeout_s=float(a.get("timeout_s", 120)), plan=plan, params=params)
            state = res["run"]["state"]
            if state == "running":
                summary = plan.summary("failed", "the rehearsal did not finish within the timeout")
            else:
                summary = plan.summary(state, res.get("error"))
                plan.close()
            out = {"plan": summary, "stdout": res.get("stdout", ""), "ok": state in ("done", "truncated") and not summary["refused"]}
            if res.get("error"):
                out["error"] = res["error"]
            self.log.write("plan", name=name, verdict=summary["verdict"], steps=len(plan.plan))
            return out
        self.lab.release_all()                   # hand this session's leases to the run's own session
        return self.runs.start(script, name=name, timeout_s=float(a.get("timeout_s", 600)),
                               background=bool(a.get("background")), params=params)

    def _recipes(self):
        from . import recipes as R
        extra = [self.home / "recipes"]
        return R.load_all(extra)

    def data_op(self, a: dict):
        op = a["op"]
        if op == "runs":
            return {"runs": self.runs.list()}
        if op == "list":
            d = self.runs.resolve(a.get("run", "latest"))
            return {"run": d.name, "files": sorted(str(p.relative_to(d)) for p in d.rglob("*") if p.is_file())}
        if op == "read":
            return self.runs.read(a.get("run", "latest"), a.get("path", "stdout.txt"))
        if op == "log":
            return self.log.window(int(a.get("since", 0)), int(a.get("limit", 100)))
        if op == "updates":
            self._device(a["device"])                      # connecting is what starts the relay
            return self.updates(a["device"], a.get("signal"), float(a.get("since", 0) or 0), int(a.get("limit", 20)))
        raise ValueError(f"unknown data op {op}")

    # ---- methods: served by the device; the bridge only routes ---------------
    def method_op(self, a: dict):
        op = a["op"]
        if not a.get("device"):
            raise ValueError("mhp_method needs device=<id>: methods live on the instrument that runs them")
        dev = self._device(a["device"])
        if op == "find":
            if not a.get("compound"):
                raise ValueError("find needs compound")
            return dev.method_find(a["compound"], a.get("project"), a.get("action"))
        if op == "list":
            return dev.methods(a.get("compound"), a.get("project"), a.get("action"), a.get("query"), bool(a.get("retired")))
        if op == "get":
            return dev.method(a["name"], a.get("project"), a.get("version"))
        if op == "diff":
            return dev.method_diff(a["a"], a.get("b"), a.get("a_version"), a.get("b_version"), a.get("project"))
        if op == "retire":
            r = dev.method_retire(a["name"], a.get("project"))
            self.log.write("method/retire", device=dev.name, method=r.get("method"))
            return r
        if op == "save":
            if not isinstance(a.get("method"), dict):
                raise ValueError("save needs method={name, project?, action, params, compounds, ...}")
            m = {**a["method"], **({"project": a["project"]} if a.get("project") and not a["method"].get("project") else {})}
            r = dev.method_save(m, a.get("note"))
            self.log.write("method/save", device=dev.name, method={k: r["saved"].get(k) for k in ("project", "name", "version", "hash")})
            return r
        if op == "run":
            job = dev.run_method(a["name"], a.get("overrides"), project=a.get("project"), version=a.get("version"),
                                 run_project=a.get("run_project"), compound=a.get("compound"), wait=a.get("wait", True) is not False)
            if job["state"] in ("done", "failed", "cancelled"):
                self.log.write("job", device=dev.name, action=job["action"], state=job["state"], method=job.get("method"),
                               project=job.get("project"), result=_cap(job.get("result")))
            return {"job": job}
        raise ValueError(f"unknown method op {op}")

    # ---- lab management ------------------------------------------------------
    def lab_op(self, a: dict):
        from .fleet import Fleet
        from .validate import validate_path
        fleet = self.fleet
        if fleet is None:
            fleet = self.fleet = Fleet(self.home / "fleet.json")
        op = a["op"]
        if op == "status":
            n = len(fleet.devices)
            running = [r for r in self.runs.list() if r["state"] == "running"]
            unlocated = fleet.unlocated()
            return {"devices": n, "runs_in_progress": len(running), "fleet": str(fleet.path), "elicitation": self.can_elicit(),
                    **({"without_a_location": unlocated,
                        "ask": "Ask the human where these instruments stand, then mhp_lab op='location'."} if unlocated else {}),
                    "next": ("The lab is empty. Ask the user whether their instruments already have an OpenMHP address (then op='scan' "
                             "or op='add'), whether a community package exists (op='registry'), or whether to onboard one by interview "
                             "(op='onboard'). Offer op='scan' first; it is free. To try without hardware: op='add' target=<bundled package> sim=true "
                             "or `npx openmhp-cli demo`.")
                            if n == 0 else
                            ("Lab has %d device(s); mhp_find searches them. Recipes: op='recipes'. To add more: op='scan', op='registry', "
                             "or op='onboard' for an instrument with no OpenMHP address yet." % n)}
        if op == "onboard":
            if self._onboarding is None:
                from .onboarding import Onboarding
                self._onboarding = Onboarding(fleet.packages_dir())
            ans = a.get("answers") or {}
            if ans.get("skip"):
                sess = self._onboarding.sessions.get(a.get("id"))
                if sess is None:
                    return {"error": "unknown onboarding id"}
                sess["asked_optional"] = True
                r = self._onboarding.finish(a["id"])
            else:
                r = self._onboarding.step(a.get("id"), ans)
            if r.get("validation", {}).get("ok"):
                r["safety_card"] = self._safety_card_for_package(fleet.packages_dir() / r["id"])
                r["next"] = ("Read the safety card and the operating procedure back to the human. If they agree, mhp_lab op='add' target='%s'." % r["id"])
            return r
        if op == "scan":
            found = fleet.scan(hosts=a.get("hosts"))
            self.log.write("scan", found=[f["id"] for f in found])
            return {"found": found, "next": "mhp_lab op='add' target=<target> for each device you want in the lab"} if found else \
                   {"found": [], "note": "no new MHP devices answered on localhost or the given hosts. Devices advertise _mhp._tcp or answer GET /mhp.json. "
                                         "Pass hosts=[...] for specific machines, try op='registry' for a community package, or op='onboard'."}
        if op == "add":
            target = a["target"]
            if not target.startswith(("http", "pkg:", "sim:", "local:", "stdio:", "github:")) and "/" not in target and not Path(target).exists():
                target = str(fleet.packages_dir() / safe_id(target))  # a package id under ~/.openmhp/devices
            card = fleet.add(target, sim=bool(a.get("sim")), location=a.get("location"))
            entry = fleet.devices[card["id"]]
            self.lab.targets[card["id"]] = entry["target"]
            if isinstance(self.lab.directory, Directory):
                self.lab.directory.add(card, entry["target"])
            self.log.write("lab/add", device=card["id"], target=entry["target"], sim=bool(a.get("sim")))
            note = "now discoverable through mhp_find" + ("; this is a SIMULATED twin" if a.get("sim") else "")
            if not card.get("location"):
                note += ("; it has no location yet. Ask the human where the instrument stands and record it with "
                         "mhp_lab op='location' id='%s' location='...'" % card["id"])
            return {"added": card, "note": note}
        if op in ("remove", "reload"):
            did = a.get("id")
            entry = fleet.devices.get(did)
            target = entry["target"] if entry else self.lab.targets.get(did)
            active = self._active_jobs(did)
            if active and not a.get("force"):
                return {"error": f"{did} has active jobs {active}; let them finish or cancel them first (or pass force=true)"}
            self._forget_device(did, target)
            if op == "remove":
                ok = fleet.remove(did) if entry else False
                self.log.write("lab/remove", device=did)
                return {"removed": did if (ok or target) else None}
            if entry is None:
                return {"error": f"{did} is not in the lab"}
            fleet.remove(did)
            card = fleet.add(target, sim=bool(entry.get("sim")))
            new = fleet.devices[card["id"]]
            self.lab.targets[card["id"]] = new["target"]
            if isinstance(self.lab.directory, Directory):
                self.lab.directory.add(card, new["target"])
            self.log.write("lab/reload", device=card["id"], target=new["target"])
            return {"reloaded": card}
        if op == "release":
            self.lab.release_all()
            return {"released": sorted(self.lab.devices)}
        if op == "list":
            return {"devices": fleet.list(), "fleet": str(fleet.path)}
        if op == "home":
            return {"home": str(fleet.path.parent), "fleet": str(fleet.path), "packages": str(fleet.packages_dir()),
                    "runs": str(self.home / "runs"), "log": str(self.log.dir), "recipes": str(self.home / "recipes")}
        if op == "recipes":
            from . import recipes as R
            return {"recipes": R.search(a.get("query", ""), self._recipes(), limit=int(a.get("limit", 8))),
                    "how": "mhp_run recipe=<name> params={...} plan=true first; then without plan. Your own recipes go in ~/.openmhp/recipes/."}
        if op == "registry":
            from .registry import search as rsearch
            return {"packages": rsearch(a.get("query", "")), "how": "mhp_lab op='add' target='github:...' (sim=true for a rehearsal twin)"}
        if op == "location":
            card = fleet.set_location(a["id"], a.get("location", ""))
            if isinstance(self.lab.directory, Directory):
                self.lab.directory.add(card, fleet.devices[card["id"]]["target"])
            self.log.write("lab/location", device=card["id"], location=card["location"])
            return {"device": card["id"], "location": card["location"]}
        if op == "safety_card":
            from .safety import safety_card
            dev = self._device(a["id"])
            pkg = fleet.devices.get(a["id"], {}).get("target", "")
            pkg_path = pkg[4:] if pkg.startswith(("pkg:", "sim:")) else None
            where = fleet.devices.get(a["id"], {}).get("card", {}).get("location")
            card = safety_card(dev, pkg_path, location=where)
            self.log.write("safety_card", device=a["id"], ok=card["ok"])
            return card
        if op == "events":
            return self.log.window(int(a.get("since", 0)), int(a.get("limit", 100)))
        if op == "new":
            did = safe_id(a["id"])
            folder = fleet.packages_dir() / did
            if (folder / "DEVICE.md").exists():
                return {"exists": str(folder), "note": "package already exists; use op='write' to change files"}
            folder.mkdir(parents=True, exist_ok=True)
            tpl = Path(__file__).parent / "skills" / "openmhp-onboard-device" / "assets"
            dev_md = (tpl / "DEVICE.template.md").read_text().replace("change-me-01", did).replace("Change-me-01", did)
            dev_md = dev_md.replace("class: generic", f"class: {a.get('class', 'generic')}")
            if a.get("description"):
                dev_md = dev_md.replace("description: What it is, in one clause. When an agent should pick it, in one clause. What it is not for.",
                                        f"description: {a['description']}")
            (folder / "DEVICE.md").write_text(dev_md)
            (folder / "descriptor.yaml").write_text((tpl / "descriptor_template.yaml").read_text())
            (folder / "driver.py").write_text((tpl / "driver_template.py").read_text())
            return {"created": str(folder), "files": ["DEVICE.md", "descriptor.yaml", "driver.py"],
                    "next": "op='write' the real DEVICE.md, descriptor.yaml and driver.py, op='validate', and op='add' with target=<id>"}
        if op == "write":
            folder = fleet.packages_dir() / safe_id(a["id"])
            folder.mkdir(parents=True, exist_ok=True)
            written = []
            for rel, text in (a.get("files") or {}).items():
                p = (folder / rel)
                if folder.resolve() not in p.resolve().parents:
                    raise ValueError(f"{rel} escapes the package")
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(text)
                written.append(rel)
            return {"package": str(folder), "written": written, "next": "op='validate' then op='add'"}
        if op == "validate":
            where = fleet.devices.get(a["id"], {}).get("card", {}).get("location")
            return validate_path(str(fleet.packages_dir() / safe_id(a["id"])), location=where)
        raise ValueError(f"unknown lab op {op}")

    def _safety_card_for_package(self, folder: Path) -> str:
        from .client import connect
        from .safety import safety_card
        target = f"pkg:{Path(folder).resolve()}"
        try:
            dev = connect(target, Path(folder).name)
            try:
                return safety_card(dev, str(folder))["text"]
            finally:
                dev.close()
        except Exception as e:                                  # noqa: BLE001
            return f"(safety card unavailable: {type(e).__name__}: {e})"
        finally:
            drop_inprocess(target)                              # the lab loads its own instance when the device is added

    def _active_jobs(self, did: str) -> list[str]:
        dev = self.lab.devices.get(did)
        if dev is None:
            return []
        try:
            jobs = dev.call("jobs/list")["jobs"]
        except Exception:                                       # noqa: BLE001
            return []
        return [j["id"] for j in jobs if j["state"] not in ("done", "failed", "cancelled")]

    def _forget_device(self, did: str, target: str | None) -> None:
        """Invalidate every cache that routes to a device: connection, directory entry, in-process driver."""
        self.lab.forget(did)
        if isinstance(self.lab.directory, Directory):
            self.lab.directory.remove(did)
        if target and target.startswith(("pkg:", "sim:", "local:")):
            entry = _inprocess.get(target)
            if entry is not None:
                self._hooked.discard(id(entry[0]))
            drop_inprocess(target)

    # ---- MCP protocol ------------------------------------------------------------
    def handle(self, msg: dict):
        m, p, mid = msg.get("method"), msg.get("params") or {}, msg.get("id")
        if m == "initialize":
            self.client_caps = p.get("capabilities") or {}
            requested = p.get("protocolVersion")
            return self._ok(mid, {"protocolVersion": requested if requested in SUPPORTED_MCP_VERSIONS else SUPPORTED_MCP_VERSIONS[0],
                                  "capabilities": {"tools": {}, "resources": {}, "prompts": {}, "logging": {}},
                                  "serverInfo": {"name": "openmhp-bridge", "version": __version__},
                                  "instructions": INSTRUCTIONS})
        if m == "prompts/list":
            return self._ok(mid, {"prompts": [{"name": n, "description": d} for n, (d, _) in PROMPTS.items()]})
        if m == "prompts/get":
            d, text = PROMPTS[p["name"]]
            return self._ok(mid, {"description": d, "messages": [{"role": "user", "content": {"type": "text", "text": text}}]})
        if m == "notifications/initialized" or mid is None:
            return None
        if m == "ping":
            return self._ok(mid, {})
        if m == "logging/setLevel":
            return self._ok(mid, {})
        if m == "tools/list":
            return self._ok(mid, {"tools": TOOLS})
        if m == "resources/list":            # only devices this session has opened; the directory is the catalogue
            res = [{"uri": "mhp://runs/latest/stdout.txt", "name": "latest run output", "mimeType": "text/plain"},
                   {"uri": "mhp://log/today", "name": "today's run log", "mimeType": "application/x-ndjson"}]
            for n, dev in self.lab.devices.items():
                res.append({"uri": f"mhp://{n}/descriptor", "name": f"{n} descriptor", "mimeType": "application/json"})
                for path in dev.call("resources/list")["resources"]:
                    res.append({"uri": f"mhp://{n}/{path}", "name": f"{n} {path}", "mimeType": "text/plain"})
            return self._ok(mid, {"resources": res})
        if m == "resources/read":
            _, rest = p["uri"].split("//", 1)
            n, _, path = rest.partition("/")
            if n == "runs":
                rid, _, rel = path.partition("/")
                text, mime = self.runs.read(rid, rel or "stdout.txt")["text"], "text/plain"
            elif n == "log":
                text, mime = "\n".join(json.dumps(e, default=str) for e in self.log.recent[-200:]), "application/x-ndjson"
            elif path == "descriptor":
                text, mime = json.dumps(self.lab[n].describe(), indent=2), "application/json"
            else:
                text, mime = self.lab[n].call("resources/read", {"path": path})["text"], "text/plain"
            return self._ok(mid, {"contents": [{"uri": p["uri"], "mimeType": mime, "text": text}]})
        if m == "tools/call":
            try:
                res = self.call_tool(p["name"], p.get("arguments") or {})
                return self._ok(mid, {"content": [{"type": "text", "text": json.dumps(res, indent=1, default=str)}]})
            except RemoteError as e:
                txt = json.dumps({"mhpError": {"code": e.code, "message": e.message, "data": e.data}}, default=str)
                return self._ok(mid, {"content": [{"type": "text", "text": txt}], "isError": True})
            except Exception as e:                # noqa: BLE001
                return self._ok(mid, {"content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}], "isError": True})
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"unknown method {m}"}}

    @staticmethod
    def _ok(mid, result):
        return {"jsonrpc": "2.0", "id": mid, "result": result}


# ------------------------------------------------------------------ transports ---- #
class StdioLoop:
    """Bidirectional stdio: handles client requests, and lets the bridge send its own requests (elicitation)
    and notifications (logging) back to the client. It writes only to the stream it was given; main() points
    sys.stdout at stderr, so nothing else in the process can write into the protocol stream."""

    def __init__(self, bridge: Bridge, out=None):
        self.bridge = bridge
        self._stream = out if out is not None else sys.stdout
        self._out = threading.Lock()
        self._pending: dict[str, dict] = {}
        self._cv = threading.Condition()
        self._n = 0
        self._n_lock = threading.Lock()
        bridge.send_request = self.request
        bridge.send_notification = self.notify

    def write(self, obj: dict):
        line = json.dumps(obj, default=str) + "\n"
        with self._out:
            self._stream.write(line)
            self._stream.flush()

    def notify(self, method: str, params: dict):
        self.write({"jsonrpc": "2.0", "method": method, "params": params})

    def request(self, method: str, params: dict, timeout: float = 600):
        with self._n_lock:
            self._n += 1
            rid = f"srv-{self._n}"
        self.write({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        with self._cv:
            while rid not in self._pending:
                if not self._cv.wait(timeout=timeout):
                    raise TimeoutError(f"no answer to {method}")
            resp = self._pending.pop(rid)
        if "error" in resp:
            raise RuntimeError(resp["error"].get("message", "request failed"))
        return resp.get("result")

    def run(self, stdin=None):
        for line in (stdin or sys.stdin):
            if not line.strip():
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "method" not in msg and "id" in msg:            # a response to one of our requests
                with self._cv:
                    self._pending[str(msg["id"])] = msg
                    self._cv.notify_all()
                continue
            threading.Thread(target=self._serve, args=(msg,), daemon=True).start()

    def _serve(self, msg):
        resp = self.bridge.handle(msg)
        if resp is not None:
            self.write(resp)


def make_mcp_http_server(bridge: Bridge, host: str = "127.0.0.1", port: int = 18800, token: str | None = None,
                         allowed_origins: tuple[str, ...] = ()):
    """MCP over HTTP (JSON responses): POST /mcp. Every request needs `Authorization: Bearer <token>`.
    Requests carrying an Origin header are refused unless that origin is explicitly allowed, and on a loopback
    bind the Host header must be localhost (DNS-rebinding protection). There are no server-initiated requests
    on this transport, so confirm-gated operations are unavailable over it."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    if not token:
        raise ValueError("the MCP HTTP endpoint requires an access token")
    loopback = host in ("127.0.0.1", "localhost", "::1")
    allowed_hosts: set[str] = set()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _reply(self, code: int, obj=None):
            body = json.dumps(obj, default=str).encode() if obj is not None else b""
            self.send_response(code)
            if obj is not None:
                self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _denied(self):
            origin = self.headers.get("Origin")
            if origin is not None and origin not in allowed_origins:
                return 403, "origin not allowed"
            if loopback and self.headers.get("Host", "") not in allowed_hosts:
                return 403, "host not allowed"
            auth = self.headers.get("Authorization", "")
            if not (auth.startswith("Bearer ") and hmac.compare_digest(auth[7:].encode(), token.encode())):
                return 401, "missing or invalid bearer token"
            return None

        def do_POST(self):
            denied = self._denied()
            if denied:
                return self._reply(denied[0], {"error": denied[1]})
            if self.path.rstrip("/") not in ("/mcp", ""):
                return self._reply(404, {"error": "POST /mcp"})
            try:
                n = int(self.headers.get("Content-Length", 0))
                if n > 10_000_000:
                    return self._reply(413, {"error": "request too large"})
                msg = json.loads(self.rfile.read(n))
            except ValueError:
                return self._reply(400, {"error": "invalid JSON"})
            resp = bridge.handle(msg)
            return self._reply(200, resp) if resp is not None else self._reply(202)

        def do_GET(self):
            denied = self._denied()
            return self._reply(denied[0], {"error": denied[1]}) if denied else self._reply(405, {"error": "use POST /mcp"})

    srv = ThreadingHTTPServer((host, port), H)
    real = srv.server_address[1]
    allowed_hosts.update({f"127.0.0.1:{real}", f"localhost:{real}", f"[::1]:{real}"})
    return srv


def serve_mcp_http(bridge: Bridge, host: str = "127.0.0.1", port: int = 18800, token: str | None = None,
                   allowed_origins: tuple[str, ...] = ()) -> None:
    srv = make_mcp_http_server(bridge, host, port, token, allowed_origins)
    print(f"MHP MCP bridge listening on http://{host}:{srv.server_address[1]}/mcp (bearer token required)", file=sys.stderr)
    srv.serve_forever()


def http_token(home: Path) -> str:
    """OPENMHP_HTTP_TOKEN, or a random token kept in <home>/http_token (created with mode 0600)."""
    env = os.environ.get("OPENMHP_HTTP_TOKEN")
    if env:
        return env
    path = home / "http_token"
    if path.is_file():
        return path.read_text().strip()
    home.mkdir(parents=True, exist_ok=True)
    tok = secrets.token_urlsafe(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(tok)
    return tok


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    directory, http_port, fleet, origins = None, None, None, []
    if "--fleet" in argv:
        from .fleet import Fleet
        i = argv.index("--fleet")
        nxt = argv[i + 1] if i + 1 < len(argv) and not argv[i + 1].startswith("--") and "=" not in argv[i + 1] else None
        fleet = Fleet(nxt)
        argv = argv[:i] + argv[i + (2 if nxt else 1):]
    if "--directory" in argv:
        i = argv.index("--directory")
        from .client import connect
        directory = connect(argv[i + 1], "directory")
        argv = argv[:i] + argv[i + 2:]
    if "--http" in argv:
        i = argv.index("--http")
        http_port = int(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    while "--allow-origin" in argv:
        i = argv.index("--allow-origin")
        origins.append(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    proto = sys.stdout
    if http_port is None:
        sys.stdout = sys.stderr          # the protocol stream belongs to StdioLoop alone
    targets = dict(arg.split("=", 1) for arg in argv)
    if not targets and directory is None and fleet is None:
        from .fleet import Fleet
        fleet = Fleet()                  # ~/.openmhp/fleet.json, possibly empty: mhp_lab fills it
        print(f"MHP bridge: lab from {fleet.path} ({len(fleet.devices)} devices)", file=sys.stderr)
    bridge = Bridge(targets, directory, fleet)
    if http_port is not None:
        token = http_token(bridge.home)
        print(f"MHP bridge: send 'Authorization: Bearer <token>'; the token is in {bridge.home / 'http_token'} "
              "(or set OPENMHP_HTTP_TOKEN)", file=sys.stderr)
        return serve_mcp_http(bridge, port=http_port, token=token, allowed_origins=tuple(origins))
    StdioLoop(bridge, out=proto).run()


if __name__ == "__main__":
    sys.exit(main())
