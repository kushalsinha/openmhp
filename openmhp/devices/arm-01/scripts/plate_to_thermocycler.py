# mhp_run script: move a plate from deck_A1 to the thermocycler and verify.
arm = lab["arm-01"]
with arm:
    arm.write("speed", 30)
    arm.write("gripper_force", 20)
    if not arm.read("homed"):
        arm.wait(arm.invoke("home"))
    arm.wait(arm.invoke("pick_plate", location="deck_A1"))
    arm.wait(arm.invoke("place_plate", location="thermocycler"))
print("plate placed; holding_plate =", arm.read("holding_plate"), "position =", arm.read("position"))
