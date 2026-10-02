"""MHP driver for an Elveflow MUX Distributor (rotary selection valve) through the Elveflow SDK."""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time

from openmhp.driver import DeviceFault, Driver, InvalidValue, Job, LimitViolation

HERE = pathlib.Path(__file__).parent
ROTATION = {"shortest": 0, "clockwise": 1, "counterclockwise": 2}
SWITCH_TIMEOUT_S = 15


def load_config() -> dict:
    p = HERE / "config.json"
    return json.loads(p.read_text()) if p.is_file() else {}


class ElveflowMux:
    def __init__(self, cfg: dict):
        self.cfg = cfg

    def open(self) -> None:
        cfg = self.cfg
        if not cfg.get("visa_com"):
            raise DeviceFault("config.json is missing (copy config.example.json and fill it in)")
        from ctypes import byref, c_int32
        if cfg.get("sdk_dll_dir") and hasattr(os, "add_dll_directory"):
            os.add_dll_directory(cfg["sdk_dll_dir"])
        for d in (cfg.get("sdk_python_dir"), cfg.get("sdk_dll_dir")):
            if d:
                sys.path.append(d)
        import Elveflow64 as ef
        self.ef, self.byref, self.c_int32 = ef, byref, c_int32
        self.id = c_int32()
        self._ok(ef.MUX_DRI_Initialization(cfg["visa_com"].encode("ascii"), byref(self.id)), "MUX_DRI_Initialization")

    @staticmethod
    def _ok(err, what: str) -> None:
        if err not in (0, None):
            raise DeviceFault(f"Elveflow SDK {what} returned error {err}")

    def set_valve(self, port: int, rotation: int) -> None:
        self._ok(self.ef.MUX_DRI_Set_Valve(self.id.value, port, rotation), "MUX_DRI_Set_Valve")

    def get_valve(self) -> int:
        v = self.c_int32(-1)
        self._ok(self.ef.MUX_DRI_Get_Valve(self.id.value, self.byref(v)), "MUX_DRI_Get_Valve")
        return int(v.value)

    def home(self) -> None:
        from ctypes import create_string_buffer
        answer = create_string_buffer(40)
        self._ok(self.ef.MUX_DRI_Send_Command(self.id.value, 0, answer, 40), "MUX_DRI_Send_Command(home)")

    def close(self) -> None:
        self.ef.MUX_DRI_Destructor(self.id.value)


class MuxDistributor(Driver):
    def setup(self) -> None:
        self.cfg = load_config()
        self.hw = None

    def make_backend(self):
        return ElveflowMux(self.cfg)

    def _hw(self):
        if self.hw is None:
            hw = self.make_backend()
            try:
                hw.open()
            except Exception as e:                    # noqa: BLE001
                raise DeviceFault(f"cannot open the MUX Distributor: {type(e).__name__}: {e}") from None
            self.hw = hw
        return self.hw

    def on_read(self, name: str):
        if name == "connected":
            try:
                self._hw()
                return True
            except DeviceFault:
                return False
        if name == "valve_position":
            return self._hw().get_valve()
        if name == "port_map":
            return self.cfg.get("port_map") or {}
        raise InvalidValue(f"unknown signal {name}")

    def validate_params(self, action: str, params: dict) -> None:
        if action == "select_port":
            port, n = params.get("port"), int(self.cfg.get("ports", 12))
            if not isinstance(port, int) or isinstance(port, bool):
                raise InvalidValue("select_port.port must be an integer")
            if port > n:
                raise LimitViolation(f"select_port.port={port} but this valve has {n} ports", {"min": 1, "max": n})

    def on_invoke(self, job: Job):
        hw = self._hw()
        if job.action == "home":
            hw.home()
            return {"homed": True, "valve_position": hw.get_valve()}
        if job.action == "select_port":
            port = int(job.params["port"])
            hw.set_valve(port, ROTATION[job.params.get("rotation", "shortest")])
            deadline = time.monotonic() + SWITCH_TIMEOUT_S
            while time.monotonic() < deadline:
                self.checkpoint(job)
                if hw.get_valve() == port:
                    self.emit_signal("valve_position", port)
                    return {"valve_position": port, "connected_to": (self.cfg.get("port_map") or {}).get(str(port))}
                time.sleep(0.2)
            raise DeviceFault(f"valve did not reach port {port} within {SWITCH_TIMEOUT_S} s (reads {hw.get_valve()})")
        raise InvalidValue(f"unhandled action {job.action}")
