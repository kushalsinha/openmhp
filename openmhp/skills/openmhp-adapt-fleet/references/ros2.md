# ROS 2 → MHP

`openmhp.adapters.ros2.ros2_device(node_name, *, device, signals, settings, actions, estop)`

Source the workspace first (`source install/setup.bash`) so `rclpy` and message packages import.

```python
from openmhp.adapters.ros2 import ros2_device
DEVICE = ros2_device("mhp_ur5e",
    device={"id": "ur5e-01", "class": "robot_arm", "location": "cell 7", "tags": ["assembly", "motion"],
            "notes": "UR5e on the assembly cell. 5 kg payload; keep-out is the fenced cell."},
    signals={"joint_positions": ("/joint_states", "sensor_msgs/msg/JointState", "position"),
             "estop_clear": ("/safety/estop_clear", "std_msgs/msg/Bool", "data")},
    settings={"speed_scale": ("/speed_scaling", "std_msgs/msg/Float64", "data", {"min": 0.05, "max": 1.0})},
    actions={"move_to_joints": ("/follow_joint_trajectory", "control_msgs/action/FollowJointTrajectory",
                                {"interlocks": ["estop_clear"], "duration": "long",
                                 "params": {"trajectory": "JointTrajectory as nested dict"}})},
    estop=("/ur_hardware_interface/dashboard/stop", "std_srvs/srv/Trigger"))
```

| ROS 2 | MHP |
|---|---|
| topic subscription | signal (last message, field path) |
| topic publication | setting (one field) |
| action server | action; feedback `progress` → `jobs/progress`; cancel → `cancel_goal` |
| Trigger service | estop |
| parameters | not mapped in 0.2; wrap `set_parameters` in a `BoundDriver` Setting if needed |

Goal messages are built from `params` with `set_message_fields`, so nested dicts must match
the message layout exactly; put an example in `examples`.
