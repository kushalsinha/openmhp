"""The documentation says what the code does. Each state machine is declared once in openmhp/states.py; the
specification, the skills and the words people read are checked against those declarations, so a state added,
renamed or rewired in code fails here until every place that describes it says the same.

    PYTHONPATH=. python tests/test_state_docs.py
"""
import re
import ssl
import sys
import urllib.error
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from openmhp import gw_words as W, states as ST                                   # noqa: E402

SPEC = (REPO / "SPEC.md").read_text(encoding="utf-8")


def section(text: str, start: str, end: str) -> str:
    return text[text.index(start):text.index(end, text.index(start))]


def table_rows(text: str) -> list[list[str]]:
    """The body rows of the first markdown table in `text`, as cells."""
    rows, seen = [], False
    for line in text.splitlines():
        if not line.startswith("|"):
            if seen:
                break
            continue
        seen = True
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if set("".join(cells)) <= set("-: "):
            continue
        rows.append(cells)
    return rows[1:]                                                       # without the header


def ticked(cell: str) -> list[str]:
    return re.findall(r"`([^`]+)`", cell)


def test_the_specification_describes_the_run_machine_as_declared():
    rows = table_rows(section(SPEC, "### 9.3 Runs on a gateway", "## 10."))
    seen = set()
    for state_cell, waiting, moves in rows:
        moves_to = {m for m in ticked(moves) if m in ST.RUN_TRANSITIONS}
        for state in ticked(state_cell):
            seen.add(state)
            assert ST.RUN_WAITING_ON[state] == waiting, (state, waiting)
            assert moves_to == ST.RUN_TRANSITIONS[state], (state, moves_to, ST.RUN_TRANSITIONS[state])
            assert moves.strip() != "ended" or state in ST.RUN_ENDED, state
    assert seen == set(ST.RUN_STATES), set(ST.RUN_STATES) ^ seen


def test_the_gateway_skill_shows_every_run_state_and_who_it_waits_on():
    skill = (REPO / "openmhp" / "skills" / "openmhp-lab-gateway" / "SKILL.md").read_text(encoding="utf-8")
    start = skill.index("| State | Waiting on |")
    seen = set()
    for state_cell, waiting, what in table_rows(skill[start:]):
        for state in ticked(state_cell):
            seen.add(state)
            assert ST.RUN_WAITING_ON[state] == waiting, (state, waiting)
            verbs = {c.split()[0] for c, _ in ST.RUN_NEXT[state] if not c.startswith("rsync")}
            # each verb the gateway offers in that state is one the skill tells the scientist about
            assert all(f"`{v}`" in what for v in verbs), (state, verbs, what)
    assert seen == set(ST.RUN_STATES), set(ST.RUN_STATES) ^ seen
    assert set(W.STATES) == set(W.SHORT) == set(ST.RUN_STATES)            # the words a scientist reads


def test_the_specification_lists_every_status_part_and_state():
    rows = table_rows(section(SPEC, "### 10.2 Command line", "### 10.3"))
    parts = {}
    for part, machine, states in rows:
        name = ticked(part)[0]
        parts[name] = set(ticked(states))
    assert set(parts) == set(ST.STATUS_PARTS), set(parts) ^ set(ST.STATUS_PARTS)
    for name, states in ST.STATUS_PARTS.items():
        assert states <= parts[name], (name, states - parts[name])
    assert set(ST.SKILL_STATES) <= parts["agent skills"], set(ST.SKILL_STATES) - parts["agent skills"]
    assert set(ST.LINK_STATES) == parts["gateway link"]


def test_the_code_reports_only_declared_setup_states():
    status = (REPO / "openmhp" / "status.py").read_text(encoding="utf-8")
    literal = re.findall(r'part\("([^"]+)",\s*"([^"]+)"', status)
    assert literal, "status.py no longer calls part(name, state) with literals: update this check"
    for name, state in literal:
        assert state in ST.STATUS_PARTS[name], (name, state)
    for name, a, b in re.findall(r'part\("([^"]+)",\s*"([^"]+)" if [^"]+ else "([^"]+)"', status):
        assert {a, b} <= ST.STATUS_PARTS[name], (name, a, b)
    try:
        ST.check_status_part("gateway link", "refused"); assert False
    except ValueError as e:
        assert "STATUS_PARTS" in str(e)
    # the relay's words for a failed link are declared link states
    from openmhp import relay as R
    for err in (urllib.error.HTTPError("https://gw/relay", 401, "Unauthorized", {}, None),
                urllib.error.URLError(ssl.SSLCertVerificationError("certificate verify failed")),
                ConnectionRefusedError(61, "refused")):
        assert R.link_problem(err)[0] in ST.LINK_STATES, err
    skills = (REPO / "openmhp" / "skills_install.py").read_text(encoding="utf-8")
    assert set(re.findall(r'"state": "([a-z_]+)"', skills)) <= set(ST.SKILL_STATES)


def test_the_packed_guide_carries_this_specification():
    assert (REPO / "openmhp" / "guide" / "spec.md").read_text(encoding="utf-8") == SPEC


if __name__ == "__main__":
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn(); print("ok  ", name, flush=True)
            except Exception as e:                               # noqa: BLE001
                failed += 1
                import traceback; traceback.print_exc()
                print("FAIL", name, e, flush=True)
    print(f"{failed} failed")
    sys.exit(1 if failed else 0)
