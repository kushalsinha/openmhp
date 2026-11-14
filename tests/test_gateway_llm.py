"""How a gateway's runs sign in to their model: the probe, choosing a method, credentials fetched for each turn,
the free test, isolation from the operator's own sign-in, and a failed sign-in reaching the scientist.
Fake `aws`, `claude` and helper commands stand in; nothing calls a model.

    PYTHONPATH=. python tests/test_gateway_llm.py
"""
import json
import os
import stat
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, ".")
os.environ["OPENMHP_HOME"] = tempfile.mkdtemp(prefix="openmhp-llm-")
os.environ["OPENMHP_LAB_ROOT"] = str(Path(os.environ["OPENMHP_HOME"]) / "lab")
os.environ["OPENMHP_NO_UPDATE_CHECK"] = "1"

from openmhp import llm_access as L                                          # noqa: E402

FAKE_AWS = """#!/bin/sh
# configure export-credentials --profile P --format process
if [ "$4" = "lab-sso" ]; then
  echo '{"Version": 1, "AccessKeyId": "ASIAFAKE", "SecretAccessKey": "fake-secret", "SessionToken": "fake-session", "Expiration": "2099-01-01T00:00:00Z"}'
else
  echo "Error loading SSO Token: Token for lab-old does not exist or is expired" >&2; exit 255
fi
"""
FAKE_CLAUDE = """#!/bin/sh
# auth status --json: answers from the environment, as Claude Code does; records what it was given
env > "$CLAUDE_CONFIG_DIR/../env-seen.txt" 2>/dev/null || env > /dev/null
if [ -n "$CLAUDE_CODE_USE_BEDROCK" ]; then echo '{"loggedIn": true, "authMethod": "third_party", "apiProvider": "bedrock"}'
elif [ -n "$ANTHROPIC_API_KEY" ]; then echo '{"loggedIn": true, "authMethod": "api_key", "apiProvider": "firstParty"}'
else echo '{"loggedIn": false, "authMethod": "none", "apiProvider": "firstParty"}'; fi
"""


def tool(folder: Path, name: str, text: str) -> Path:
    p = folder / name
    p.write_text(text)
    p.chmod(p.stat().st_mode | stat.S_IXUSR)
    return p


def test_the_probe_names_what_is_there_and_never_a_secret():
    home = Path(tempfile.mkdtemp(prefix="home-"))
    (home / ".aws").mkdir()
    (home / ".aws" / "config").write_text("[profile lab-sso]\nsso_session = corp\nregion = eu-west-1\n\n[default]\nregion = us-east-1\n")
    (home / ".config" / "gcloud").mkdir(parents=True)
    (home / ".config" / "gcloud" / "application_default_credentials.json").write_text("{}")
    (home / ".claude").mkdir()
    (home / ".claude" / "settings.json").write_text(json.dumps({"apiKeyHelper": "/opt/corp/llm-token"}))
    env = {"ANTHROPIC_API_KEY": "sk-ant-very-secret", "ANTHROPIC_BASE_URL": "https://llm.corp.example"}
    rows = {r["method"]: r for r in L.probe(home, env, which=lambda c: f"/usr/bin/{c}")}
    assert set(rows) == set(L.METHODS)
    assert rows["api-key"]["found"] and rows["llm-gateway"]["found"] and "llm.corp.example" in rows["llm-gateway"]["use"]
    assert rows["bedrock"]["found"] and "lab-sso (SSO)" in rows["bedrock"]["what"]
    assert "profile=lab-sso region=eu-west-1" in rows["bedrock"]["use"]                      # the SSO profile first
    assert rows["vertex"]["found"] and rows["helper"]["found"] and "/opt/corp/llm-token" in rows["helper"]["use"]
    assert not rows["claude-token"]["found"] and "setup-token" in rows["claude-token"]["what"]
    assert not rows["foundry"]["found"]
    assert "very-secret" not in json.dumps(rows)
    plain = {r["method"]: r for r in L.probe(home, {"ANTHROPIC_BASE_URL": "https://api.anthropic.com"}, which=lambda c: None)}
    assert not plain["llm-gateway"]["found"]                                     # Anthropic's own address
    empty = {r["method"]: r for r in L.probe(Path(tempfile.mkdtemp()), {}, which=lambda c: None)}
    assert not any(r["found"] for r in empty.values())


def test_choosing_fetching_and_testing_a_sign_in():
    if os.name == "nt":
        print("skip: the stand-in aws, claude and helper commands are shell scripts")
        return
    gw = Path(tempfile.mkdtemp(prefix="gw-"))
    bindir = Path(tempfile.mkdtemp(prefix="bin-"))
    tool(bindir, "aws", FAKE_AWS)
    tool(bindir, "claude", FAKE_CLAUDE)
    old_path = os.environ["PATH"]
    os.environ["PATH"] = f"{bindir}{os.pathsep}{old_path}"
    try:
        # the default: the gateway's own Claude Code as set up; a run gets its sign-in variables and nothing else
        assert L.chosen(gw) is None and not L.configured(gw)
        os.environ.update(ANTHROPIC_API_KEY="sk-ant-gateway", SOME_OTHER_SECRET="x")
        try:
            got = L.turn_env(gw)
            assert got["ANTHROPIC_API_KEY"] == "sk-ant-gateway" and "SOME_OTHER_SECRET" not in got
            assert set(got) <= set(L.INSTALLED_VARS)
        finally:
            os.environ.pop("ANTHROPIC_API_KEY"), os.environ.pop("SOME_OTHER_SECRET")
        steps = L.test(gw)                                                      # the fake claude: logged out here
        real = L.installed_status
        L.installed_status = lambda: {"loggedIn": False, "why": "not signed in"}
        try:
            ok, why = L.ready(gw)
            assert not ok and "API key" in why and "mhp gateway llm" in why
        finally:
            L.installed_status = real

        # an API key: the secret lives only in llm.env (this account only); llm.json holds the choice
        L.choose(gw, "api-key", {}, "sk-ant-test-key\n")
        assert (gw / "llm.env").read_text() == "ANTHROPIC_API_KEY=sk-ant-test-key\n"
        assert oct((gw / "llm.env").stat().st_mode & 0o777) == "0o600" and "sk-ant" not in (gw / "llm.json").read_text()
        assert L.turn_env(gw) == {"ANTHROPIC_API_KEY": "sk-ant-test-key"}

        # Bedrock with an SSO profile: the old key is gone, short-lived credentials are fetched for every turn
        L.choose(gw, "bedrock", {"profile": "lab-sso", "region": "eu-west-1"})
        assert (gw / "llm.env").read_text() == ""
        env = L.turn_env(gw)
        assert env["CLAUDE_CODE_USE_BEDROCK"] == "1" and env["AWS_REGION"] == "eu-west-1"
        assert env["AWS_ACCESS_KEY_ID"] == "ASIAFAKE" and env["AWS_SESSION_TOKEN"] == "fake-session"
        assert "ANTHROPIC_API_KEY" not in env
        steps = L.test(gw)
        assert all(ok for ok, _ in steps) and "bedrock" in steps[-1][1], steps
        assert "fake-secret" not in json.dumps(steps)                          # values are never shown

        # an expired SSO session: the operator is told what to run
        L.choose(gw, "bedrock", {"profile": "lab-old", "region": "eu-west-1"})
        try:
            L.turn_env(gw)
            raise AssertionError("an expired SSO session should refuse")
        except L.LLMAccessError as e:
            assert "lab-old" in str(e) and "expired" in str(e)
        assert not L.test(gw)[-1][0]

        # a helper the company provides: run before every turn, its output is the token
        helper = tool(bindir, "corp-token", "#!/bin/sh\necho tok-$(date +%s%N)\n")
        L.choose(gw, "helper", {"command": str(helper), "var": "ANTHROPIC_AUTH_TOKEN", "url": "https://llm.corp.example"})
        a, b = L.turn_env(gw), (time.sleep(0.01), L.turn_env(gw))[1]
        assert a["ANTHROPIC_AUTH_TOKEN"].startswith("tok-") and a["ANTHROPIC_AUTH_TOKEN"] != b["ANTHROPIC_AUTH_TOKEN"]
        assert a["ANTHROPIC_BASE_URL"] == "https://llm.corp.example"
        tool(bindir, "corp-token", "#!/bin/sh\necho 'not signed in' >&2; exit 3\n")
        try:
            L.turn_env(gw)
            raise AssertionError("a failing helper should refuse")
        except L.LLMAccessError as e:
            assert "not signed in" in str(e)

        # bad choices are refused in words
        for method, opts, secret, words in (("nope", {}, None, "no sign-in method"), ("bedrock", {"profile": "x"}, None, "region="),
                                            ("api-key", {}, None, "stdin"), ("llm-gateway", {"url": "http://x"}, "t", "https://"),
                                            ("vertex", {"project": "p", "region": "r", "credentials": "/nope.json"}, None, "gcloud")):
            try:
                L.choose(gw, method, opts, secret)
                raise AssertionError(method)
            except ValueError as e:
                assert words in str(e), (method, str(e))

        # back to the default
        assert L.choose(gw, "installed", {}) is None and not L.configured(gw) and not (gw / "llm.env").exists()

        # a gateway set up before this existed (`mhp gateway llm-key` only) still works
        old = Path(tempfile.mkdtemp(prefix="gw-old-"))
        (old / "llm.env").write_text("ANTHROPIC_API_KEY=sk-ant-old\n")
        assert L.chosen(old)["method"] == "static" and L.turn_env(old) == {"ANTHROPIC_API_KEY": "sk-ant-old"}
    finally:
        os.environ["PATH"] = old_path


def test_a_run_never_sees_the_operators_sign_in():
    from openmhp import harness as H
    os.environ.update(AWS_PROFILE="operator", AWS_ACCESS_KEY_ID="AKIAOPERATOR", GOOGLE_APPLICATION_CREDENTIALS="/home/op/adc.json",
                      CLAUDE_CONFIG_DIR="/home/op/.claude")
    try:
        env = H.run_environment({"ANTHROPIC_API_KEY": "sk-run"})
        for k in ("AWS_PROFILE", "AWS_ACCESS_KEY_ID", "GOOGLE_APPLICATION_CREDENTIALS", "CLAUDE_CONFIG_DIR"):
            assert k not in env, k
    finally:
        for k in ("AWS_PROFILE", "AWS_ACCESS_KEY_ID", "GOOGLE_APPLICATION_CREDENTIALS", "CLAUDE_CONFIG_DIR"):
            os.environ.pop(k)
    work = Path(tempfile.mkdtemp(prefix="work-"))
    iso = H.ClaudeCode().isolation(work)
    assert iso == {"CLAUDE_CONFIG_DIR": str(work / ".claude-home")} and (work / ".claude-home").is_dir()
    assert H.Command(["x"]).isolation(work) == {}

    # the run's harness is started with its own configuration folder, unless the gateway is told to share its login
    seen = work / "seen.py"
    seen.write_text("import json, os, sys\nargs = sys.argv[1:]\n"
                    "print(json.dumps({'ok': True, 'session': args[args.index('--session') + 1], "
                    "'text': os.environ.get('CLAUDE_CONFIG_DIR', '-'), 'cost_usd': 0, 'tokens': 0}))\n")

    class Isolated(H.Command):
        def isolation(self, workdir):
            return {"CLAUDE_CONFIG_DIR": str(Path(workdir) / ".claude-home")}
    ad = Isolated([sys.executable, str(seen)])
    assert H.run_turn(ad, H.Turn(prompt="x", workdir=work)).text == str(work / ".claude-home")
    assert H.run_turn(ad, H.Turn(prompt="x", workdir=work, isolate=False)).text == "-"


def test_a_failed_sign_in_reaches_the_scientist():
    if os.name == "nt":
        print("skip: the stand-in aws, claude and helper commands are shell scripts")
        return
    import io
    from openmhp import gateway as G, gw_shell as GW, harness as H, scientists as S, supervisor as SV
    from tests.gw_lab import start_lab
    lab = start_lab()
    if lab is None:
        print("skip: openssl is needed for the gateway's certificate")
        return
    gw, drivers, rpc, get, node, base, ctx = lab
    bindir = Path(tempfile.mkdtemp(prefix="bin-"))
    helper = tool(bindir, "corp-token", "#!/bin/sh\necho 'SSO session expired' >&2; exit 1\n")
    L.choose(G.GW_DIR, "helper", {"command": str(helper)})
    agent = bindir / "agent.py"
    agent.write_text("import json, sys\nargs = sys.argv[1:]\nprint(json.dumps({'ok': True, 'session': "
                     "args[args.index('--session') + 1], 'text': 'ran', 'cost_usd': 0, 'tokens': 0}))\n")
    sup = SV.Supervisor(gw, lab_root=S.lab_root(), runs_dir=G.RUNS_DIR,
                        adapters={"stand-in": H.Command([sys.executable, str(agent)])}, poll_s=0.1)
    sup.start()
    S.create("bea")
    try:
        out = io.StringIO()
        GW.Shell("bea", out=out, env={"SSH_ORIGINAL_COMMAND": "mhp-gw open"}).run()
        rid = json.loads(out.getvalue())["run"]
        out = io.StringIO()
        GW.Shell("bea", out=out, env={"SSH_ORIGINAL_COMMAND": f"mhp-gw request {rid} --harness stand-in"},
                 stdin=io.StringIO("Keep the block warm."), wait_s=30).run()
        end = time.time() + 30
        while time.time() < end and not sup.record(rid).doc.get("open_questions"):
            time.sleep(0.1)
        q = next(iter(sup.record(rid).doc["open_questions"].values()))["question"]
        assert "could not sign its agent in" in q and "SSO session expired" in q and "mhp gateway llm test" in q, q
        kinds = [e["kind"] for e in sup.record(rid).events()]
        assert "signin_failed" in kinds and "turn" not in kinds                  # no turn ran without a sign-in
    finally:
        sup.stop_event.set()
        node.close()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok ", name)
