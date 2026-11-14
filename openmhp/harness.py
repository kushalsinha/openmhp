"""Harness adapters: how the gateway starts and keeps an agent session for a run.

The supervisor never talks to a model itself. A run's agent is one harness session for the whole run: a
harness that can stay open (Claude Code, in its streaming mode) runs as ONE long-lived process, started at
approval and fed each piece of news (an instrument job finished, the scientist answered, a background script
ended) as a new message. Its MCP servers, tools and background scripts live as long as the run, and between
messages it is idle (no model calls). If the process dies, or the gateway restarts, it is started again on
the same session (--resume), so the conversation carries on. A harness that cannot stay open runs one
non-interactive turn per piece of news on the same session instead (run_turn). Each harness gets an adapter;
the supervisor, charter and folders do not change when another harness is added.

    live = open_live(adapter, Turn(workdir=..., session=..., mcp_config=..., instructions=...))
    result = live.send("[12:01] instrument: gc-01 job j7 finished", timeout_s=3600)

    adapter = ADAPTERS["claude-code"]
    result = run_turn(adapter, Turn(prompt=..., workdir=..., session=..., mcp_config=..., instructions=...))

Claude Code runs in print mode with JSON output, a strict MCP configuration (only the run's servers),
`dontAsk` permissions with an explicit list of allowed tools (anything else is denied, never asked),
the run's instructions appended to its system prompt, and per-wake caps on turns and spend. Skills the
scientist handed over are copied to `<workdir>/.claude/skills/`, where Claude Code finds them.
"""
from __future__ import annotations

import collections
import json
import os
import queue
import shlex
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

# The run's tools, by MCP name: instruments through the gateway, and the run's own tools.
INSTRUMENT_TOOLS = ("mhp_find", "mhp_describe", "mhp_read", "mhp_write", "mhp_invoke", "mhp_job", "mhp_estop",
                    "mhp_run", "mhp_data", "mhp_method")
RUN_TOOLS = ("ask_scientist", "report", "propose_charter", "finish")   # the run server offers each phase its own
FILE_TOOLS = ("Read", "Edit", "Write", "Glob", "Grep", "Bash")
# Credentials a harness might pick up from the gateway's own environment. A run gets exactly the gateway's LLM
# key for runs (Turn.env) and none of these, so an operator's own login never pays for or answers as a run.
CREDENTIAL_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_BASE_URL",
                   "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY", "AWS_BEARER_TOKEN_BEDROCK",
                   "OPENAI_API_KEY", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT",
                   "CLAUDE_CONFIG_DIR", "ANTHROPIC_MODEL", "ANTHROPIC_FOUNDRY_API_KEY", "ANTHROPIC_FOUNDRY_RESOURCE",
                   "ANTHROPIC_VERTEX_PROJECT_ID", "CLOUD_ML_REGION", "GOOGLE_APPLICATION_CREDENTIALS",
                   "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_PROFILE",
                   "AWS_DEFAULT_PROFILE", "AWS_REGION")


def run_environment(extra: dict) -> dict:
    """The gateway's environment without any credential, plus what the run is given."""
    env = {k: v for k, v in os.environ.items() if k not in CREDENTIAL_VARS and not k.startswith("CLAUDE_CODE_SESSION")}
    env.update(extra)
    return env


def llm_env(path: Path) -> dict:
    """The gateway's LLM credentials for runs: KEY=VALUE lines in a file only the gateway's account reads
    (`<gateway>/llm.env`, e.g. ANTHROPIC_API_KEY=...). Empty when there is none."""
    out = {}
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    except OSError:
        pass
    return out


@dataclass
class Turn:
    prompt: str
    workdir: Path
    session: str | None = None             # None: a new session; the adapter picks its ID
    mcp_config: Path | None = None
    instructions: Path | None = None       # appended to the harness's system prompt
    model: str | None = None
    max_turns: int = 40
    max_budget_usd: float | None = None
    env: dict = field(default_factory=dict)
    run_as: str | None = None               # a Linux user to run as (sudo -n -u), or None for this one
    timeout_s: float = 3600
    isolate: bool = True                    # the harness gets a configuration folder of its own (no operator login)


@dataclass
class TurnResult:
    ok: bool
    session: str | None
    text: str = ""
    cost_usd: float = 0.0
    tokens: int = 0
    reason: str = ""                        # why it ended early: max_turns, budget, error, timeout, not installed
    raw: dict = field(default_factory=dict)


class Adapter:
    name = "base"
    program = ""

    def available(self) -> bool:
        return shutil.which(self.program) is not None

    def command(self, turn: Turn, session: str, first: bool) -> list[str]:
        raise NotImplementedError

    def parse(self, stdout: str, stderr: str, code: int, session: str) -> TurnResult:
        raise NotImplementedError

    def isolation(self, workdir: Path) -> dict:
        """Environment that keeps the harness from finding the gateway operator's own sign-in and settings."""
        return {}

    def live_command(self, turn: "Turn", session: str, first: bool) -> list[str] | None:
        """The command for a session that stays open and takes messages on stdin, or None if this harness
        cannot stay open (then each message is a turn of its own)."""
        return None


class ClaudeCode(Adapter):
    name, program = "claude-code", "claude"
    needs_llm_key = True                    # runs use the gateway's sign-in for runs, never an inherited login

    def isolation(self, workdir: Path) -> dict:
        # Claude Code keeps its login, settings and sessions under CLAUDE_CONFIG_DIR (default ~/.claude). Each run
        # folder gets its own, so a run finds neither the operator's login nor their settings, and its sessions
        # (which --resume needs between turns) stay with the run.
        home = Path(workdir) / ".claude-home"
        home.mkdir(parents=True, exist_ok=True)
        return {"CLAUDE_CONFIG_DIR": str(home)}

    def allowed_tools(self) -> str:
        mcp = [f"mcp__openmhp__{t}" for t in INSTRUMENT_TOOLS] + [f"mcp__run__{t}" for t in RUN_TOOLS]
        return ",".join(list(FILE_TOOLS) + mcp)

    def live_command(self, turn: Turn, session: str, first: bool) -> list[str]:
        # one process for the whole run: messages arrive as stream-json lines on stdin, and every reply ends with a
        # result line on stdout. No --max-turns: it would count across the whole run; the run's budget caps it.
        cmd = [self.program, "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
               "--permission-mode", "dontAsk", "--allowedTools", self.allowed_tools()]
        return cmd + self._session_args(turn, session, first)

    def _session_args(self, turn: Turn, session: str, first: bool) -> list[str]:
        cmd = ["--session-id", session] if first else ["--resume", session]
        if turn.mcp_config:
            cmd += ["--mcp-config", str(turn.mcp_config), "--strict-mcp-config"]
        if turn.instructions and first:                    # recorded with the session; reused when resumed
            cmd += ["--append-system-prompt-file", str(turn.instructions)]
        if turn.max_budget_usd:
            cmd += ["--max-budget-usd", f"{turn.max_budget_usd:.2f}"]
        if turn.model:
            cmd += ["--model", turn.model]
        return cmd

    def command(self, turn: Turn, session: str, first: bool) -> list[str]:
        cmd = [self.program, "-p", turn.prompt, "--output-format", "json", "--permission-mode", "dontAsk",
               "--allowedTools", self.allowed_tools(), "--max-turns", str(turn.max_turns)]
        cmd += ["--session-id", session] if first else ["--resume", session]
        if turn.mcp_config:
            cmd += ["--mcp-config", str(turn.mcp_config), "--strict-mcp-config"]
        if turn.instructions and first:                    # recorded with the session; reused when resumed
            cmd += ["--append-system-prompt-file", str(turn.instructions)]
        if turn.max_budget_usd:
            cmd += ["--max-budget-usd", f"{turn.max_budget_usd:.2f}"]
        if turn.model:
            cmd += ["--model", turn.model]
        return cmd

    def parse(self, stdout: str, stderr: str, code: int, session: str) -> TurnResult:
        try:
            doc = json.loads(stdout.strip().splitlines()[-1]) if stdout.strip() else {}
        except (ValueError, IndexError):
            doc = {}
        sub = doc.get("subtype", "")
        usage = doc.get("usage") or {}
        tokens = sum(int(usage.get(k) or 0) for k in ("input_tokens", "output_tokens",
                                                       "cache_creation_input_tokens", "cache_read_input_tokens"))
        reason = {"error_max_turns": "max_turns", "error_max_budget_usd": "budget"}.get(sub, "")
        ok = code == 0 and bool(doc) and not doc.get("is_error") and sub in ("", "success")
        if not ok and not reason:
            reason = "error"
        return TurnResult(ok=ok, session=doc.get("session_id") or session, text=doc.get("result") or (stderr or "")[-2000:],
                          cost_usd=float(doc.get("total_cost_usd") or 0.0), tokens=tokens, reason=reason, raw=doc)


class Command(Adapter):
    """Any program that takes the prompt as its last argument and prints {"session", "text", "cost_usd", "tokens",
    "ok"} as JSON: for harnesses without an adapter yet, and for tests. With live=True the program instead stays
    open and speaks Claude Code's stream-json protocol on stdin and stdout (the subset LiveSession reads)."""
    name = "command"

    def __init__(self, argv: list[str], live: bool = False):
        self.argv = list(argv)
        self.program = argv[0]
        self.live = live

    def live_command(self, turn: Turn, session: str, first: bool) -> list[str] | None:
        if not self.live:
            return None
        extra = ["--session", session, "--workdir", str(turn.workdir), "--live"]
        if turn.mcp_config:
            extra += ["--mcp-config", str(turn.mcp_config)]
        return self.argv + extra + ([] if first else ["--resume"])

    def command(self, turn: Turn, session: str, first: bool) -> list[str]:
        extra = ["--session", session, "--workdir", str(turn.workdir)]
        if turn.mcp_config:
            extra += ["--mcp-config", str(turn.mcp_config)]
        return self.argv + extra + [turn.prompt]

    def parse(self, stdout: str, stderr: str, code: int, session: str) -> TurnResult:
        try:
            doc = json.loads(stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            return TurnResult(ok=False, session=session, text=(stderr or stdout)[-2000:], reason="error")
        return TurnResult(ok=code == 0 and doc.get("ok", True), session=doc.get("session") or session,
                          text=doc.get("text", ""), cost_usd=float(doc.get("cost_usd") or 0), tokens=int(doc.get("tokens") or 0),
                          reason="" if code == 0 else "error", raw=doc)


ADAPTERS: dict[str, Adapter] = {"claude-code": ClaudeCode()}


def install_skills(handed_over: Path, workdir: Path) -> list[str]:
    """Copy every skill folder (one with a SKILL.md) the scientist handed over to <workdir>/.claude/skills/."""
    dest = Path(workdir) / ".claude" / "skills"
    out = []
    for md in sorted(Path(handed_over).rglob("SKILL.md")):
        src = md.parent
        target = dest / src.name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(src, target, symlinks=False)
        out.append(src.name)
    return out


def run_turn(adapter: Adapter, turn: Turn) -> TurnResult:
    """One wake of a run's agent: blocks until the harness finishes its turn."""
    first = turn.session is None
    session = turn.session or str(uuid.uuid4())
    if not adapter.available():
        return TurnResult(ok=False, session=turn.session, reason="not installed",
                          text=f"{adapter.program!r} is not installed on this gateway")
    cmd = adapter.command(turn, session, first)
    given = {**turn.env, **(adapter.isolation(turn.workdir) if turn.isolate else {})}
    env = run_environment(given)
    if turn.run_as:
        keep = ",".join(sorted(given))
        cmd = ["sudo", "-n", "-u", turn.run_as] + ([f"--preserve-env={keep}"] if keep else []) + cmd
    try:
        p = subprocess.run(cmd, cwd=str(turn.workdir), env=env, capture_output=True, text=True, timeout=turn.timeout_s)
    except subprocess.TimeoutExpired:
        return TurnResult(ok=False, session=session, reason="timeout", text=f"the turn ran past {turn.timeout_s:.0f} s")
    return adapter.parse(p.stdout, p.stderr, p.returncode, session)


class LiveSession:
    """A run's harness session, kept open between messages. Not thread-safe: one sender at a time (the supervisor
    holds the run's lock). Costs reported in its result lines are totals for the process, so each message is
    charged the difference."""

    def __init__(self, cmd: list[str], cwd: Path, env: dict, session: str):
        self.session = session
        self.p = subprocess.Popen(cmd, cwd=str(cwd), env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, bufsize=1)
        self.lines: queue.Queue = queue.Queue()
        self.stderr = collections.deque(maxlen=40)
        self.cost_seen = 0.0
        threading.Thread(target=self._read, daemon=True, name="live-out").start()
        threading.Thread(target=self._drain, daemon=True, name="live-err").start()

    def _read(self) -> None:
        for line in self.p.stdout:
            try:
                self.lines.put(json.loads(line))
            except ValueError:
                continue
        self.lines.put(None)                                   # the process closed its output: it has ended

    def _drain(self) -> None:
        for line in self.p.stderr:
            self.stderr.append(line.rstrip())

    def alive(self) -> bool:
        return self.p.poll() is None

    def send(self, text: str, timeout_s: float = 3600) -> TurnResult:
        """One message in, the session's reply out. Blocks until its result line, the process ending, or the timeout."""
        try:
            self.p.stdin.write(json.dumps({"type": "user", "message": {"role": "user", "content": text}}) + "\n")
            self.p.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            return TurnResult(ok=False, session=self.session, reason="exited", text=self._why())
        end = time.time() + timeout_s
        while True:
            try:
                ev = self.lines.get(timeout=max(0.0, end - time.time()))
            except queue.Empty:
                return TurnResult(ok=False, session=self.session, reason="timeout", text=f"no reply within {timeout_s:.0f} s")
            if ev is None:
                return TurnResult(ok=False, session=self.session, reason="exited", text=self._why())
            if ev.get("type") != "result":
                continue
            total = float(ev.get("total_cost_usd") or 0.0)
            cost = total - self.cost_seen if total >= self.cost_seen else total
            self.cost_seen = max(self.cost_seen, total)
            usage = ev.get("usage") or {}
            tokens = sum(int(usage.get(k) or 0) for k in ("input_tokens", "output_tokens",
                                                           "cache_creation_input_tokens", "cache_read_input_tokens"))
            sub = ev.get("subtype", "")
            reason = {"error_max_turns": "max_turns", "error_max_budget_usd": "budget"}.get(sub, "")
            ok = not ev.get("is_error") and sub in ("", "success")
            self.session = ev.get("session_id") or self.session
            return TurnResult(ok=ok, session=self.session, text=ev.get("result") or "", cost_usd=round(cost, 6),
                              tokens=tokens, reason=reason or ("" if ok else "error"), raw=ev)

    def _why(self) -> str:
        code = self.p.poll()
        tail = " | ".join(list(self.stderr)[-5:])
        return f"the session ended (exit {code})" + (f": {tail[-600:]}" if tail else "")

    def close(self, wait_s: float = 15) -> None:
        """End the session: close its input (it finishes what it is doing and exits), then make sure it is gone."""
        try:
            self.p.stdin.close()
        except OSError:
            pass
        try:
            self.p.wait(wait_s)
        except subprocess.TimeoutExpired:
            self.p.terminate()
            try:
                self.p.wait(5)
            except subprocess.TimeoutExpired:
                self.p.kill()


def open_live(adapter: Adapter, turn: Turn) -> "LiveSession | TurnResult | None":
    """Start a run's session as one long-lived process. None when the harness cannot stay open (use run_turn);
    a TurnResult when it could not start."""
    first = turn.session is None
    session = turn.session or str(uuid.uuid4())
    cmd = adapter.live_command(turn, session, first)
    if cmd is None:
        return None
    if not adapter.available():
        return TurnResult(ok=False, session=turn.session, reason="not installed",
                          text=f"{adapter.program!r} is not installed on this gateway")
    given = {**turn.env, **(adapter.isolation(turn.workdir) if turn.isolate else {})}
    env = run_environment(given)
    if turn.run_as:
        keep = ",".join(sorted(given))
        cmd = ["sudo", "-n", "-u", turn.run_as] + ([f"--preserve-env={keep}"] if keep else []) + cmd
    try:
        return LiveSession(cmd, turn.workdir, env, session)
    except OSError as e:
        return TurnResult(ok=False, session=turn.session, reason="error", text=f"could not start the session: {e}")


def describe(cmd: list[str]) -> str:
    return " ".join(shlex.quote(c) for c in cmd)
