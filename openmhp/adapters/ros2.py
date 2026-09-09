"""ROS 2 -> MHP.

    from openmhp.adapters.ros2 import ros2_device
    dev = ros2_device("mhp_ur5e",
        device={"id": "ur5e-01", "class": "robot_arm", "location": "cell 7",
                "notes": "UR5e on the assembly cell. 5 kg payload."},
        signals={"joint_positions": ("/joint_states", "sensor_msgs/msg/JointState", "position"),
                 "estop_clear": ("/safety/estop_clear", "std_msgs/msg/Bool", "data")},
        settings={"speed_scale": ("/speed_scaling", "std_msgs/msg/Float64", "data", {"min": 0.05, "max": 1.0})},
        actions={"move_to_joints": ("/follow_joint_trajectory",
                                    "control_msgs/action/FollowJointTrajectory",
                                    {"interlocks": ["estop_clear"], "duration": "long"})},
        estop=("/ur_hardware_interface/dashboard/stop", "std_srvs/srv/Trigger"))

Mapping
  topic (subscribe)   -> signal   (topic, msg_type, field path)   last message cached
  topic (publish)     -> setting  (topic, msg_type, field, limits?)
  action server       -> action   (name, action_type, opts); goal built from params,
                                  feedback -> jobs/progress if it has a `progress` field,
                                  cancel_requested -> cancel_goal
  service (Trigger)   -> estop    (name, srv_type)

Needs rclpy and the message packages on the PYTHONPATH (source your ROS 2
workspace first). The node spins on a background thread.
"""
from __future__ import annotations

import threading
import time

from .base import Action, BoundDriver, Setting, Signal


def _field(msg, path: str):
    for part in path.split("."):
        msg = getattr(msg, part)
    return list(msg) if hasattr(msg, "__iter__") and not isinstance(msg, (str, bytes)) else msg


def ros2_device(node_name: str, *, device: dict, signals: dict | None = None, settings: dict | None = None,
                actions: dict | None = None, estop: tuple | None = None, physical: dict | None = None,
                spin: bool = True) -> BoundDriver:
    import rclpy
    from rclpy.action import ActionClient
    from rosidl_runtime_py.utilities import get_message, get_action, get_service
    from rosidl_runtime_py.set_message import set_message_fields

    if not rclpy.ok():
        rclpy.init()
    node = rclpy.create_node(node_name)
    if spin:
        threading.Thread(target=rclpy.spin, args=(node,), daemon=True).start()

    cache: dict[str, object] = {}

    def sig(name, spec):
        topic, mtype, path = spec
        node.create_subscription(get_message(mtype), topic, lambda m, t=topic: cache.__setitem__(t, m), 10)
        return Signal(name, read=lambda: _field(cache[topic], path) if topic in cache else None,
                      notes=f"{topic} ({mtype}).{path}")

    def setting(name, spec):
        topic, mtype, field, *rest = spec
        pub = node.create_publisher(get_message(mtype), topic, 10)

        def write(v):
            msg = get_message(mtype)()
            set_message_fields(msg, {field: v})
            pub.publish(msg)
        return Setting(name, write=write, limits=rest[0] if rest else None, notes=f"publishes {topic}.{field}")

    def action(name, spec):
        aname, atype, opts = (spec + ({},))[:3]
        A = get_action(atype)
        ac = ActionClient(node, A, aname)

        def run(job, params):
            ac.wait_for_server(timeout_sec=5.0)
            goal = A.Goal()
            set_message_fields(goal, params)
            done = {}

            def on_feedback(fb):
                prog = getattr(fb.feedback, "progress", None)
                if prog is not None:
                    driver.progress(job, float(prog))
            fut = ac.send_goal_async(goal, feedback_callback=on_feedback)
            while not fut.done():
                time.sleep(0.05)
            handle = fut.result()
            if not handle.accepted:
                raise RuntimeError("goal rejected")
            rfut = handle.get_result_async()
            while not rfut.done():
                if job.cancel_requested:
                    handle.cancel_goal_async()
                time.sleep(0.1)
            res = rfut.result().result
            return {f: _field(res, f) for f in res.get_fields_and_field_types()}
        return Action(name, run=run, **{"duration": "long", **opts})

    def make_estop():
        sname, stype = estop
        S = get_service(stype)
        cli = node.create_client(S, sname)
        return lambda: cli.call_async(S.Request())

    driver = BoundDriver(
        device=device, physical=physical,
        signals=[sig(n, s) for n, s in (signals or {}).items()],
        settings=[setting(n, s) for n, s in (settings or {}).items()],
        actions=[action(n, s) for n, s in (actions or {}).items()],
        estop=make_estop() if estop else None,
        extra={"ros2": {"node": node_name}},
    )
    return driver
