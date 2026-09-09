# Named locations for arm-01

Coordinates are gripper-centre {x, y, z} in mm, arm base at the origin, z up.
The arm approaches every location from 60 mm above it.

| Name | x | y | z | Notes |
|---|---|---|---|---|
| deck_A1 | 120 | 340 | 80 | liquid handler deck, front-left slot |
| deck_A2 | 250 | 340 | 80 | liquid handler deck, front-right slot |
| thermocycler | -410 | 90 | 120 | block of thermocycler-01; lid must be open |

To add a location, edit `locations` in descriptor.yaml and teach it in `free_drive` (human only).
