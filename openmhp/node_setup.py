"""``mhp node setup [<package>] [<dir>]``: the questions, and the steps after them.

After ``mhp node add`` puts a package on the PC, the person at the bench should not be handed a to-do
list. The command knows the machine, the package and what its config needs, so it installs the
vendor client, asks only for what a person knows (which COM port, the Empower address, the project),
with an example beside every question, writes ``config.json``, proves the answers against the
instrument where the driver can, pairs with the lab's gateway, and leaves the node running.

What a package can provide (all optional; the generic path works without them):

- ``config.schema.json`` next to ``config.example.json``: one entry per question, in the order to ask::

      {"address": {"ask": "Empower Web API address", "example": "https://emp.lab.local:3076",
                   "kind": "url", "required": true, "help": "..."},
       "password": {"ask": "Password for {username}", "kind": "secret", "keyring": ["Empower", "{username}"]},
       "project": {"ask": "Project", "kind": "choice", "choices_from": "projects"},
       "verify_tls": {"ask": "Check the TLS certificate?", "kind": "bool", "advanced": true}}

  Kinds: text, url, path, com_port, int, bool, choice, secret. A ``secret`` goes to the OS keyring and
  never into config.json. ``advanced`` questions keep the example value unless ``--all``. Keys of
  the example that the schema does not mention keep their example values.
  Without a schema, every string-valued key of the example is asked, with the example as the hint
  and the sentence about it from ``references/setup.md`` as help.

- ``Driver.discover(cfg, what)`` (classmethod): choices for a ``choice`` or ``com_port`` question
  given the answers so far. ``Driver.probe(cfg)`` (classmethod): one line proving the config works,
  raising with the reason otherwise.

Every prompt goes through one ``ask(prompt, default, secret)`` callable, so tests drive the whole
flow without a terminal, and ``--yes`` / ``--set key=value`` / no TTY run it with no questions.
"""
from __future__ import annotations

import getpass
import glob
import json
import os
import re
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

KINDS = ("text", "url", "path", "com_port", "int", "bool", "choice", "secret")


@dataclass
class Question:
    key: str
    ask: str
    kind: str = "text"
    example: str | None = None
    help: str = ""
    required: bool = True
    advanced: bool = False
    choices: list = field(default_factory=list)
    choices_from: str | None = None
    keyring: list | None = None            # [service, user], {placeholders} filled from earlier answers


class Unanswered(Exception):
    """Raised by the non-interactive ``ask`` when a question has no default."""


class Stop(Exception):
    """The person chose to stop."""


# ---- schema -------------------------------------------------------------------------------------
def _example(folder: Path) -> dict:
    try:
        d = json.loads((folder / "config.example.json").read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _current(folder: Path) -> dict:
    try:
        d = json.loads((folder / "config.json").read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def load_schema(folder: Path) -> list[Question] | None:
    """The package's own questions, or None when it has none."""
    f = folder / "config.schema.json"
    if not f.is_file():
        return None
    raw = json.loads(f.read_text(encoding="utf-8"))
    ex = _example(folder)
    out = []
    for key, spec in raw.items():
        spec = dict(spec or {})
        if "example" not in spec and isinstance(ex.get(key), (str, int, float)) and not isinstance(ex.get(key), bool):
            spec["example"] = str(ex[key])
        out.append(Question(key=key, ask=spec.pop("ask", key), kind=spec.pop("kind", "text"),
                            example=spec.pop("example", None), help=spec.pop("help", ""),
                            required=bool(spec.pop("required", True)), advanced=bool(spec.pop("advanced", False)),
                            choices=list(spec.pop("choices", []) or []), choices_from=spec.pop("choices_from", None),
                            keyring=spec.pop("keyring", None)))
    return out


def schema_problems(folder: Path) -> list[str]:
    """What ``mhp validate`` says about a config.schema.json."""
    f = folder / "config.schema.json"
    if not f.is_file():
        return []
    try:
        raw = json.loads(f.read_text(encoding="utf-8"))
    except ValueError as e:
        return [f"config.schema.json: not valid JSON ({e})"]
    if not isinstance(raw, dict):
        return ["config.schema.json must be an object of key -> question"]
    ex = _example(folder)
    out = []
    for key, spec in raw.items():
        if not isinstance(spec, dict):
            out.append(f"config.schema.json/{key}: must be an object"); continue
        kind = spec.get("kind", "text")
        if kind not in KINDS:
            out.append(f"config.schema.json/{key}: unknown kind {kind!r} (one of {', '.join(KINDS)})")
        if kind != "secret" and key not in ex:
            out.append(f"config.schema.json/{key}: not a key of config.example.json")
        if kind == "secret" and not (isinstance(spec.get("keyring"), list) and len(spec["keyring"]) == 2):
            out.append(f"config.schema.json/{key}: a secret needs keyring: [service, user]")
        if kind == "choice" and not spec.get("choices") and not spec.get("choices_from"):
            out.append(f"config.schema.json/{key}: a choice needs choices or choices_from")
        if not spec.get("ask"):
            out.append(f"config.schema.json/{key}: no ask text")
    return out


def setup_help(folder: Path, key: str) -> str:
    """The lines of references/setup.md that talk about ``key``: the help for a fallback question."""
    f = folder / "references" / "setup.md"
    if not f.is_file():
        return ""
    hits = []
    for para in re.split(r"\n\s*\n", f.read_text(encoding="utf-8", errors="replace")):
        for line in para.splitlines():
            if re.search(rf"`{re.escape(key)}`|\b{re.escape(key)}\b", line):
                hits.append(" ".join(para.split()))
                break
    return "\n".join(hits[:2])


def fallback_schema(folder: Path) -> list[Question]:
    """No schema: ask for each string-valued key of the example, in its order."""
    ex = _example(folder)
    out = []
    for key, v in ex.items():
        if not isinstance(v, str):
            continue
        kind = ("com_port" if key in ("port", "com_port", "serial_port") or re.fullmatch(r"(COM\d+|/dev/tty\S*)", v)
                else "url" if re.match(r"https?://", v)
                else "path" if key.endswith(("_dir", "_file", "_dll", "_path")) or re.match(r"([A-Za-z]:[\\/]|/|\\\\)", v)
                else "text")
        out.append(Question(key=key, ask=key.replace("_", " "), kind=kind, example=v, help=setup_help(folder, key)))
    return out


def questions_for(folder: Path) -> list[Question]:
    return load_schema(folder) or fallback_schema(folder)


# ---- the machine ---------------------------------------------------------------------------------
def serial_ports() -> list[str]:
    """Serial ports on this PC, best effort: pyserial if installed, the registry on Windows, /dev otherwise."""
    try:
        from serial.tools import list_ports                                   # pyserial
        return sorted(p.device for p in list_ports.comports())
    except Exception:                                                         # noqa: BLE001
        pass
    if sys.platform == "win32":
        try:
            import winreg
            out = []
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\SERIALCOMM") as k:
                i = 0
                while True:
                    try:
                        out.append(winreg.EnumValue(k, i)[1]); i += 1
                    except OSError:
                        break
            return sorted(out, key=lambda s: (len(s), s))
        except OSError:
            return []
    return sorted(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*") + glob.glob("/dev/tty.usb*") + glob.glob("/dev/cu.usb*"))


def driver_class(folder: Path, sim: bool = False):
    from .package import load_package
    try:
        return load_package(folder).load_driver_class(sim=sim)
    except Exception:                                                         # noqa: BLE001  (vendor import missing, etc.)
        return None


def discover(folder: Path, cfg: dict, what: str, sim: bool = False) -> list:
    """Ask the driver for choices; [] when it has none or cannot reach the instrument."""
    cls = driver_class(folder, sim)
    fn = getattr(cls, "discover", None)
    if fn is None:
        return []
    try:
        return list(fn(cfg, what) or [])
    except Exception as e:                                                    # noqa: BLE001
        raise RuntimeError(f"{type(e).__name__}: {e}") from None


def probe(folder: Path, cfg: dict, sim: bool = False) -> tuple[bool | None, str]:
    """(True, proof) | (False, reason) | (None, '') when the driver has no probe."""
    if sim:
        return True, "simulated twin; no instrument contacted"
    cls = driver_class(folder)
    fn = getattr(cls, "probe", None)
    if fn is None:
        return None, ""
    try:
        text = fn(cfg)
    except Exception as e:                                                    # noqa: BLE001
        return False, str(e) or type(e).__name__
    return (None, "") if text is None else (True, str(text))


# ---- asking -------------------------------------------------------------------------------------
def default_say(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


def default_ask(prompt: str, default: str | None = None, secret: bool = False) -> str:
    if secret:                                                      # secrets never come back through this function
        raise ValueError("ask a secret through secret_asker(ask)")
    own_line = prompt.endswith("\n  ")                               # a question: the answer goes on the line under it
    base = prompt.rstrip()
    dflt = f" [{default}]" if default not in (None, "") and not base.endswith("]") else ""
    shown = base + dflt + ("\n  > " if own_line else " > ")
    print(shown, end="", file=sys.stderr, flush=True)
    try:
        ans = input()
    except EOFError:
        raise Stop() from None
    return ans if ans.strip() else (default or "")


def auto_ask(prompt: str, default: str | None = None, secret: bool = False) -> str:
    """No terminal: a default is taken, anything else is left for a person."""
    if default not in (None, ""):
        return default
    raise Unanswered(prompt)


def hidden_input(prompt: str) -> str:
    """Read a secret with no echo. Its value goes to the keyring and nowhere else."""
    return getpass.getpass(prompt.rstrip() + " > ")


def secret_asker(ask):
    """The callable that collects a secret for the given ``ask``: kept apart from ordinary answers so a
    password is never on the path that prints or re-asks."""
    if ask is default_ask:
        return hidden_input
    if ask is auto_ask:
        return lambda prompt: auto_ask(prompt)
    return lambda prompt: ask(prompt, None, secret=True)


def _yes(ans: str, default: bool = True) -> bool:
    a = ans.strip().lower()
    return default if not a else a in ("y", "yes", "true", "1", "on")


def coerce(q: Question, text: str):
    t = text.strip()
    if q.kind == "int":
        return int(t)
    if q.kind == "bool":
        return _yes(t, False)
    return t


def _fill(template: str, cfg: dict) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: str(cfg.get(m.group(1), "")), template)


def _pick(ans: str, options: list) -> str | None:
    """A number or the exact text of one option; None otherwise."""
    a = ans.strip()
    if a.isdigit() and 1 <= int(a) <= len(options):
        return str(options[int(a) - 1][0] if isinstance(options[int(a) - 1], (list, tuple)) else options[int(a) - 1])
    for o in options:
        val = o[0] if isinstance(o, (list, tuple)) else o
        if a == str(val):
            return str(val)
    return None


def _options_text(options: list) -> str:
    lines = []
    for i, o in enumerate(options, 1):
        if isinstance(o, (list, tuple)) and len(o) >= 2:
            lines.append(f"({i}) {o[0]}  {o[1]}")
        else:
            lines.append(f"({i}) {o[0] if isinstance(o, (list, tuple)) else o}")
    return "  " + "   ".join(lines) if sum(len(x) for x in lines) < 70 else "\n    " + "\n    ".join(lines)


def interview(folder: Path, questions: list[Question], ask=default_ask, say=default_say, *,
              answers: dict | None = None, all_fields: bool = False, sim: bool = False) -> tuple[dict, list[str]]:
    """Ask every question; return (config, keys left unanswered). Starts from config.json when there is one."""
    example, current = _example(folder), _current(folder)
    fresh = MARK not in current                                     # a first run: example values are hints, not defaults
    cfg = dict(example)
    cfg.update(current)
    answers = dict(answers or {})
    ask_secret = secret_asker(ask)
    missing: list[str] = []
    for q in questions:
        if q.advanced and not all_fields and q.key not in answers:
            continue
        if q.key in answers:
            if q.kind == "secret":
                _store_secret(q, cfg, answers[q.key], say)
            else:
                cfg[q.key] = coerce(q, answers[q.key])
            continue
        if q.kind == "secret":
            try:
                val = ask_secret(f"  {_fill(q.ask, cfg)} (goes to the OS keyring, never into a file; Enter to skip)")
            except Unanswered:
                missing.append(q.key); continue
            if val.strip():
                _store_secret(q, cfg, val, say)
            continue
        has_default = (q.key in current and current[q.key] not in (None, "") and not (fresh and current[q.key] == example.get(q.key)))
        default = str(current[q.key]) if has_default else None
        if q.kind == "bool" and q.key in cfg and isinstance(cfg[q.key], bool):
            default = "y" if cfg[q.key] else "n"
        options: list = []
        if q.kind in ("choice", "com_port"):
            options = list(q.choices)
            if not options:
                try:
                    options = discover(folder, cfg, q.choices_from or q.key, sim) if (q.choices_from or q.kind == "choice") else []
                except RuntimeError as e:
                    say(f"  (could not list {q.choices_from or q.key}: {e}; type the value instead)")
                if not options and q.kind == "com_port":
                    options = serial_ports()
        hint = ""
        if options:
            hint = "\n" + _options_text(options)
        elif q.example is not None and not has_default:
            hint = f"   e.g. {q.example}"
        if not q.required and not has_default:
            hint += "   (Enter for none)"
        prompt = f"  {_fill(q.ask, cfg)}{hint}\n  "
        while True:
            try:
                ans = ask(prompt, default)
            except Unanswered:
                missing.append(q.key); break
            if ans.strip() == "?":
                say("    " + (q.help or setup_help(folder, q.key) or "no notes on this one; references/setup.md may help").replace("\n", "\n    "))
                continue
            if not ans.strip():
                if q.required:
                    say("    this one is needed"); continue
                cfg[q.key] = None; break
            if options:
                picked = _pick(ans, options)
                if picked is None:
                    if not _yes(ask(f"    {ans.strip()} is not in the list. Use it anyway? [y/N]", "n"), False):
                        continue
                    picked = ans.strip()
                cfg[q.key] = picked; break
            if q.kind == "url" and not re.match(r"https?://\S+$", ans.strip()):
                say("    needs to start with http:// or https://"); continue
            if q.kind == "int":
                try:
                    cfg[q.key] = int(ans.strip()); break
                except ValueError:
                    say("    a whole number, please"); continue
            if q.kind == "bool":
                cfg[q.key] = _yes(ans, cfg.get(q.key) is True); break
            if q.kind == "path":
                p = Path(ans.strip()).expanduser()
                looks_dir = q.key.endswith("_dir") or not p.suffix
                if not p.exists():
                    if looks_dir:
                        if _yes(ask(f"    {p} does not exist yet. Create it? [Y/n]", "y")):
                            try:
                                p.mkdir(parents=True, exist_ok=True)
                            except OSError as e:
                                say(f"    could not create it: {e}"); continue
                    elif not _yes(ask(f"    {p} was not found. Use it anyway? [y/N]", "n"), False):
                        continue
                cfg[q.key] = str(p); break
            cfg[q.key] = ans.strip(); break
    return cfg, missing


def _store_secret(q: Question, cfg: dict, value: str, say) -> None:
    service, user = (_fill(str(x), cfg) for x in (q.keyring or ["openmhp", q.key]))
    try:
        import keyring
        keyring.set_password(service, user, value)
        say(f"    stored in the OS keyring as {service} / {user}")
    except ImportError:
        say(f"    the keyring package is not installed, so the password was not stored. Later:  pip install keyring  then  "
            f"python -m keyring set {service} {user}")
    except Exception as e:                                                    # noqa: BLE001
        say(f"    could not store it in the keyring ({e}). Later:  python -m keyring set {service} {user}")


MARK = "_configured"                    # written by setup; drivers ignore it. Tells the preflight the values are a person's, not the example's


def write_config(folder: Path, cfg: dict) -> Path:
    """config.json, written whole; the previous one kept as config.json.bak when it differs."""
    import time
    target = folder / "config.json"
    cfg = {k: v for k, v in cfg.items() if k != MARK}
    cfg[MARK] = time.strftime("%Y-%m-%d %H:%M by mhp node setup")
    text = json.dumps(cfg, indent=2, ensure_ascii=False) + "\n"
    if target.is_file() and target.read_text(encoding="utf-8") != text:
        (folder / "config.json.bak").write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
    tmp = folder / "config.json.tmp"
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, target)
    return target


# ---- checks shared with `mhp node --check` ----------------------------------------------------------
def same_json(a: Path, b: Path) -> bool:
    try:
        return json.loads(a.read_text(encoding="utf-8")) == json.loads(b.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False


def preflight_problems(folders: list[Path], host: str, base: int) -> list[str]:
    """What stops each package from serving, in words a person at the bench can act on."""
    from .node_add import config_keys, short
    problems = []
    for i, folder in enumerate(folders):
        ex = folder / "config.example.json"
        cur = _current(folder)
        if ex.is_file() and (not cur or (MARK not in cur and cur == _example(folder))):
            keys = ", ".join(config_keys(folder)) or "the values it asks for"
            problems.append(f"{folder.name}: not set up yet ({keys}). Run:  mhp node setup {folder.name}"
                            + ("" if folder.parent == _default_dir() else f" {short(folder.parent)}"))
        try:
            with socket.socket() as sock:
                sock.bind((host, base + i))
        except OSError:
            problems.append(f"port {base + i} (for {folder.name}) is already in use. Is another `mhp node` running? "
                            f"Close it (or `mhp node --service-status`), or start with  --http {base + 100}")
    return problems


def _default_dir() -> Path:
    from .node_add import default_dir
    return default_dir()


# ---- the flow -------------------------------------------------------------------------------------
def pip_install(pkgs: str, run=None) -> tuple[bool, str]:
    run = run or (lambda argv: subprocess.run(argv, capture_output=True, text=True))
    r = run([sys.executable, "-m", "pip", "install", *pkgs.split()])
    ok = r.returncode == 0
    tail = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
    return ok, (tail[-1] if tail else "")


def setup_package(folder: Path, ask=default_ask, say=default_say, *, answers: dict | None = None, all_fields: bool = False,
                  sim: bool | None = None, pip_run=None, ask_pip: bool = True, pip: bool = True) -> dict:
    """Dependencies, questions, config.json, probe, for one package. Returns what happened."""
    from .node_add import pip_lines, short, this_os, windows_only
    folder = Path(folder)
    name = folder.name
    out = {"name": name, "configured": False, "missing": [], "probe": None, "probe_text": "", "pip": [], "sim": False}
    # 1. the vendor client
    for pkgs in pip_lines(folder):
        if not pip:
            say(f"not installing the vendor client (--no-pip); before serving run:  pip install {pkgs}")
            continue
        try:
            go = (not ask_pip) or _yes(ask(f"install {pkgs} now? [Y/n]", "y"))
        except Unanswered:
            go = True
        if not go:
            continue
        say(f"installing {pkgs} ...")
        ok, last = pip_install(pkgs, pip_run)
        out["pip"].append((pkgs, ok))
        say("  done" if ok else f"  FAILED: {last}\n  (carry on; run  pip install {pkgs}  by hand before serving)")
    # 2. the operating system
    if sim is None:
        sim = False
        if windows_only(folder, None) and sys.platform != "win32":
            try:
                sim = _yes(ask(f"{name} needs the vendor's Windows software, and this is {this_os()}. Set it up for the "
                               f"simulated twin only? [Y/n]", "y"))
            except Unanswered:
                sim = True
    out["sim"] = sim
    # 3. the questions
    if not (folder / "config.example.json").is_file():
        out["configured"] = True
        say(f"{name} needs no settings.")
        return out
    questions = questions_for(folder)
    had_config = MARK in _current(folder)
    say(f"\nA few questions about {name}. " + ("Enter keeps the value in [brackets]; " if had_config else "") + "? explains.")
    cfg, missing = interview(folder, questions, ask, say, answers=answers, all_fields=all_fields, sim=sim)
    out["missing"] = missing
    if missing:
        say(f"not saved: {', '.join(missing)} still need an answer. Run  mhp node setup {name}  at a terminal, or pass --set key=value.")
        return out
    write_config(folder, cfg)
    out["configured"] = True
    kept = [k for k, v in _example(folder).items() if k not in {q.key for q in questions if not q.advanced or all_fields}
            and not isinstance(v, str)]
    say(f"saved {short(folder / 'config.json')}" + (f"   ({', '.join(kept[:5])}{', ...' if len(kept) > 5 else ''} kept at their defaults; edit the file to change them)" if kept else ""))
    # 4. the proof
    while True:
        say("checking ...")
        ok, text = probe(folder, cfg, sim)
        out["probe"], out["probe_text"] = ok, text
        if ok is None:
            say(f"  {name} is configured (its driver has no connection check; the first `mhp node` run is the test)")
            break
        if ok:
            say(f"  {name} is ready: {text}")
            break
        say(f"  {name} did not answer: {text}")
        try:
            choice = ask("  (f)ix an answer, (c)arry on anyway, or (s)top? [f/c/s]", "f").strip().lower()[:1]
        except Unanswered:
            choice = "c"
        if choice == "s":
            raise Stop()
        if choice == "c":
            break
        cfg, missing = interview(folder, questions, ask, say, all_fields=all_fields, sim=sim)
        if missing:
            break
        write_config(folder, cfg)
    return out


def parse_pair_line(text: str) -> tuple[str, str] | None:
    """'https://gw.lab ab12-cd34' -> (url, code); None when it is not that."""
    parts = text.strip().replace(",", " ").split()
    if len(parts) == 2 and parts[0].startswith("https://"):
        return parts[0].rstrip("/"), parts[1]
    if len(parts) == 2 and parts[1].startswith("https://"):
        return parts[1].rstrip("/"), parts[0]
    return None


def finish(root: Path, base: int, ask=default_ask, say=default_say, *, host: str = "127.0.0.1", joiner=None, svc=None,
           load=None) -> dict:
    """After the packages are set up: the gateway, then the service. Returns {'serve': bool, 'joined': cfg|None, 'service': ...}."""
    from . import relay as R
    from . import service as S
    from .node_add import short
    root = Path(root)
    svc = svc or S
    joiner = joiner or R.join
    out = {"serve": False, "joined": None, "service": None}
    folders = sorted(p.parent for p in root.glob("*/DEVICE.md"))
    problems = preflight_problems(folders, host, base)
    if problems:
        say("\nnot serving yet:")
        for p in problems:
            say(f"  - {p}")
        return out
    # the gateway
    joined = R.load_node_config()
    if joined:
        say(f"\nthis PC is paired with {joined.get('gateway')} as '{joined.get('name')}'; the gateway lists the new instrument when the node reconnects.")
        out["joined"] = joined
    else:
        try:
            ans = ask("\nDoes your lab have an OpenMHP gateway? Paste the line from `mhp gateway pair` there (address and code), "
                      "or Enter to skip", None)
        except Unanswered:
            ans = ""
        while ans.strip():
            pair = parse_pair_line(ans)
            if pair is None:
                try:
                    ans = ask("  that is not an address and a code (like  https://gw.lab.local ab12-cd34). Try again, or Enter to skip", None)
                except Unanswered:
                    ans = ""
                continue
            try:
                load = load or _load_all
                drivers = load(folders)
                cfg = joiner(pair[0], pair[1], drivers, name=socket.gethostname().split(".")[0], quiet=True)
                say(f"paired with {cfg['gateway']} as '{cfg['name']}'")
                out["joined"] = cfg
            except SystemExit as e:
                say(f"could not join: {e}")
                try:
                    ans = ask("  paste the line again (a new code from `mhp gateway pair`), or Enter to skip", None)
                except Unanswered:
                    ans = ""
                continue
            break
        if not out["joined"]:
            say("  (later:  mhp node" + ("" if root == _default_dir() else f" {short(root)}") + " --join https://<gateway> <code>)")
    # the service
    st = svc.status()
    if st.get("installed"):
        try:
            go = _yes(ask("\nA background service already runs mhp node on this PC. Restart it so it picks up the new instrument? [Y/n]", "y"))
        except Unanswered:
            go = True
        if go:
            r = svc.restart(root, base)
            out["service"] = r
            say("restarted; the service serves the new instrument now." if r.get("ok") else f"could not restart the service: {r.get('error') or r.get('steps')}")
            return out
    else:
        try:
            go = _yes(ask("\nRun in the background from now on, also after reboots? [Y/n]", "y"))
        except Unanswered:
            go = False
        if go:
            r = svc.install(root, base)
            out["service"] = r
            if r.get("ok"):
                say(f"installed; {r.get('note', 'running')}" + (" Agents can find this PC's instruments through the gateway now." if out["joined"] else ""))
                say("  (mhp node --service-status  says how it is doing;  mhp node --uninstall-service  removes it)")
                return out
            say(f"could not install the service: {r.get('error') or '; '.join(r.get('steps', []))}. Serving in this window instead.")
    out["serve"] = True
    return out


def _load_all(folders: list[Path]) -> dict:
    from .package import load_driver
    drivers = {}
    for f in folders:
        try:
            drv = load_driver(f)
            drivers[drv.descriptor["device"]["id"]] = drv
        except Exception:                                                     # noqa: BLE001  one package must not stop the join
            pass
    return drivers


def interactive(yes: bool = False, no_setup: bool = False) -> bool:
    return not yes and not no_setup and sys.stdin.isatty() and sys.stderr.isatty()


def run(folders: list[Path], root: Path, base: int, *, yes: bool = False, sets: list[str] | None = None, all_fields: bool = False,
        no_pip: bool = False, ask=None, say=default_say, **kw) -> int | str:
    """Set up each folder, then finish. Returns 0, 1, or 'serve:<dir>' when the node should start in this window."""
    answers = {}
    for s in sets or []:
        k, _, v = s.partition("=")
        answers[k.strip()] = v
    ask = ask or (auto_ask if yes or not interactive() else default_ask)
    try:
        results = [setup_package(f, ask, say, answers=answers if len(folders) == 1 else None, all_fields=all_fields,
                                 ask_pip=ask is not auto_ask, pip=not no_pip, **kw) for f in folders]
        if not all(r["configured"] for r in results):
            return 1
        fin = finish(root, base, ask, say)
    except Stop:
        say("stopped. Nothing else was changed; run  mhp node setup  to continue later.")
        return 1
    except KeyboardInterrupt:
        say("\nstopped. Run  mhp node setup  to continue later.")
        return 1
    return f"serve:{root}" if fin["serve"] and ask is not auto_ask else 0


def main(args: list[str], root: Path | None = None, base: int = 18900, **opts) -> int | str:
    """``mhp node setup [<package>] [<dir>]``."""
    from .node_add import default_dir, short
    name = args[0] if args else None
    root = Path(args[1]).expanduser() if len(args) > 1 else Path(root) if root else default_dir()
    folders = sorted(p.parent for p in root.glob("*/DEVICE.md"))
    if name:
        folders = [f for f in folders if f.name == name]
        if not folders:
            print(f"no package named {name} in {short(root)}. `mhp node add {name}` puts it there.", file=sys.stderr)
            return 1
    if not folders:
        print(f"no device packages in {short(root)}. Add one with:  mhp node add <package>", file=sys.stderr)
        return 1
    return run(folders, root, base, **opts)
