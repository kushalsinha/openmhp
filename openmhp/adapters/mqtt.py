"""MQTT -> MHP.

    from openmhp.adapters.mqtt import mqtt_device
    dev = mqtt_device("mqtt://broker.lab.local:1883",
        device={"id": "incubator-07", "class": "incubator", "location": "bay 4",
                "notes": "CO2 incubator publishing on the lab's shared broker."},
        signals={"temperature": ("lab/incubator-07/temperature", "degC"),
                 "door_closed": ("lab/incubator-07/door", "boolean"),
                 "co2_pct": ("lab/incubator-07/co2", "percent", 30)},          # 30 s staleness window
        settings={"setpoint": ("lab/incubator-07/cmd/setpoint", {"min": 4, "max": 55}, "degC")},
        actions={"purge_co2": ("lab/incubator-07/cmd/purge", "lab/incubator-07/evt/purge",
                               {"approval": "confirm", "duration": "short"})},
        estop=("lab/incubator-07/cmd/stop", None))

Mapping
  topic (subscribe)     -> signal   (topic, unit_or_type[, max_age_s])   last message cached with its
                                    arrival time; older than max_age_s (default 5 s) reads as None, so a
                                    stale interlock counts as open, same rule ROS 2 uses. Payload is decoded
                                    as JSON when it parses, otherwise kept as the raw decoded string.
  topic (publish)       -> setting  (command_topic, limits?, unit?)   value is published JSON-encoded,
                                    QoS 1, not retained. MQTT has no read-back for a plain publish; pair a
                                    setting with a signal on the device's own state topic if it has one.
  command + reply topic -> action   (command_topic, reply_topic_or_None, opts)   publishes
                                    {**params, "job": job.id} to command_topic; with a reply_topic, waits for
                                    a message there whose "job" field matches, and returns its payload as the
                                    result (a "status": "failed" or "cancelled" field raises accordingly).
                                    Without a reply_topic the action is fire-and-forget: it returns once the
                                    broker has acknowledged the publish (QoS 1), which confirms delivery to
                                    the broker, not that the device acted on it.
  stop topic             -> estop   (topic, payload)   published at QoS 2. Like the action above, this
                                    confirms the broker received it, not that the device stopped — pair it
                                    with a signal on a state topic the device publishes back, and read that
                                    signal to confirm, the way the rest of MHP treats safety: a claim is
                                    evidence only once something read from the device shows it.

Needs paho-mqtt (`pip install "openmhp[mqtt]"` or `[all]`); pass `client=` to inject a fake for tests, or
your own configured `paho.mqtt.client.Client` (auth, TLS, a shared connection with other subscribers).
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Any

from ..driver import JobCancelled
from .base import Action, BoundDriver, Setting, Signal

DEFAULT_MAX_AGE_S = 5.0
DEFAULT_ACTION_TIMEOUT_S = 30.0


def _decode(payload: bytes | str) -> Any:
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", errors="replace")
    try:
        return json.loads(payload)
    except (ValueError, TypeError):
        return payload


def _encode(value: Any) -> bytes:
    return (value if isinstance(value, str) else json.dumps(value)).encode("utf-8")


def _connect(url: str):
    import paho.mqtt.client as mqtt
    from urllib.parse import urlparse

    u = urlparse(url if "://" in url else f"mqtt://{url}")
    c = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    if u.username:
        c.username_pw_set(u.username, u.password)
    c.connect(u.hostname or "localhost", u.port or 1883, keepalive=30)
    c.loop_start()
    return c


class _Router:
    """One on_message dispatcher shared by every topic this device cares about, so mqtt_device
    needs exactly one subscription pass regardless of how many signals or actions it declares."""

    def __init__(self, client):
        self.client = client
        self._handlers: dict[str, list] = {}
        self._lock = threading.Lock()
        client.on_message = self._on_message
        client.on_connect = self._on_connect  # noqa: E731  resubscribe after a reconnect

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        with self._lock:
            for topic in self._handlers:
                client.subscribe(topic, qos=1)

    def _on_message(self, client, userdata, msg):
        with self._lock:
            handlers = list(self._handlers.get(msg.topic, ()))
        for h in handlers:
            try:
                h(_decode(msg.payload))
            except Exception:                              # noqa: BLE001  one bad handler must not drop others
                pass

    def on(self, topic: str, handler) -> None:
        with self._lock:
            new = topic not in self._handlers
            self._handlers.setdefault(topic, []).append(handler)
        if new:
            self.client.subscribe(topic, qos=1)


def mqtt_device(url: str = "", *, device: dict, signals: dict | None = None, settings: dict | None = None,
                actions: dict | None = None, estop: tuple | None = None, physical: dict | None = None,
                client=None) -> BoundDriver:
    client = client or _connect(url)
    router = _Router(client)
    cache: dict[str, tuple[Any, float]] = {}

    def sig(name, spec):
        if isinstance(spec, str):
            topic, unit, max_age = spec, None, DEFAULT_MAX_AGE_S
        else:
            topic = spec[0]
            unit = spec[1] if len(spec) > 1 else None
            max_age = float(spec[2]) if len(spec) > 2 else DEFAULT_MAX_AGE_S
        router.on(topic, lambda v, t=topic: cache.__setitem__(t, (v, time.monotonic())))
        typ = "boolean" if unit == "boolean" else "number" if unit not in (None, "string") else "string"

        def read():
            entry = cache.get(topic)
            if entry is None or time.monotonic() - entry[1] > max_age:
                return None                                # no fresh sample: never report a stale value
            return entry[0]
        return Signal(name, read=read, type=typ, unit=None if typ != "number" else unit,
                      notes=f"{topic}; stale after {max_age}s")

    def setting(name, spec):
        topic, limits, unit = (spec, None, None) if isinstance(spec, str) else (tuple(spec) + (None, None))[:3]

        def write(v):
            info = client.publish(topic, _encode(v), qos=1)
            info.wait_for_publish(timeout=5.0) if hasattr(info, "wait_for_publish") else None
        return Setting(name, write=write, limits=limits, unit=unit, notes=f"publishes {topic}")

    def action(name, spec):
        cmd_topic, reply_topic, raw_opts = (tuple(spec) + (None, {}))[:3]
        opts = dict(raw_opts or {})
        timeout_s = float(opts.pop("timeout_s", DEFAULT_ACTION_TIMEOUT_S))
        cancel_topic = opts.pop("cancel_topic", None)
        opts.setdefault("cancellable", bool(cancel_topic))          # honest default: no cancel topic, no real cancel

        pending: dict[str, dict] = {}                         # job id -> {"event": Event, "result": dict}
        if reply_topic is not None:
            def on_reply(v):
                if not (isinstance(v, dict) and v.get("job") in pending):
                    return
                entry = pending[v["job"]]
                entry["result"].update(v)
                entry["event"].set()
            router.on(reply_topic, on_reply)                  # subscribed once, up front, not per invoke

        def run(job, params):
            corr = job.id or uuid.uuid4().hex
            payload = {**params, "job": corr}
            if reply_topic is None:
                info = client.publish(cmd_topic, _encode(payload), qos=1)
                if hasattr(info, "wait_for_publish"):
                    info.wait_for_publish(timeout=5.0)
                return {"published": True, "note": "no reply_topic: broker delivery confirmed, device outcome unknown"}
            entry = pending[corr] = {"event": threading.Event(), "result": {}}
            try:
                client.publish(cmd_topic, _encode(payload), qos=1)
                deadline = time.monotonic() + timeout_s
                cancel_sent = False
                while not entry["event"].is_set():
                    if time.monotonic() > deadline:
                        raise TimeoutError(f"no reply on {reply_topic} for job {corr} within {timeout_s}s")
                    if job.cancel_requested and cancel_topic and not cancel_sent:
                        client.publish(cancel_topic, _encode({"job": corr}), qos=1)
                        cancel_sent = True                    # one cancel publish is enough
                    prog = entry["result"].get("progress")
                    if prog is not None:
                        driver.progress(job, float(prog))
                    entry["event"].wait(0.1)
            finally:
                pending.pop(corr, None)
            status = entry["result"].get("status")
            if status == "cancelled":
                raise JobCancelled(job.id)
            if status == "failed":
                raise RuntimeError(entry["result"].get("error") or f"{name} reported status=failed")
            return entry["result"]
        return Action(name, run=run, **opts)

    def make_estop():
        topic, payload = estop
        return lambda: client.publish(topic, _encode(payload if payload is not None else {"estop": True}), qos=2)

    driver = BoundDriver(
        device=device, physical=physical,
        signals=[sig(n, s) for n, s in (signals or {}).items()],
        settings=[setting(n, s) for n, s in (settings or {}).items()],
        actions=[action(n, s) for n, s in (actions or {}).items()],
        estop=make_estop() if estop else None,
        extra={"mqtt": {"url": url}},
    )
    return driver
