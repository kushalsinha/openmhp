---
mhp: "2026-09-09"
id: arm-01
class: robot_arm
make: SimRobotics
model: PH-6
location: bay 3
tags: [plates, motion, sbs]
description: Six-axis plate-handling arm between the liquid handler and thermocycler-01, 850 mm reach, 1.5 kg payload. Use to move SBS microplates between deck_A1, deck_A2 and the thermocycler. Not for tubes or lids; gripper crushes PCR tubes.
driver: driver.py:SimArm
---

# Arm-01

Floor-standing on a 600 × 600 mm base in bay 3. A light curtain rings the arm at 1 m; anyone
inside opens the `safe_zone_clear` interlock and every motion is refused until they leave.

## Operating procedure

1. `home` once per session; other actions refuse until `homed` is true.
2. Set `speed` to 30 or less whenever people work nearby or plates are unsealed. 100 is 1.2 m/s.
3. Set `gripper_force` at 20 N for polypropylene plates; above 25 N deforms them.
4. `pick_plate` then `place_plate` with a named location (`deck_A1`, `deck_A2`, `thermocycler`).
   The arm will not pick while holding, and will not place while empty.
5. Hold a lease across a pick and place pair so no other agent interleaves a move.

## What to watch

- `holding_plate` after a pick, and `position` near the target after a place.
- A motion aborted by the light curtain fails the job and leaves the device in `fault`. Read
  `safe_zone_clear`, ask the person to step out, then `safety/reset`.
- `free_drive` is manual teach mode and is forbidden to agents by design.

## Resources

- `references/locations.md`: the coordinate table behind the named locations.
- `scripts/plate_to_thermocycler.py`: pick from deck_A1, place on the thermocycler, verify.
