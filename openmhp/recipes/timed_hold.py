# recipe: timed-hold
# needs: any device with a temperature setpoint
# asks: which device; the setpoint; how long to hold; how often to log
# summary: Set a temperature, wait until it is reached, hold for a duration while logging readings to the run folder, then return to a safe setpoint, also when a step fails.
PARAMS = {"device": None, "setting": "target_temperature", "signal": "block_temperature", "setpoint": 37,
          "hold_minutes": 60, "log_every_s": 60, "tolerance": 0.5, "safe_setpoint": 22, "reach_timeout_s": 1800}

import time, csv, os
dev = lab[PARAMS["device"]] if PARAMS["device"] else lab[lab.find("temperature hold", state="idle")[0]["id"]]
path = os.path.join(run_dir, "readings.csv")
with dev, open(path, "w", newline="") as f:
    w = csv.writer(f); w.writerow(["t_s", PARAMS["signal"]])
    t0 = time.time()
    try:
        dev.write(PARAMS["setting"], PARAMS["setpoint"])
        dev.wait_until(PARAMS["signal"], lambda v: abs(v - PARAMS["setpoint"]) <= PARAMS["tolerance"],
                       timeout=PARAMS["reach_timeout_s"], poll=1, label=f"within {PARAMS['tolerance']} of {PARAMS['setpoint']}")
        reached = time.time()
        while time.time() - reached < PARAMS["hold_minutes"] * 60:
            w.writerow([round(time.time() - t0, 1), dev.read(PARAMS["signal"])]); f.flush()
            time.sleep(PARAMS["log_every_s"])
    finally:
        # restore the safe setpoint on success and on failure; report if that is impossible
        try:
            dev.write(PARAMS["setting"], PARAMS["safe_setpoint"])
        except Exception as e:
            print(f"CLEANUP FAILED: could not restore {PARAMS['setting']} to {PARAMS['safe_setpoint']}: {e}")
print(f"held {PARAMS['setpoint']} for {PARAMS['hold_minutes']} min; readings in readings.csv; now {dev.read(PARAMS['signal'])}")
