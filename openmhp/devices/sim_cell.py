"""Shared physical state for simulators in one process.

Real cells share physics: an arm cannot put a plate through a closed lid. The
simulators register here by device id so a simulated arm can check the state of
the instrument a handoff location belongs to, instead of each simulator
pretending the other does not exist.
"""
from __future__ import annotations

import threading
import weakref

_devices: "weakref.WeakValueDictionary[str, object]" = weakref.WeakValueDictionary()
_lock = threading.Lock()


def register(device_id: str, driver: object) -> None:
    with _lock:
        _devices[device_id] = driver


def get(device_id: str):
    with _lock:
        return _devices.get(device_id)
