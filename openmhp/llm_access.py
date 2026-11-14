"""How a gateway's runs sign in to their model: see what this machine can use, choose one, test it.

    mhp gateway llm                       what this machine could use for runs, and which one runs use now
    mhp gateway llm use api-key                          < key      an Anthropic API key
    mhp gateway llm use claude-token                     < token    a Claude subscription token from `claude setup-token`
                                                                    (Team and Enterprise seats sign in there with SSO)
    mhp gateway llm use llm-gateway url=https://llm.corp.example < token
                                                                    a company LLM gateway or proxy in front of Claude
    mhp gateway llm use bedrock profile=NAME region=us-east-1       Amazon Bedrock with an AWS profile, including
                                                                    IAM Identity Center (SSO) profiles
    mhp gateway llm use vertex project=ID region=us-east5 [credentials=FILE]
                                                                    Google Vertex AI with application default credentials
    mhp gateway llm use foundry resource=NAME            < key      Microsoft Foundry
    mhp gateway llm use helper command="/opt/corp/llm-token" [var=ANTHROPIC_AUTH_TOKEN] [url=...]
                                                                    any command that prints a fresh key or token
    mhp gateway llm test                  check the chosen sign-in as a run would see it (free: no model call)
    mhp gateway llm test call             ... and make one tiny model call (costs a fraction of a cent)

Most companies sign in to Claude through SSO rather than with a raw API key. On a gateway that means one of:
a Claude Team or Enterprise seat (its token from `claude setup-token`), a cloud account (Bedrock, Vertex or
Foundry, where SSO gives short-lived credentials), a company LLM gateway, or a helper script the company
provides. Short-lived credentials are fetched again before every turn of every run, by the gateway's own
account, so a run never holds more than one turn's worth and an SSO session is used as long as it lasts.

Runs never use this account's own sign-in: they get only the chosen credentials, and Claude Code runs with a
configuration folder of its own (CLAUDE_CONFIG_DIR) so it cannot find the operator's login. Secrets stay in
<gateway>/llm.env (this account only); the choice, without secrets, is in <gateway>/llm.json.
"""
from __future__ import annotations

import configparser
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

METHODS = ("api-key", "claude-token", "llm-gateway", "bedrock", "vertex", "foundry", "helper")
SECRET = {"api-key": "ANTHROPIC_API_KEY", "claude-token": "CLAUDE_CODE_OAUTH_TOKEN",
          "llm-gateway": "ANTHROPIC_AUTH_TOKEN", "foundry": "ANTHROPIC_FOUNDRY_API_KEY"}
EXPECT = {"api-key": ("api_key", "firstParty"), "claude-token": ("oauth_token", "firstParty"),
          "llm-gateway": (None, "firstParty"), "bedrock": ("third_party", "bedrock"),
          "vertex": ("third_party", "vertex"), "foundry": ("third_party", "foundry"), "helper": (None, None)}


class LLMAccessError(RuntimeError):
    """The gateway could not get credentials for a run's turn. The message says what the operator should do."""


def _paths(gw_dir: Path) -> tuple[Path, Path]:
    return Path(gw_dir) / "llm.json", Path(gw_dir) / "llm.env"


def _read_env(path: Path) -> dict:
    out = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    except OSError:
        pass
    return out


def _write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def chosen(gw_dir: Path) -> dict | None:
    """The sign-in runs use, without secrets; None when there is none. A gateway set up before this existed
    (only llm.env, from `mhp gateway llm-key`) counts as a static one."""
    cfg_path, env_path = _paths(gw_dir)
    try:
        return json.loads(cfg_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    env = _read_env(env_path)
    return {"method": "static", "vars": sorted(env)} if env else None


def configured(gw_dir: Path) -> bool:
    return chosen(gw_dir) is not None


def choose(gw_dir: Path, method: str, opts: dict, secret: str | None = None) -> dict:
    """Save the sign-in runs use. Replaces any earlier one entirely, so an old key cannot outrank the new method."""
    if method not in METHODS:
        raise ValueError(f"no sign-in method {method!r}; one of: {', '.join(METHODS)}")
    cfg = {"method": method, "chosen": time.strftime("%Y-%m-%dT%H:%M:%S")}
    env, secrets = {}, {}
    need = {"llm-gateway": ("url",), "bedrock": ("profile", "region"), "vertex": ("project", "region"),
            "foundry": ("resource",), "helper": ("command",)}.get(method, ())
    missing = [k for k in need if not opts.get(k)]
    if missing:
        raise ValueError(f"{method} needs " + ", ".join(f"{k}=..." for k in missing))
    if method in SECRET:
        if not secret or "\n" in secret.strip():
            raise ValueError(f"{method} needs its key or token as one line on stdin")
        secrets[SECRET[method]] = secret.strip()
    if method == "llm-gateway":
        if not str(opts["url"]).startswith("https://"):
            raise ValueError("url must start with https://")
        env["ANTHROPIC_BASE_URL"] = opts["url"]
    elif method == "bedrock":
        if not shutil.which("aws"):
            raise ValueError("bedrock needs the AWS CLI (v2) on the gateway, to fetch short-lived credentials")
        cfg["profile"] = opts["profile"]
        env.update(CLAUDE_CODE_USE_BEDROCK="1", AWS_REGION=opts["region"])
    elif method == "vertex":
        creds = Path(opts.get("credentials") or Path.home() / ".config" / "gcloud" / "application_default_credentials.json")
        if not creds.is_file():
            raise ValueError(f"no Google credentials at {creds}: run `gcloud auth application-default login` on the "
                             "gateway, or give credentials=<service account key file>")
        env.update(CLAUDE_CODE_USE_VERTEX="1", CLOUD_ML_REGION=opts["region"], ANTHROPIC_VERTEX_PROJECT_ID=opts["project"],
                   GOOGLE_APPLICATION_CREDENTIALS=str(creds.resolve()))
    elif method == "foundry":
        env.update(CLAUDE_CODE_USE_FOUNDRY="1", ANTHROPIC_FOUNDRY_RESOURCE=opts["resource"])
    elif method == "helper":
        var = opts.get("var") or "ANTHROPIC_API_KEY"
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", var):
            raise ValueError(f"{var!r} is not an environment variable name")
        cfg.update(command=shlex.split(opts["command"]), var=var)
        if opts.get("url"):
            env["ANTHROPIC_BASE_URL"] = opts["url"]
    if opts.get("model"):
        env["ANTHROPIC_MODEL"] = opts["model"]
    cfg["env"] = env
    cfg_path, env_path = _paths(gw_dir)
    _write_private(env_path, "".join(f"{k}={v}\n" for k, v in secrets.items()))
    _write_private(cfg_path, json.dumps(cfg, indent=1))
    return cfg


def _run(cmd: list[str], what: str, timeout: float = 60) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise LLMAccessError(f"{what}: {cmd[0]!r} is not installed on the gateway") from None
    except subprocess.TimeoutExpired:
        raise LLMAccessError(f"{what}: {cmd[0]} did not answer within {timeout:.0f} s") from None
    if p.returncode != 0:
        detail = (p.stderr or p.stdout).strip().splitlines()
        raise LLMAccessError(f"{what}: {cmd[0]} failed ({detail[-1][:300] if detail else 'exit ' + str(p.returncode)})")
    return p.stdout


def turn_env(gw_dir: Path) -> dict:
    """The environment one turn of a run signs in with. Short-lived credentials are fetched now, for this turn.
    Raises LLMAccessError with what the operator should do when they cannot be had."""
    cfg = chosen(gw_dir)
    if cfg is None:
        raise LLMAccessError("this gateway has no sign-in for runs yet: its operator chooses one with `mhp gateway llm`")
    env = dict(cfg.get("env") or {})
    env.update(_read_env(_paths(gw_dir)[1]))
    m = cfg["method"]
    if m == "bedrock":
        prof = cfg["profile"]
        out = _run(["aws", "configure", "export-credentials", "--profile", prof, "--format", "process"],
                   f"AWS profile {prof!r}")
        try:
            c = json.loads(out)
            env.update(AWS_ACCESS_KEY_ID=c["AccessKeyId"], AWS_SECRET_ACCESS_KEY=c["SecretAccessKey"])
            if c.get("SessionToken"):
                env["AWS_SESSION_TOKEN"] = c["SessionToken"]
        except (ValueError, KeyError):
            raise LLMAccessError(f"AWS profile {prof!r}: the AWS CLI did not return credentials") from None
    elif m == "helper":
        token = _run(cfg["command"], "the sign-in helper").strip()
        if not token or "\n" in token:
            raise LLMAccessError("the sign-in helper must print one line: the key or token")
        env[cfg["var"]] = token
    elif m == "vertex" and not Path(env.get("GOOGLE_APPLICATION_CREDENTIALS", "")).is_file():
        raise LLMAccessError("the Google credentials file for runs is gone: run `gcloud auth application-default "
                             "login` on the gateway, then `mhp gateway llm use vertex ...` again")
    return env


# ---- what this machine has ---------------------------------------------------------------------------
def _aws_profiles(home: Path) -> list[dict]:
    cp = configparser.ConfigParser()
    try:
        cp.read([home / ".aws" / "config"], encoding="utf-8")
    except configparser.Error:
        return []
    out = []
    for sec in cp.sections():
        name = sec[8:] if sec.startswith("profile ") else (sec if sec == "default" else None)
        if name:
            s = cp[sec]
            out.append({"name": name, "sso": bool(s.get("sso_session") or s.get("sso_start_url")), "region": s.get("region")})
    return out


def probe(home: Path | None = None, environ: dict | None = None, which=shutil.which) -> list[dict]:
    """Every way this machine could sign runs in, found or not. Names and places only: never a secret's value."""
    home, environ = Path(home or Path.home()), os.environ if environ is None else environ
    rows = []

    def row(method, found, what, use):
        rows.append({"method": method, "found": bool(found), "what": what, "use": use})

    row("api-key", environ.get("ANTHROPIC_API_KEY"), "ANTHROPIC_API_KEY is set in this shell" if environ.get("ANTHROPIC_API_KEY")
        else "an Anthropic API key, from console.anthropic.com or your company's admin", "mhp gateway llm use api-key < key")
    claude = which("claude")
    row("claude-token", environ.get("CLAUDE_CODE_OAUTH_TOKEN"),
        "CLAUDE_CODE_OAUTH_TOKEN is set in this shell" if environ.get("CLAUDE_CODE_OAUTH_TOKEN") else
        ("a Claude Team or Enterprise seat (SSO) or a Claude subscription: run `claude setup-token` and sign in"
         if claude else "a Claude subscription token: install Claude Code, then run `claude setup-token`"),
        "mhp gateway llm use claude-token < token")
    url = environ.get("ANTHROPIC_BASE_URL")
    if url and re.match(r"^https://api\.anthropic\.com/?$", url):
        url = None                                     # Anthropic's own address: not a company gateway
    row("llm-gateway", url, f"ANTHROPIC_BASE_URL points at {url}" if url else "a company LLM gateway in front of Claude",
        f"mhp gateway llm use llm-gateway url={url or 'https://...'} < token")
    profiles = _aws_profiles(home)
    if which("aws") and profiles:
        names = ", ".join(p["name"] + (" (SSO)" if p["sso"] else "") for p in profiles)
        p0 = next((p for p in profiles if p["sso"]), profiles[0])
        row("bedrock", True, f"AWS CLI with profiles: {names}",
            f"mhp gateway llm use bedrock profile={p0['name']} region={p0['region'] or 'us-east-1'}")
    else:
        row("bedrock", False, "Amazon Bedrock: needs the AWS CLI and a profile (`aws configure sso` for SSO)",
            "mhp gateway llm use bedrock profile=NAME region=REGION")
    adc = home / ".config" / "gcloud" / "application_default_credentials.json"
    gac = environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    project = environ.get("ANTHROPIC_VERTEX_PROJECT_ID") or environ.get("GOOGLE_CLOUD_PROJECT") or "ID"
    found_g = adc.is_file() or (gac and Path(gac).is_file())
    row("vertex", found_g, ("Google application default credentials are set up" if found_g else
                            "Google Vertex AI: needs `gcloud auth application-default login` or a service account key"),
        f"mhp gateway llm use vertex project={project} region=REGION" + (f" credentials={gac}" if gac else ""))
    res = environ.get("ANTHROPIC_FOUNDRY_RESOURCE")
    row("foundry", res, f"Foundry resource {res}" if res else "Microsoft Foundry: needs a resource name and key",
        f"mhp gateway llm use foundry resource={res or 'NAME'} < key")
    helper = None
    try:
        helper = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8")).get("apiKeyHelper")
    except (OSError, ValueError, AttributeError):
        pass
    row("helper", helper, f"Claude Code here uses a key helper: {helper}" if helper else
        "a command your company provides that prints a fresh key or token",
        f'mhp gateway llm use helper command="{helper or "/path/to/helper"}"')
    return rows


def own_login() -> str | None:
    """How this account's own Claude Code is signed in (free; no model call), to say it is not used for runs."""
    if not shutil.which("claude"):
        return None
    try:
        p = subprocess.run(["claude", "auth", "status", "--json"], capture_output=True, text=True, timeout=30,
                           env={k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")})
        doc = json.loads(p.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    return doc.get("authMethod") if doc.get("loggedIn") else None


# ---- testing it as a run would ------------------------------------------------------------------------
def test(gw_dir: Path, call: bool = False) -> list[tuple[bool, str]]:
    """Check the chosen sign-in the way a run's turn gets it: fetch the credentials, then ask Claude Code, in a
    configuration folder of its own and with no other credential, how it would sign in. With call=True, also
    make one tiny model call."""
    import tempfile
    from .harness import run_environment
    steps = []
    cfg = chosen(gw_dir)
    if cfg is None:
        return [(False, "no sign-in chosen for runs: see `mhp gateway llm`")]
    try:
        env = turn_env(gw_dir)
        steps.append((True, f"credentials for a turn ({cfg['method']}): " + ", ".join(sorted(env)) + " (values not shown)"))
    except LLMAccessError as e:
        return steps + [(False, str(e))]
    if not shutil.which("claude"):
        return steps + [(False, "Claude Code (`claude`) is not installed on the gateway")]
    with tempfile.TemporaryDirectory(prefix="openmhp-llm-test-") as home:
        run_env = run_environment({**env, "CLAUDE_CONFIG_DIR": home})
        try:
            p = subprocess.run(["claude", "auth", "status", "--json"], capture_output=True, text=True, timeout=60, env=run_env)
            doc = json.loads(p.stdout)
        except (OSError, ValueError, subprocess.TimeoutExpired) as e:
            return steps + [(False, f"Claude Code could not report its sign-in: {e}")]
        method, provider = EXPECT.get(cfg["method"], (None, None))
        ok = bool(doc.get("loggedIn")) and (method is None or doc.get("authMethod") == method) \
            and (provider is None or doc.get("apiProvider") == provider)
        steps.append((ok, f"a run's Claude Code signs in with {doc.get('authMethod')} via {doc.get('apiProvider')}"
                      + ("" if ok else f" (expected {method or 'any'} via {provider or 'any'})")))
        if ok and call:
            try:
                p = subprocess.run(["claude", "-p", "Reply with the single word OK.", "--output-format", "json",
                                    "--max-turns", "1", "--max-budget-usd", "0.05", "--strict-mcp-config"],
                                   capture_output=True, text=True, timeout=180, env=run_env, cwd=home)
                doc = json.loads(p.stdout.strip().splitlines()[-1]) if p.stdout.strip() else {}
            except (OSError, ValueError, IndexError, subprocess.TimeoutExpired) as e:
                return steps + [(False, f"the test call failed: {e}")]
            good = not doc.get("is_error") and p.returncode == 0
            steps.append((good, f"one model call: {'answered' if good else 'failed'} "
                                f"(${float(doc.get('total_cost_usd') or 0):.4f})"
                          + ("" if good else f": {(doc.get('result') or p.stderr or '').strip()[:300]}")))
    return steps


# ---- the command ----------------------------------------------------------------------------------------
def _opts(words: list[str]) -> dict:
    out = {}
    for w in words:
        if "=" not in w:
            raise ValueError(f"expected name=value, got {w!r}")
        k, v = w.split("=", 1)
        out[k] = v
    return out


def main(gw_dir: Path, words: list[str], say=print) -> int:
    verb = words[0] if words else "probe"
    try:
        if verb == "probe":
            cur = chosen(gw_dir)
            say("runs sign in with: " + (cur["method"] + (f" (profile {cur['profile']})" if cur.get("profile") else "")
                                         if cur else "nothing yet"))
            say("")
            say("what this machine could use for runs:")
            for r in probe():
                say(f"  [{'x' if r['found'] else ' '}] {r['method']:<13} {r['what']}")
                say(f"      {r['use']}")
            mine = own_login()
            if mine:
                say("")
                say(f"This account's own Claude Code is signed in ({mine}). Runs never use it: they get only the "
                    "sign-in chosen above.")
            return 0
        if verb == "use":
            if len(words) < 2:
                raise ValueError("use <method> [name=value ...]; methods: " + ", ".join(METHODS))
            method, opts = words[1], _opts(words[2:])
            secret = None
            if method in SECRET:
                if sys.stdin.isatty():
                    import getpass
                    secret = getpass.getpass(f"{SECRET[method]} for runs on this gateway: ")
                else:
                    secret = sys.stdin.read()
            cfg = choose(gw_dir, method, opts, secret)
            say(f"runs on this gateway now sign in with {method}" + (f" (profile {cfg['profile']})" if cfg.get("profile") else "")
                + ". Check it with: mhp gateway llm test")
            return 0
        if verb == "show":
            say(json.dumps(chosen(gw_dir) or {"method": None}, indent=1))
            return 0
        if verb == "test":
            steps = test(gw_dir, call=len(words) > 1 and words[1] == "call")
            for ok, text in steps:
                say(f"  {'OK ' if ok else 'FIX'} {text}")
            return 0 if steps and all(ok for ok, _ in steps) else 1
    except ValueError as e:
        say(f"llm: {e}")
        return 2
    say(__doc__.split("\n\n")[1])
    return 2
