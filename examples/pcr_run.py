"""Third control surface: a code file that chains driver commands across devices.

An agent writes (or is handed) a script like this for anything that must run
faster or longer than its own reasoning loop. The devices then carry out the
sequence on their own; the agent only reads the result.

    python examples/pcr_run.py
"""
from openmhp.client import Lab, RemoteError

lab = Lab({
    "arm":    "local:openmhp.devices.sim_arm:SimArm",
    "thermo": "local:openmhp.devices.sim_thermocycler:SimThermocycler",
})
arm, thermo = lab["arm"], lab["thermo"]

PCR = {"steps": [{"temp": 95, "hold_s": 30}, {"temp": 58, "hold_s": 30}, {"temp": 72, "hold_s": 45}],
       "cycles": 3}

with arm, thermo:                                   # exclusive leases on both devices
    arm.write("speed", 30)                          # descriptor notes: <=30% near open plates
    arm.write("gripper_force", 20)                  # <25 N so plates aren't deformed
    arm.wait(arm.invoke("home"))
    arm.wait(arm.invoke("pick_plate", location="deck_A1"))
    arm.wait(arm.invoke("place_plate", location="thermocycler"))

    thermo.write("lid_heater", True)
    job = thermo.invoke("run_protocol", **PCR)      # long-running: device does the work
    while (j := thermo.status(job))["state"] == "running":
        print(f"  cycle {thermo.read('cycle')}  block {thermo.read('block_temperature'):6.1f} degC  "
              f"{j['progress']*100:5.1f}%")
        import time; time.sleep(0.15)
    print("thermocycler result:", j["result"])

    thermo.write("target_temperature", 4)           # hold at 4 degC
    try:
        thermo.write("target_temperature", -20)     # refused by the driver, never reaches hardware
    except RemoteError as e:
        print("guarded write refused:", e.message)

    arm.wait(arm.invoke("pick_plate", location="thermocycler"))
    arm.wait(arm.invoke("place_plate", location="deck_A2"))

print("done. plate is at deck_A2, block at", thermo.read("block_temperature"), "degC")
