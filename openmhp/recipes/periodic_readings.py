# recipe: periodic-readings
# needs: any device with readable signals
# asks: which device and signals; how often; for how long
# summary: Log chosen signals every N seconds for a duration into a CSV in the run folder. Run in the background for overnight monitoring.
PARAMS = {"device": None, "signals": ["block_temperature"], "every_s": 60, "hours": 8, "alert": {}}

import time, csv, os
dev = lab[PARAMS["device"]] if PARAMS["device"] else lab[lab.find(" ".join(PARAMS["signals"]))[0]["id"]]
path = os.path.join(run_dir, "readings.csv")
t0, n, alerts = time.time(), 0, []
with open(path, "w", newline="") as f:
    w = csv.writer(f); w.writerow(["t_s", *PARAMS["signals"]])
    while time.time() - t0 < PARAMS["hours"] * 3600:
        vals = dev.call("signals/read", {"names": PARAMS["signals"]})["values"]
        w.writerow([round(time.time() - t0, 1), *[vals[s] for s in PARAMS["signals"]]]); f.flush(); n += 1
        for s, (lo, hi) in PARAMS["alert"].items():
            if not (lo <= vals[s] <= hi):
                alerts.append((round(time.time() - t0), s, vals[s])); print(f"ALERT t={round(time.time()-t0)}s {s}={vals[s]} outside {lo}..{hi}")
        time.sleep(PARAMS["every_s"])
print(f"{n} rows in readings.csv; {len(alerts)} alert(s)")
