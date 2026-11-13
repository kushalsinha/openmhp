"""Run charters: the format, its English summary, and how the gateway enforces it on every request a
run makes with its run token.

    PYTHONPATH=. python tests/test_gateway_charter.py
"""
import copy
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")
os.environ["OPENMHP_HOME"] = tempfile.mkdtemp(prefix="openmhp-charter-")
os.environ["OPENMHP_NO_UPDATE_CHECK"] = "1"

from openmhp import charter as C                                            # noqa: E402

CHARTER = {
    "version": 1, "run": "R-2611-0042", "owner": "alice",
    "objective": "Best capacity retention after 50 cycles over salt concentration and additive",
    "autonomy": "act",
    "instruments": {"tc": "bench/thermocycler-01", "ob1": "bench/ob1-01"},
    "envelope": {
        "tc": {"actions": {"run_protocol": {"cycles": {"min": 1, "max": 40}}, "open_lid": {}, "close_lid": {}},
               "settings": {"target_temperature": {"min": 4, "max": 99}, "lid_heater": {"in": [True, False]}}},
        "ob1": {"actions": {"vent": {}}, "settings": {"pressure_setpoint_ch1": {"min": 0, "max": 300}}},
    },
    "consumables": {"buffer_ml": {"limit": 1.0, "uses": [{"instrument": "tc", "action": "run_protocol",
                                                          "param": "cycles", "scale": 0.1}]}},
    "budgets": {"experiments": 3, "count": {"instrument": "tc", "action": "run_protocol"},
                "deadline": "2099-01-01T00:00:00"},
    "standing_approvals": [{"instrument": "tc", "action": "open_lid", "uses": 2}],
    "always_ask": [{"instrument": "ob1", "action": "vent"}],
    "stop_conditions": ["retention above 95 %"],
    "cleanup": "lid closed, block at 4 C",
}


class raises:
    def __init__(self, exc):
        self.exc, self.value = exc, None
    def __enter__(self):
        return self
    def __exit__(self, et, ev, tb):
        assert et is not None and issubclass(et, self.exc), f"expected {self.exc.__name__}, got {et}: {ev}"
        self.value = ev
        return True


def test_charter_format_digest_and_summary():
    assert C.problems(CHARTER) == []
    d = C.digest(CHARTER)
    assert d.startswith("sha256:") and C.digest(copy.deepcopy(CHARTER)) == d
    assert C.digest({**CHARTER, "approved_by": "alice", "approved_at": "now"}) == d        # approval records are not content
    widened = copy.deepcopy(CHARTER)
    widened["envelope"]["tc"]["settings"]["target_temperature"]["max"] = 105
    assert C.digest(widened) != d

    bad = copy.deepcopy(CHARTER)
    del bad["objective"]
    bad["autonomy"] = "yolo"
    bad["instruments"]["x"] = "no-slash"
    bad["envelope"]["ghost"] = {"actions": {}}
    bad["envelope"]["tc"]["settings"]["target_temperature"] = {"min": 50, "max": 10}
    bad["envelope"]["tc"]["actions"]["run_protocol"]["cycles"] = {"lo": 1}
    bad["budgets"]["deadline"] = "Friday"
    bad["consumables"]["buffer_ml"]["uses"][0]["instrument"] = "ghost"
    bad["standing_approvals"].append({"instrument": "ghost"})
    found = " | ".join(C.problems(bad))
    for words in ("missing 'objective'", "autonomy", "instruments.x", "envelope.ghost", "min is above max",
                  "unknown bound 'lo'", "budgets.deadline", "consumables.buffer_ml", "standing_approvals[1]"):
        assert words in found, (words, found)

    text = C.summary(CHARTER)
    for words in ("R-2611-0042", "tc: run run_protocol (cycles 1 to 40)", "tc: set target_temperature to 4 to 99",
                  "at most 3 experiments", "buffer_ml: at most 1.0", "Approved in advance", "tc: open_lid, at most 2 times",
                  "Always asks you first", "ob1: vent", "retention above 95 %", d):
        assert words in text, (words, text)


# ---- a gateway, a lab PC with three simulated instruments, and a run whose charter covers two ----------
_LAB = []


def lab():
    """One simulated lab for every test in this file."""
    if not _LAB:
        _LAB.append(start_lab())
    return _LAB[0]


def start_lab():
    from tests.gw_lab import start_lab as start
    lab = start()
    return lab[:5] if lab else None


def test_a_run_token_reaches_only_its_charter():
    import time
    from openmhp import gateway as G
    if lab() is None:
        print("skip: openssl is needed for the gateway's certificate")
        return
    gw, drivers, rpc, get, node = lab()
    ob1 = next(d for d in drivers if "ob1" in d)
    charter = copy.deepcopy(CHARTER)
    charter["instruments"] = {"tc": "bench/thermocycler-01", "ob1": f"bench/{ob1}"}
    with raises(LookupError):
        gw.issue_run_token({**charter, "instruments": {**charter["instruments"], "x": "bench/nope"},
                            "envelope": charter["envelope"]})
    with raises(ValueError):
        gw.issue_run_token({**charter, "autonomy": "yolo"})
    tok = gw.issue_run_token(charter)
    TC = "bench/thermocycler-01"

    # only its instruments: listed, described, reached
    st, doc = get(tok, "")
    assert st == 200 and doc["devices"] == sorted([TC, f"bench/{ob1}"])
    assert get(tok, "bench/arm-01/mhp.json")[0] == 404 and rpc(tok, "bench/arm-01", "signals/read")[0] == 404
    st, ans = rpc(tok, "directory", "directory/search", {"query": "robot arm plate"})
    assert st == 200 and all(r["id"] != "bench/arm-01" for r in ans["result"]["results"])
    assert "result" in rpc(tok, TC, "signals/read")[1]

    # the run acts under the scientist's name and run ID (the thermocycler wants a lease before any write)
    assert "result" in rpc(tok, TC, "session/acquire", {"ttl": 120})[1]
    assert drivers["thermocycler-01"].lease == "alice/run-R-2611-0042"

    # settings: inside the envelope passes, beyond the charter is refused though the device would allow it
    assert "result" in rpc(tok, TC, "settings/write", {"name": "lid_heater", "value": False})[1]
    assert "result" in rpc(tok, TC, "settings/write", {"name": "target_temperature", "value": 50})[1]
    err = rpc(tok, TC, "settings/write", {"name": "target_temperature", "value": 105})[1]["error"]
    assert err["code"] == -32013 and err["data"]["charter"] == "outside" and err["data"]["bounds"] == {"min": 4, "max": 99}
    assert rpc(tok, f"bench/{ob1}", "settings/write", {"name": "pressure_setpoint_ch1", "value": 500})[1]["error"]["code"] == -32013
    assert rpc(tok, TC, "sim/fault", {})[1]["error"]["data"]["charter"] == "outside"

    # actions: bounds, then the consumable, then the experiment budget; refusals never reach the device
    def protocol(cycles, dry=False):
        p = {"name": "run_protocol", "params": {"steps": [{"temp": 50, "hold_s": 0}], "cycles": cycles}}
        if dry:
            p["dryRun"] = True
        st, ans = rpc(tok, TC, "actions/invoke", p)
        if "result" in ans and not dry:
            job = ans["result"].get("job", ans["result"]).get("id")
            end = time.time() + 30
            while time.time() < end and rpc(tok, TC, "jobs/status", {"id": job})[1]["result"]["job"]["state"] not in ("done", "failed"):
                time.sleep(0.05)
        return ans
    assert protocol(41)["error"]["data"]["param"] == "cycles"
    assert "result" in protocol(10, dry=True)                              # a dry run counts for nothing
    assert "result" in protocol(5)                                         # 0.5 of 1.0 mL
    e = protocol(6)["error"]                                               # 0.6 more would be 1.1
    assert e["data"]["charter"] == "consumable" and abs(e["data"]["used"] - 0.5) < 1e-9
    assert "result" in protocol(4) and "result" in protocol(1)            # 0.9, then 1.0: exactly the limit
    assert protocol(1)["error"]["data"]["charter"] == "budget"             # three experiments used
    usage = gw.gate_for(f"Bearer {tok}").usage
    assert usage["experiments"] == 3 and abs(usage["consumables"]["buffer_ml"] - 1.0) < 1e-9

    # approvals: never taken from the run; a standing approval covers open_lid twice, then the scientist is asked
    def lid(action, approved=None):
        p = {"name": action, "params": {}}
        if approved is not None:
            p["approved"] = approved
        return rpc(tok, TC, "actions/invoke", p)[1]
    def done(ans):
        assert "result" in ans, ans
        job = ans["result"].get("job", ans["result"]).get("id")
        end = time.time() + 30
        while job and time.time() < end and rpc(tok, TC, "jobs/status", {"id": job})[1]["result"]["job"]["state"] not in ("done", "failed"):
            time.sleep(0.05)
    for _ in range(2):
        done(lid("open_lid"))
        done(lid("close_lid"))
    e = lid("open_lid", approved=True)["error"]                            # run's own "approved" is stripped
    assert e["code"] == -32012 and e["data"]["charter"] == "ask_scientist"
    e = rpc(tok, f"bench/{ob1}", "actions/invoke", {"name": "vent", "params": {}})[1]["error"]
    assert e["code"] == -32012 and e["data"]["charter"] == "ask_scientist"            # always_ask: never sent
    assert rpc(tok, TC, "safety/reset", {})[1]["error"]["data"]["charter"] == "ask_scientist"

    rpc(tok, TC, "session/release", {})

    # usage outlives a gateway restart; ending the run ends the token
    gw2 = G.Gateway(G.load())
    assert gw2.gate_for(f"Bearer {tok}").usage["experiments"] == 3
    gw.end_run("R-2611-0042")
    assert get(tok, "")[0] == 401


def test_runs_get_all_their_instruments_or_wait():
    import time
    if lab() is None:
        print("skip: openssl is needed for the gateway's certificate")
        return
    gw, drivers, rpc, get, node = lab()
    ob1 = next(d for d in drivers if "ob1" in d)
    TC, OB1, ARM = "bench/thermocycler-01", f"bench/{ob1}", "bench/arm-01"
    lease = lambda dev: drivers[dev]._lease_holder()

    def charter(run, owner, instruments):
        return {"version": 1, "run": run, "owner": owner, "objective": "allocation", "instruments": instruments,
                "envelope": {a: {"actions": {}, "settings": {}} for a in instruments}}
    a = charter("R-2611-0050", "alice", {"tc": TC, "ob1": OB1})
    b = charter("R-2611-0051", "bob", {"tc": TC})
    c = charter("R-2611-0052", "carol", {"arm": ARM, "ob1": OB1})
    for ch in (a, b, c):
        gw.issue_run_token(ch)

    assert gw.allocate("R-2611-0050")["state"] == "allocated"
    assert lease("thermocycler-01") == lease(ob1) == "alice/run-R-2611-0050"
    got = gw.allocate("R-2611-0051")
    assert got["state"] == "queued" and got["waiting_for"] == [TC]
    got = gw.allocate("R-2611-0052")                       # the arm is free but ob1 is not: it takes nothing
    assert got["state"] == "queued" and got["waiting_for"] == [OB1] and lease("arm-01") is None

    time.sleep(12)                                         # past the thermocycler's 10 s watchdog
    assert lease("thermocycler-01") == "alice/run-R-2611-0050" and drivers["thermocycler-01"].state != "estop"

    gw.end_run("R-2611-0050")                              # both waiting runs get their instruments now
    end = time.time() + 15
    while time.time() < end and not ("R-2611-0051" in gw.allocated and "R-2611-0052" in gw.allocated):
        time.sleep(0.1)
    assert lease("thermocycler-01") == "bob/run-R-2611-0051"
    assert lease("arm-01") == lease(ob1) == "carol/run-R-2611-0052"
    gw.end_run("R-2611-0051")
    gw.end_run("R-2611-0052")
    assert lease("thermocycler-01") is None and lease("arm-01") is None and lease(ob1) is None
    assert gw.waiting == [] and gw.allocated == {}


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok ", name)
