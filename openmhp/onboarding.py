"""Server-side onboarding: an interview the MCP server runs, so any agent can
add an instrument by relaying questions to a human and answers back.

    mhp_lab op="onboard"                       -> first questions
    mhp_lab op="onboard" id=... answers={...}  -> next questions, or the finished package

The agent asks the human in plain words (the `ask` text), turns the reply into the
shape given in `shape`, and sends it back. When every required answer is in, the
server writes DEVICE.md, descriptor.yaml and driver.py itself, validates the
package, and adds it to the lab. Nobody writes code.

Driver kinds a non-programmer can finish:
  manual   the instrument is operated by a person; the agent asks for actions and
           records readings. Useful today, and a placeholder until a real driver exists.
  serial   ASCII commands over a serial/USB port, declared in the descriptor
           (openmhp.drivers.serial_ascii). The owner pastes commands from the manual.
  mhp      the instrument already speaks MHP at a URL: just add it.
  adapter  OPC UA / ROS 2 / SiLA 2 / MADSci / PyLabRobot bindings (a technician's job;
           the interview collects what it can and leaves driver.py for the adapt-fleet skill).
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import yaml

from .fleet import safe_id

QUESTIONS = [
    # key, required, ask (what the agent says to the human), shape (what the agent returns)
    ("name", True,
     "What is the instrument? Make and model, and what you call it in the lab.",
     {"make": "str", "model": "str", "nickname": "str, optional"}),
    ("kind", True,
     "How is it controlled today? (a) someone operates it by hand at the bench, (b) it has a serial/USB "
     "port with text commands (there is usually a command list in the manual), (c) it already has an OpenMHP "
     "address on the network, (d) it is driven by OPC UA, ROS 2, SiLA 2, MADSci or PyLabRobot.",
     {"kind": "one of manual | serial | mhp | adapter", "url": "str, only for mhp", "port": "str, only for serial, e.g. /dev/ttyUSB0 or COM3",
      "baud": "int, only for serial, default 9600", "layer": "str, only for adapter"}),
    ("purpose", True,
     "In a sentence or two: what is it for, when should an agent choose it over other instruments, and what "
     "should it never be used for?",
     {"description": "str, 60 to 1024 chars, mentions what it is, when to pick it, what it is not for"}),
    ("place", True,
     "Where does it sit (room, bay, bench), and what 3 to 5 words would someone search for to find it?",
     {"location": "str", "tags": "list of str", "class": "one of thermocycler liquid_handler robot_arm microscope plate_reader "
      "centrifuge incubator hotplate balance pump valve spectrometer laser stage cnc 3d_printer oven power_supply camera generic"}),
    ("physical", False,
     "Anything an agent could not know from a screen: weight, footprint, hot or sharp or fragile parts, "
     "things that must not be moved or touched while it runs.",
     {"notes": "str"}),
    ("signals", True,
     "What can be read from it? For each: what it is called, its unit, and where it is measured. "
     "Include yes/no states that matter, like lid closed or door closed.",
     {"signals": [{"name": "snake_case", "type": "number | boolean | string", "unit": "str, optional", "notes": "str, optional",
                   "serial_read": "str, only for serial kind: the command that returns this value"}]}),
    ("settings", True,
     "What can be set? For each: its name, unit, the lowest and highest value you would ever allow, and what "
     "goes wrong past each end. Say if setting it should require a person's OK every time.",
     {"settings": [{"name": "snake_case", "type": "number | boolean | string", "unit": "str, optional", "min": "number", "max": "number",
                    "approval": "auto | confirm", "notes": "str, optional",
                    "serial_write": "str, only for serial kind: command with {value}, e.g. 'OUT_SP_1 {value}'"}]}),
    ("actions", True,
     "What can it do, as operations? For each: the name, roughly how long it takes, its inputs, and one realistic "
     "example of the inputs. Also: what must be true before it may start (lid closed, homed, nobody nearby), "
     "and whether a person must confirm every time or an agent must never do it.",
     {"actions": [{"name": "snake_case", "duration": "short | long", "params": {"param": "description"}, "example": {"param": "value"},
                   "interlocks": ["signal names that must be true"], "approval": "auto | confirm | forbid", "notes": "str, optional",
                   "methods": "bool, optional: true if this operation runs a saved method that changes per project or compound "
                              "(an HPLC/GC method, a PCR program, a scan recipe); the device then keeps methods per project",
                   "serial_commands": ["str, only for serial kind: commands sent in order; {param} placeholders allowed"]}]}),
    ("procedure", True,
     "Walk me through a normal run, step by step: what you check first, what you set, what you start, what you "
     "watch while it runs, and how you leave it safe afterwards.",
     {"steps": ["str, one per step"], "watch": ["str, things to watch and failure modes"]}),
    ("stop", True,
     "If something goes wrong, how do you stop it right now? Is there a button, a command, a breaker? "
     "And if the agent lost contact, how many seconds before the instrument should stop on its own?",
     {"estop": "str, what stopping does; or 'none'", "estop_serial": "str, only for serial kind", "watchdog_s": "int"}),
    ("docs", False,
     "Do you have an SOP, a manual excerpt, or a standard program you want the agent to have? Paste the text.",
     {"references": {"filename.md": "text"}}),
]
REQUIRED = [q[0] for q in QUESTIONS if q[1]]


class Onboarding:
    """One interview per device id. Kept in memory by the bridge, persisted as JSON so a crash loses nothing."""

    def __init__(self, packages_dir: Path):
        self.dir = packages_dir
        self.sessions: dict[str, dict] = {}

    # ---- protocol ----------------------------------------------------------
    def step(self, device_id: str | None, answers: dict | None) -> dict:
        if not device_id:
            device_id = self._id_from(answers or {})
        device_id = safe_id(device_id)
        s = self.sessions.setdefault(device_id, self._load(device_id))
        if answers:
            s["answers"].update(answers)
            if "signals" in answers or "settings" in answers or "actions" in answers:
                s["answers"]["kind"] = s["answers"].get("kind") or "manual"
            self._persist(device_id, s)
        missing = [k for k in REQUIRED if not self._answered(s["answers"], k)]
        optional = [k for k, req, *_ in QUESTIONS if not req and k not in s["answers"] and k not in s.get("skipped", [])]
        if missing:
            nxt = [self._question(k) for k in missing[:2]]
            return {"id": device_id, "progress": f"{len(REQUIRED) - len(missing)}/{len(REQUIRED)} required answered",
                    "ask": nxt, "how": "Ask the human the `ask` text in your own words, one question at a time. Turn the reply into the `shape` "
                                        "and send it back as answers={key: value}. Do not invent values; ask again if unsure."}
        if optional and not s.get("asked_optional"):
            s["asked_optional"] = True
            return {"id": device_id, "progress": "all required answered", "ask": [self._question(k) for k in optional],
                    "how": "These are optional. Ask once; if the human has nothing to add, send answers={'skip': true}."}
        return self.finish(device_id)

    def finish(self, device_id: str) -> dict:
        from .validate import validate_path
        device_id = safe_id(device_id)
        s = self.sessions[device_id]
        folder = self.dir / device_id
        files = build_package(device_id, s["answers"])
        folder.mkdir(parents=True, exist_ok=True)
        for rel, text in files.items():
            p = folder / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        v = validate_path(str(folder))
        s["done"] = time.time()
        self._persist(device_id, s)
        return {"id": device_id, "package": str(folder), "files": sorted(files), "validation": v,
                "next": "Read DEVICE.md back to the human for review (mhp_describe after adding). Then mhp_lab op='add' target='%s'." % device_id
                if v["ok"] else "Fix the validation errors with op='write' (or answer the question again), then op='validate' and op='add'."}

    # ---- helpers -------------------------------------------------------------
    @staticmethod
    def _question(key: str) -> dict:
        k, req, ask, shape = next(q for q in QUESTIONS if q[0] == key)
        return {"key": k, "required": req, "ask": ask, "shape": shape}

    @staticmethod
    def _answered(a: dict, key: str) -> bool:
        if key == "name":      return bool(a.get("make") or a.get("model") or a.get("nickname"))
        if key == "kind":      return a.get("kind") in ("manual", "serial", "mhp", "adapter")
        if key == "purpose":   return len(str(a.get("description", ""))) >= 60
        if key == "place":     return bool(a.get("location")) and bool(a.get("class"))
        if key == "signals":   return isinstance(a.get("signals"), list) and len(a["signals"]) > 0
        if key == "settings":  return isinstance(a.get("settings"), list)
        if key == "actions":   return isinstance(a.get("actions"), list)
        if key == "procedure": return isinstance(a.get("steps"), list) and len(a["steps"]) > 0
        if key == "stop":      return "estop" in a and "watchdog_s" in a
        return key in a

    @staticmethod
    def _id_from(a: dict) -> str:
        base = a.get("nickname") or a.get("model") or a.get("make") or "device"
        base = re.sub(r"[^a-z0-9]+", "-", str(base).lower()).strip("-") or "device"
        return f"{base[:50].strip('-') or 'device'}-01"

    def _load(self, device_id: str) -> dict:
        p = self.dir / device_id / ".onboarding.json"
        if p.is_file():
            return json.loads(p.read_text())
        return {"answers": {}, "started": time.time()}

    def _persist(self, device_id: str, s: dict) -> None:
        p = self.dir / device_id / ".onboarding.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(s, indent=1))


# ---------------------------------------------------------------- generation ---- #
def build_package(device_id: str, a: dict) -> dict[str, str]:
    """Turn interview answers into the package files."""
    kind = a.get("kind", "manual")
    signals = [_sig(s) for s in a.get("signals", [])]
    settings = [_setting(s) for s in a.get("settings", [])]
    actions = [_action(x) for x in a.get("actions", [])]
    bool_sigs = {s["name"] for s in signals if s["type"] == "boolean"}
    interlocks = sorted({i for x in actions for i in x.get("interlocks", []) if i in bool_sigs}
                        | {i for s in settings for i in s.get("interlocks", []) if i in bool_sigs})
    estop_text = str(a.get("estop", "none"))
    descriptor = {
        "device": {"notes": a.get("device_notes", "")} if a.get("device_notes") else {},
        "physical": {"notes": a["notes"]} if a.get("notes") else {},
        "signals": signals, "settings": settings, "actions": [_clean(x) for x in actions],
        "safety": ({"estop": False, "estop_kind": "operator", "interlocks": interlocks, "watchdog_s": None,
                    "notes": "Operator-run: stopping is a request to the person at the instrument. " + estop_text}
                   if kind == "manual" else
                   {"estop": estop_text.strip().lower() not in ("", "none", "no"), "interlocks": interlocks,
                    "watchdog_s": int(a.get("watchdog_s", 30)), "notes": estop_text}),
    }
    if kind == "serial":
        descriptor["serial"] = {
            "port": a.get("port", "/dev/ttyUSB0"), "baud": int(a.get("baud", 9600)), "eol": "\\r\\n",
            "read": {s["name"]: s["serial_read"] for s in a.get("signals", []) if s.get("serial_read")},
            "write": {s["name"]: s["serial_write"] for s in a.get("settings", []) if s.get("serial_write")},
            "actions": {x["name"]: x["serial_commands"] for x in a.get("actions", []) if x.get("serial_commands")},
            "estop": [a["estop_serial"]] if a.get("estop_serial") else [],
        }
    if not descriptor["device"]:
        descriptor.pop("device")

    make, model = a.get("make", ""), a.get("model", "")
    title = a.get("nickname") or f"{make} {model}".strip() or device_id
    fm = {"mhp": "2026-09-12", "id": device_id, "class": a.get("class", "generic"), "make": make, "model": model,
          "location": a.get("location", ""), "tags": a.get("tags", []), "description": a.get("description", "")}
    if kind in ("manual", "serial"):
        fm["driver"] = "driver.py:Device"
    steps = "\n".join(f"{i}. {s}" for i, s in enumerate(a.get("steps", []), 1))
    watch = "\n".join(f"- {w}" for w in a.get("watch", [])) or "- Read the signals that prove the outcome before reporting success."
    refs = a.get("references") or {}
    res_lines = "\n".join(f"- `references/{n}`: from the owner." for n in refs)
    if kind == "manual":
        res_lines += ("\n" if res_lines else "") + "- This instrument is operated by a person. Each action waits until a person acknowledges it; settings are requests until a person reports the value; `record` stores a reading a person confirms."
    device_md = f"""---
{yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).strip()}
---

# {title}

{a.get('description', '')}

Location: {a.get('location', '')}. {a.get('notes', '')}

## Operating procedure
{steps}

## What to watch
{watch}

## Resources
{res_lines or '- none yet'}
"""
    files = {"DEVICE.md": device_md, "descriptor.yaml": yaml.safe_dump(descriptor, sort_keys=False, allow_unicode=True)}
    for n, text in refs.items():
        files[f"references/{re.sub(r'[^A-Za-z0-9._-]', '_', n)}"] = str(text)
    if kind == "manual":
        files["driver.py"] = 'from openmhp.drivers.manual import ManualDriver as Device   # human-operated; see DEVICE.md\n'
    elif kind == "serial":
        files["driver.py"] = 'from openmhp.drivers.serial_ascii import SerialAsciiDriver as Device   # commands in descriptor.yaml `serial:`\n'
    elif kind == "mhp":
        files["driver.py"] = f'# This instrument already speaks MHP at {a.get("url")}. Add it with: mhp lab add {a.get("url")}\n'
    else:
        files["driver.py"] = (f'# TODO: {a.get("layer", "adapter")} bindings. See the openmhp-adapt-fleet skill.\n'
                              'from openmhp.adapters import BoundDriver\nDEVICE = BoundDriver(device={})\n')
    return files


def _sig(s: dict) -> dict:
    return _clean({"name": _snake(s["name"]), "type": s.get("type", "number"), "unit": s.get("unit"), "notes": s.get("notes")})


def _setting(s: dict) -> dict:
    lim = None
    if s.get("type", "number") in ("number", "integer") and (s.get("min") is not None or s.get("max") is not None):
        lim = _clean({"min": s.get("min"), "max": s.get("max")})
    return _clean({"name": _snake(s["name"]), "type": s.get("type", "number"), "unit": s.get("unit"), "limits": lim,
                   "approval": s.get("approval", "auto"), "interlocks": s.get("interlocks") or None, "notes": s.get("notes")})


def _action(x: dict) -> dict:
    return _clean({"name": _snake(x["name"]), "duration": x.get("duration", "short"), "approval": x.get("approval", "auto"),
                   "interlocks": [_snake(i) for i in x.get("interlocks", [])] or None, "params": x.get("params") or None,
                   "examples": [x["example"]] if x.get("example") else None, "notes": x.get("notes"),
                   "methods": True if x.get("methods") is True else None})


def _snake(n: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(n).lower()).strip("_")


def _clean(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}
