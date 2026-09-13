"""Third control surface: a code file that chains driver commands across devices.

An agent writes (or is handed) a script like this for anything that must run
faster or longer than its own reasoning loop. The devices then carry out the
sequence on their own; the agent only reads the result.

This file is trusted host code talking to the SDK directly, so it passes
approved=True for the two lid openings, standing in for the person who would
confirm them. Through the MCP bridge a person is asked instead, and a model
cannot approve on their behalf.

    python examples/pcr_run.py
"""
import time

from openmhp.client import Lab, RemoteError

lab = Lab({
    "arm":    "local:openmhp.devices.sim_arm:SimArm",
    "thermo": "local:openmhp.devices.sim_thermocycler:SimThermocycler",
})
arm, thermo = lab["arm"], lab["thermo"]

PCR = {"steps": [{"temp": 95, "hold_s": 30}, {"temp": 58, "hold_s": 30}, {"temp": 72, "hold_s": 45}],
       "cycles": 3}

with arm, thermo:                                   # leases on both, kept alive by a heartbeat
    arm.write("speed", 30)                          # descriptor notes: <=30% near open plates
    arm.write("gripper_force", 20)                  # <25 N so plates aren't deformed
    arm.wait(arm.invoke("home"))

    thermo.wait(thermo.invoke("open_lid", approved=True))
    arm.wait(arm.invoke("pick_plate", location="deck_A1"))
    arm.wait(arm.invoke("place_plate", location="thermocycler"))
    arm.wait(arm.invoke("home"))                    # clear of the lid
    thermo.wait(thermo.invoke("close_lid"))

    thermo.write("lid_heater", True)
    job = thermo.invoke("run_protocol", **PCR)      # long-running: device does the work
    while (j := thermo.status(job))["state"] == "running":
        print(f"  cycle {thermo.read('cycle')}  block {thermo.read('block_temperature'):6.1f} degC  "
              f"{j['progress']*100:5.1f}%")
        time.sleep(0.15)
    print("thermocycler result:", j["result"])

    thermo.write("target_temperature", 4)           # hold at 4 degC
    try:
        thermo.write("target_temperature", -20)     # refused by the driver, never reaches hardware
    except RemoteError as e:
        print("guarded write refused:", e.message)

    thermo.write("lid_heater", False)
    thermo.wait(thermo.invoke("open_lid", approved=True))
    arm.wait(arm.invoke("pick_plate", location="thermocycler"))
    arm.wait(arm.invoke("place_plate", location="deck_A2"))
    arm.wait(arm.invoke("home"))

print("done. plate is at deck_A2, block at", thermo.read("block_temperature"), "degC")
