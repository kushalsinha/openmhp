# recipe: pcr-with-plate-transfer
# needs: robot_arm, thermocycler
# asks: which deck slot holds the plate; the cycling program and cycle count; where to put the plate afterwards; a person confirms each lid opening
# summary: Open the thermocycler lid, move a plate from the deck onto the block, close the lid, pre-heat it, run a cycling program, hold at 4 C, let the lid cool, open it and return the plate.
PARAMS = {"arm": None, "thermocycler": None, "plate_slot": "deck_A1", "return_slot": "deck_A2", "handoff": "thermocycler",
          "steps": [{"temp": 95, "hold_s": 30}, {"temp": 58, "hold_s": 30}, {"temp": 72, "hold_s": 45}], "cycles": 30,
          "hold_c": 4, "lid_ready_c": 100}

# Everything below is the recipe body; edit PARAMS, not this, unless the lab differs.
#
# The arm reaches a thermocycler through a named handoff location that its descriptor binds to one
# instrument. The recipe uses exactly that instrument, so it can never load an unrelated thermocycler.
# If a step fails, the driver latches a fault and runs its safe-state hook (heaters off, brakes on).
arm_id = PARAMS["arm"] or lab.find("plate handling robot arm", cls="robot_arm", state="idle")[0]["id"]
arm = lab[arm_id]
bound = (arm.describe().get("handoffs") or {}).get(PARAMS["handoff"])
if bound is None:
    raise RuntimeError(f"{arm_id} has no handoff location {PARAMS['handoff']!r} bound to an instrument; add it under handoffs in the arm's descriptor")
tc_id = bound if bound in lab else (bound + "-sim" if (bound + "-sim") in lab else bound)
if PARAMS["thermocycler"] and PARAMS["thermocycler"] not in (bound, bound + "-sim"):
    raise RuntimeError(f"{arm_id}'s {PARAMS['handoff']!r} location belongs to {bound}, not {PARAMS['thermocycler']}")
tc = lab[tc_id]

with arm, tc:
    arm.write("speed", 30)
    if not arm.read("homed"):
        arm.wait(arm.invoke("home"))

    # load: lid cool and open, plate in, arm clear, lid closed
    tc.write("lid_heater", False)
    tc.wait_until("lid_cool", lambda v: v is True, timeout=600, poll=5, label="lid below 60 C")
    if tc.read("lid_closed"):
        tc.wait(tc.invoke("open_lid"))                       # a person confirms
    arm.wait(arm.invoke("pick_plate", location=PARAMS["plate_slot"]))
    arm.wait(arm.invoke("place_plate", location=PARAMS["handoff"]))
    arm.wait(arm.invoke("home"))
    tc.wait(tc.invoke("close_lid"))

    # run: pre-heat the lid, cycle, hold
    tc.write("lid_heater", True)
    tc.wait_until("lid_temperature", lambda v: v >= PARAMS["lid_ready_c"], timeout=300, poll=2, label=f">= {PARAMS['lid_ready_c']} C")
    job = tc.wait(tc.invoke("run_protocol", steps=PARAMS["steps"], cycles=PARAMS["cycles"]))
    tc.write("target_temperature", PARAMS["hold_c"])

    # unload: lid off and cool, lid open, plate out, arm clear
    tc.write("lid_heater", False)
    tc.wait_until("lid_cool", lambda v: v is True, timeout=600, poll=5, label="lid below 60 C")
    tc.wait(tc.invoke("open_lid"))                           # a person confirms
    arm.wait(arm.invoke("pick_plate", location=PARAMS["handoff"]))
    arm.wait(arm.invoke("place_plate", location=PARAMS["return_slot"]))
    arm.wait(arm.invoke("home"))
print(f"pcr done on {tc_id}: {job['result']}; plate at {PARAMS['return_slot']}; block {tc.read('block_temperature')} C")
