# mhp_run script: move a plate from deck_A1 onto thermocycler-01 and verify.
# The arm will not move into the thermocycler while its lid is closed, so the lid is opened first
# (a person confirms) and closed again once the arm is clear.
arm, tc = lab["arm-01"], lab["thermocycler-01"]
with arm, tc:
    arm.write("speed", 30)
    arm.write("gripper_force", 20)
    if not arm.read("homed"):
        arm.wait(arm.invoke("home"))
    if tc.read("lid_closed"):
        tc.wait(tc.invoke("open_lid"))
    arm.wait(arm.invoke("pick_plate", location="deck_A1"))
    arm.wait(arm.invoke("place_plate", location="thermocycler"))
    arm.wait(arm.invoke("home"))
    tc.wait(tc.invoke("close_lid"))
print("plate placed; holding_plate =", arm.read("holding_plate"), "lid_closed =", tc.read("lid_closed"))
