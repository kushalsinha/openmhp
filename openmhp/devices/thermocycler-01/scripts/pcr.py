# mhp_run script: full PCR on thermocycler-01 with lid pre-heat and 4 degC hold.
# Edit STEPS/CYCLES, then pass this file's text to mhp_run. Prints one summary line.
STEPS = [{"temp": 95, "hold_s": 30}, {"temp": 58, "hold_s": 30}, {"temp": 72, "hold_s": 45}]
CYCLES = 30

tc = lab["thermocycler-01"]
with tc:
    assert tc.read("lid_closed"), "close the lid first"
    tc.write("lid_heater", True)
    job = tc.wait(tc.invoke("run_protocol", steps=STEPS, cycles=CYCLES))
    tc.write("target_temperature", 4)
print("pcr done:", job["result"], "holding at", tc.read("block_temperature"), "degC")
