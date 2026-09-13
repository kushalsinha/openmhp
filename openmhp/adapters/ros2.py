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
  topic (subscribe)   -> signal   (topic, msg_type, field path[, max_age_s])   last message cached with its
                                  arrival time; older than max_age_s (default 2 s) reads as None, so a
                                  stale interlock counts as open
  topic (publish)     -> setting  (topic, msg_type, field, limits?)
  action server       -> action   (name, action_type, opts); goal built from params,
                                  feedback -> jobs/progress if it has a `progress` field,
                                  cancel_requested -> one cancel_goal request; the job reports the
                                  goal's terminal status (succeeded, canceled, aborted), not just its payload
  service (Trigger)   -> estop    (name, srv_type)

Needs rclpy and the message packages on the PYTHONPATH (source your ROS 2
workspace first). The node spins on a background thread.
"""
from __future__ import annotations

import threading
import time

from ..driver import JobCancelled
from .base import Action, BoundDriver, Setting, Signal


def _field(msg, path: str):
    for part in path.split("."):
        msg = getattr(msg, part)
    return list(msg) if hasattr(msg, "__iter__") and not isinstance(msg, (str, bytes)) else msg


def ros2_device(node_name: str, *, device: dict, signals: dict | None = None, settings: dict | None = None,
                actions: dict | None = None, estop: tuple | None = None, physical: dict | None = None,
                spin: bool = True) -> BoundDriver:
    import rclpy
    from action_msgs.msg import GoalStatus
    from rclpy.action import ActionClient
    from rosidl_runtime_py.utilities import get_message, get_action, get_service
    from rosidl_runtime_py.set_message import set_message_fields

    if not rclpy.ok():
        rclpy.init()
    node = rclpy.create_node(node_name)
    if spin:
        threading.Thread(target=rclpy.spin, args=(node,), daemon=True).start()

    cache: dict[str, tuple[object, float]] = {}

    def sig(name, spec):
        topic, mtype, path, *rest = spec
        max_age = float(rest[0]) if rest else 2.0
        node.create_subscription(get_message(mtype), topic, lambda m, t=topic: cache.__setitem__(t, (m, time.monotonic())), 10)

        def read():
            entry = cache.get(topic)
            if entry is None or time.monotonic() - entry[1] > max_age:
                return None                                   # no fresh sample: never report a stale value
            return _field(entry[0], path)
        return Signal(name, read=read, notes=f"{topic} ({mtype}).{path}; stale after {max_age}s")

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
            cancel_sent = False
            while not rfut.done():
                if job.cancel_requested and not cancel_sent:
                    handle.cancel_goal_async()
                    cancel_sent = True
                time.sleep(0.1)
            wrapped = rfut.result()
            res = wrapped.result
            payload = {f: _field(res, f) for f in res.get_fields_and_field_types()}
            if wrapped.status == GoalStatus.STATUS_SUCCEEDED:
                return payload
            if wrapped.status == GoalStatus.STATUS_CANCELED:
                raise JobCancelled(job.id)
            raise RuntimeError(f"goal ended with status {wrapped.status} (aborted or unknown): {payload}")
        return Action(name, run=run, **{"duration": "long", **opts})

    def make_estop():
        sname, stype = estop
        S = get_service(stype)
        cli = node.create_client(S, sname)

        def stop():
            if not cli.wait_for_service(timeout_sec=2.0):
                raise RuntimeError(f"stop service {sname} is not available")
            fut = cli.call_async(S.Request())
            deadline = time.monotonic() + 5.0
            while not fut.done():
                if time.monotonic() > deadline:
                    raise RuntimeError(f"stop service {sname} did not answer within 5 s")
                time.sleep(0.05)
            resp = fut.result()
            if getattr(resp, "success", True) is False:
                raise RuntimeError(f"stop service {sname} reported failure: {getattr(resp, 'message', '')}")
        return stop

    driver = BoundDriver(
        device=device, physical=physical,
        signals=[sig(n, s) for n, s in (signals or {}).items()],
        settings=[setting(n, s) for n, s in (settings or {}).items()],
        actions=[action(n, s) for n, s in (actions or {}).items()],
        estop=make_estop() if estop else None,
        extra={"ros2": {"node": node_name}},
    )
    return driver
