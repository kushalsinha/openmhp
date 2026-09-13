# recipe: optimize-separation
# needs: any instrument with a method-driven action whose result reports resolution between peaks (gc, hplc)
# asks: the compound and the project (the device picks the method; if several, the person chooses); the target resolution; which parameter to adapt and its step
# summary: Closed loop on a chromatograph. Ask the instrument for the project's method for a compound, run it, read the result it pushes back, adapt one parameter within the instrument's limits until neighbouring peaks are resolved, then save what worked as the method's next version.
PARAMS = {"device": None, "compound": "ethanol", "project": "_shared", "method": None,
          "target_resolution": 1.5, "adapt": "carrier_flow_ml_min", "step": -0.25, "floor": 0.5, "ceiling": 5.0,
          "max_runs": 6, "save_as_new_version": True}

import json, os
dev = lab[PARAMS["device"]] if PARAMS["device"] else lab[lab.find("chromatograph separation", state="idle")[0]["id"]]

# 1. the method: named, or the one the device files for this compound in this project (SPEC 4.5 M8)
if PARAMS["method"]:
    m = dev.method(PARAMS["method"], PARAMS["project"])
else:
    pick = dev.method_find(PARAMS["compound"], PARAMS["project"])
    if pick["choice"] != "one":
        raise SystemExit(pick["ask"])            # several or none: a person decides before anything runs
    m = dev.method(pick["method"]["name"], pick["method"]["project"])
print(f"method {m['project']}/{m['name']} v{m['version']} ({m['hash']}) for {', '.join(m['compounds'])}")

# 2. run, look at what came back, adapt within the limits, run again
value = float(m["params"].get(PARAMS["adapt"], dev.read("carrier_flow")))
history = []
with dev:
    for i in range(1, PARAMS["max_runs"] + 1):
        job = dev.run_method(m["name"], {PARAMS["adapt"]: round(value, 3)}, project=m["project"],
                             run_project=PARAMS["project"], compound=PARAMS["compound"])
        r = job["result"]
        with open(os.path.join(run_dir, f"run{i}_result.json"), "w") as f:
            json.dump(r, f)
        rs = r.get("resolution_min")
        history.append({"run": i, "job": job["id"], "method": job.get("method"), PARAMS["adapt"]: value,
                        "resolution_min": rs, "run_time_s": r.get("run_time_s")})
        print(f"run {i}: {PARAMS['adapt']}={value:g}  resolution_min={rs}  unresolved={r.get('unresolved')}  {r.get('run_time_s')} s")
        if rs is not None and rs >= PARAMS["target_resolution"]:
            print(f"target {PARAMS['target_resolution']} reached at {PARAMS['adapt']}={value:g}")
            break
        nxt = value + PARAMS["step"]
        if not PARAMS["floor"] <= nxt <= PARAMS["ceiling"]:
            print(f"cannot adapt further: {PARAMS['adapt']}={nxt:g} is outside {PARAMS['floor']}..{PARAMS['ceiling']}")
            break
        value = nxt
    else:
        print(f"stopped after {PARAMS['max_runs']} runs without reaching {PARAMS['target_resolution']}")

with open(os.path.join(run_dir, "history.json"), "w") as f:
    json.dump(history, f, indent=1)

# 3. keep what worked, as the next version of the same method (the device validates and versions it)
final = history[-1]
if PARAMS["save_as_new_version"] and final["resolution_min"] is not None and final["resolution_min"] >= PARAMS["target_resolution"]:
    saved = dev.method_save({"name": m["name"], "project": m["project"], "action": m["action"], "compounds": m["compounds"],
                             "params": {**m["params"], PARAMS["adapt"]: final[PARAMS["adapt"]]},
                             "derived_from": {"project": m["project"], "name": m["name"], "version": m["version"]},
                             "source": {"kind": "agent", "ref": f"optimize-separation run {run_id}"}},
                            note=f"{PARAMS['adapt']} tuned to {final[PARAMS['adapt']]:g} (resolution {final['resolution_min']})")
    print(f"saved {saved['saved']['project']}/{saved['saved']['name']} v{saved['saved']['version']} ({saved['saved']['hash']})")
