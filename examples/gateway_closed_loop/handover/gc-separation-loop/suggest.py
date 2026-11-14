"""A small sequential optimiser for a GC separation: two knobs, carrier flow and oven ramp.

Lower flow and slower ramps separate peaks better but take longer. While nothing is resolved it moves
toward better separation; once something is, it moves back toward faster runs as long as separation
holds, and stops when neither direction improves. Deterministic, standard library only.
"""
import json
import sys

TARGET = 1.5
FLOW = (0.5, 5.0)
RAMP = (2.0, 40.0)
START = {"carrier_flow_ml_min": 1.5, "ramp_c_min": 20.0}


def clamp(v, lo, hi):
    return round(min(hi, max(lo, v)), 3)


def key(p):
    return (round(p["carrier_flow_ml_min"], 3), round(p["ramp_c_min"], 3))


def suggest(history):
    if not history:
        return {**START, "why": "first injection at the instrument's usual conditions"}
    tried = {key(h) for h in history}
    good = [h for h in history if (h.get("resolution_min") or 0) >= TARGET]
    if not good:
        last = max(history, key=lambda h: h.get("resolution_min") or 0)
        for f, r, why in ((0.75, 1.0, "slower carrier flow"), (1.0, 0.6, "slower ramp"), (0.75, 0.6, "both slower")):
            nxt = {"carrier_flow_ml_min": clamp(last["carrier_flow_ml_min"] * f, *FLOW),
                   "ramp_c_min": clamp(last["ramp_c_min"] * r, *RAMP)}
            if key(nxt) not in tried:
                return {**nxt, "why": f"not resolved yet (best Rs {last.get('resolution_min')}): {why}"}
        return {"done": True, "best": last, "why": "no untried slower condition is left within the bounds"}
    best = min(good, key=lambda h: h["run_time_s"])
    for f, r, why in ((1.2, 1.0, "faster flow"), (1.0, 1.4, "faster ramp"), (1.1, 1.2, "both a little faster")):
        nxt = {"carrier_flow_ml_min": clamp(best["carrier_flow_ml_min"] * f, *FLOW),
               "ramp_c_min": clamp(best["ramp_c_min"] * r, *RAMP)}
        if key(nxt) not in tried:
            return {**nxt, "why": f"resolved at {best['run_time_s']} s: try a {why} to shorten the run"}
    return {"done": True, "best": best, "why": "every faster neighbour of the best condition is tried"}


if __name__ == "__main__":
    hist = json.load(open(sys.argv[1])) if len(sys.argv) > 1 else []
    print(json.dumps(suggest(hist)))
