# recipe: setpoint-sweep
# needs: any device with a numeric setting and a signal to measure
# asks: which device, setting and signal; the list of setpoints; settle time
# summary: Step a setting through a list of values, wait for each to settle, record the measured signal at each, save a CSV, report the table, and restore the setting even if a step fails. Calibration and characterisation.
PARAMS = {"device": None, "setting": "target_temperature", "signal": "block_temperature",
          "values": [30, 40, 50, 60], "settle_s": 30, "samples": 3, "restore": 22}

import time, csv, os, statistics
dev = lab[PARAMS["device"]] if PARAMS["device"] else lab[lab.find("sweep calibrate", state="idle")[0]["id"]]
rows = []
with dev:
    try:
        for v in PARAMS["values"]:
            dev.write(PARAMS["setting"], v)
            time.sleep(PARAMS["settle_s"])
            xs = [dev.read(PARAMS["signal"]) for _ in range(PARAMS["samples"])]
            rows.append((v, statistics.mean(xs), statistics.pstdev(xs) if len(xs) > 1 else 0.0))
    finally:
        try:
            dev.write(PARAMS["setting"], PARAMS["restore"])
        except Exception as e:
            print(f"CLEANUP FAILED: could not restore {PARAMS['setting']} to {PARAMS['restore']}: {e}")
with open(os.path.join(run_dir, "sweep.csv"), "w", newline="") as f:
    w = csv.writer(f); w.writerow(["setpoint", "measured_mean", "measured_sd"]); w.writerows(rows)
print("setpoint  measured  sd")
for v, m, s in rows:
    print(f"{v:>8}  {m:8.2f}  {s:.2f}")
