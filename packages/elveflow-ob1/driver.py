"""MHP driver for an Elveflow OB1 pressure controller (with MFS flow sensors read through it).

Hardware settings live in `config.json` next to this file (see config.example.json and
references/setup.md). The file is optional at import time so the package validates anywhere;
`connected` reads false and everything else raises until the SDK session opens.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

from openmhp.driver import DeviceFault, Driver, InvalidValue, Job

HERE = pathlib.Path(__file__).parent
CHANNELS = (1, 2, 3, 4)
CALIB_LEN = 1000


def load_config() -> dict:
    p = HERE / "config.json"
    return json.loads(p.read_text()) if p.is_file() else {}


class ElveflowOB1:
    """Thin wrapper over the Elveflow SDK (Elveflow64.py + Elveflow64.dll, Windows only)."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.remote = False

    def open(self) -> None:
        cfg = self.cfg
        if not cfg.get("device_name"):
            raise DeviceFault("config.json is missing (copy config.example.json and fill it in)")
        from ctypes import byref, c_double, c_int32
        if cfg.get("sdk_dll_dir") and hasattr(os, "add_dll_directory"):
            os.add_dll_directory(cfg["sdk_dll_dir"])
        if cfg.get("sdk_python_dir"):
            sys.path.append(cfg["sdk_python_dir"])
            if cfg.get("sdk_dll_dir"):
                sys.path.append(cfg["sdk_dll_dir"])
        import Elveflow64 as ef
        self.ef, self.byref, self.c_double = ef, byref, c_double
        self.id = c_int32()
        regs = (list(cfg.get("regulators", [])) + [0, 0, 0, 0])[:4]
        self._ok(ef.OB1_Initialization(cfg["device_name"].encode("ascii"), *regs, byref(self.id)), "OB1_Initialization")
        for ch, s in (cfg.get("sensors") or {}).items():
            args = (self.id, int(ch), int(s["type"]), int(s.get("digital", 1)), int(s.get("calibration", 0)),
                    int(s.get("resolution", 7)))
            try:
                err = ef.OB1_Add_Sens(*args, 0)             # newer SDKs take a custom-sensor voltage
            except TypeError:
                err = ef.OB1_Add_Sens(*args)
            self._ok(err, f"OB1_Add_Sens ch{ch}")
        self.calib = (c_double * CALIB_LEN)()
        if cfg.get("calibration_file"):
            self._ok(ef.Elveflow_Calibration_Load(cfg["calibration_file"].encode("ascii"), byref(self.calib), CALIB_LEN),
                     "Elveflow_Calibration_Load")
        else:
            self._ok(ef.Elveflow_Calibration_Default(byref(self.calib), CALIB_LEN), "Elveflow_Calibration_Default")

    @staticmethod
    def _ok(err, what: str) -> None:
        if err not in (0, None):
            raise DeviceFault(f"Elveflow SDK {what} returned error {err}")

    def set_pressure(self, ch: int, mbar: float) -> None:
        if self.remote:
            self._ok(self.ef.OB1_Set_Remote_Target(self.id.value, ch, self.c_double(mbar)), "OB1_Set_Remote_Target")
        else:
            self._ok(self.ef.OB1_Set_Press(self.id.value, ch, self.c_double(mbar), self.byref(self.calib), CALIB_LEN),
                     "OB1_Set_Press")

    def _remote_data(self, ch: int) -> tuple[float, float]:
        reg, sens = self.c_double(), self.c_double()
        self._ok(self.ef.OB1_Get_Remote_Data(self.id.value, ch, self.byref(reg), self.byref(sens)), "OB1_Get_Remote_Data")
        return reg.value, sens.value

    def pressure(self, ch: int) -> float:
        if self.remote:
            return self._remote_data(ch)[0]
        v = self.c_double()
        self._ok(self.ef.OB1_Get_Press(self.id.value, ch, 1, self.byref(self.calib), self.byref(v), CALIB_LEN), "OB1_Get_Press")
        return v.value

    def flow(self, ch: int) -> float:
        if self.remote:
            return self._remote_data(ch)[1]
        v = self.c_double()
        self._ok(self.ef.OB1_Get_Sens_Data(self.id.value, ch, 1, self.byref(v)), "OB1_Get_Sens_Data")
        return v.value

    def start_flow_control(self, ch: int, sensor_ch: int, target: float, p: float, i: float) -> None:
        if not self.remote:
            self._ok(self.ef.OB1_Start_Remote_Measurement(self.id.value, self.byref(self.calib), CALIB_LEN),
                     "OB1_Start_Remote_Measurement")
            self.remote = True
        self._ok(self.ef.PID_Add_Remote(self.id.value, ch, self.id.value, sensor_ch, self.c_double(p), self.c_double(i), 1),
                 "PID_Add_Remote")
        self._ok(self.ef.OB1_Set_Remote_Target(self.id.value, ch, self.c_double(target)), "OB1_Set_Remote_Target")

    def stop_flow_control(self) -> None:
        if self.remote:
            self._ok(self.ef.OB1_Stop_Remote_Measurement(self.id.value), "OB1_Stop_Remote_Measurement")
            self.remote = False

    def close(self) -> None:
        self.ef.OB1_Destructor(self.id.value)


class OB1(Driver):
    def setup(self) -> None:
        self.cfg = load_config()
        self.hw = None
        self.open_error: str | None = None
        self.flow_loops: dict[int, int] = {}          # regulator channel -> sensor channel

    def make_backend(self):
        return ElveflowOB1(self.cfg)

    def _hw(self):
        if self.hw is None:
            hw = self.make_backend()
            try:
                hw.open()
            except Exception as e:                    # noqa: BLE001
                self.open_error = f"{type(e).__name__}: {e}"
                raise DeviceFault(f"cannot open the OB1: {self.open_error}") from None
            self.hw, self.open_error = hw, None
        return self.hw

    def _regulated(self, ch: int) -> bool:
        regs = (list(self.cfg.get("regulators", [])) + [0, 0, 0, 0])[:4]
        return bool(regs[ch - 1])

    def _has_sensor(self, ch: int) -> bool:
        return str(ch) in (self.cfg.get("sensors") or {})

    def on_read(self, name: str):
        if name == "connected":
            try:
                self._hw()
                return True
            except DeviceFault:
                return False
        if name == "flow_control_active":
            return bool(self.flow_loops)
        kind, _, ch = name.rpartition("_ch")
        ch = int(ch)
        if kind == "pressure":
            return round(self._hw().pressure(ch), 2) if self._regulated(ch) else None
        if kind == "flow":
            return round(self._hw().flow(ch), 2) if self._has_sensor(ch) else None
        if kind == "pressure_setpoint":
            return getattr(self, "_sp", {}).get(ch)
        raise InvalidValue(f"unknown signal {name}")

    def on_write(self, name: str, value) -> None:
        ch = int(name.rpartition("_ch")[2])
        if not self._regulated(ch):
            raise InvalidValue(f"channel {ch} has no regulator in config.json")
        if ch in self.flow_loops:
            raise InvalidValue(f"channel {ch} is under flow control; invoke stop_flow_control first")
        self._hw().set_pressure(ch, float(value))
        self.__dict__.setdefault("_sp", {})[ch] = float(value)

    def validate_params(self, action: str, params: dict) -> None:
        if action == "set_flow":
            ch = params.get("channel")
            sch = params.get("sensor_channel", ch)
            if isinstance(ch, int) and self.cfg and not self._regulated(ch):
                raise InvalidValue(f"channel {ch} has no regulator in config.json")
            if isinstance(sch, int) and self.cfg and not self._has_sensor(sch):
                raise InvalidValue(f"no flow sensor is configured on channel {sch}")

    def on_invoke(self, job: Job):
        hw = self._hw()
        p = job.params
        if job.action == "set_flow":
            ch = int(p["channel"])
            sch = int(p.get("sensor_channel", ch))
            pid = self.cfg.get("pid") or {}
            hw.start_flow_control(ch, sch, float(p["flow_ul_min"]), float(p.get("p", pid.get("p", 0.05))),
                                  float(p.get("i", pid.get("i", 0.01))))
            self.flow_loops[ch] = sch
            return {"channel": ch, "sensor_channel": sch, "target_ul_min": float(p["flow_ul_min"])}
        if job.action == "stop_flow_control":
            self._all_zero(hw)
            return {"stopped": True}
        if job.action == "vent":
            self._all_zero(hw)
            return {"vented": True, "pressures": {ch: round(hw.pressure(ch), 1) for ch in CHANNELS if self._regulated(ch)}}
        raise InvalidValue(f"unhandled action {job.action}")

    def _all_zero(self, hw) -> None:
        hw.stop_flow_control()
        self.flow_loops.clear()
        for ch in CHANNELS:
            if self._regulated(ch):
                hw.set_pressure(ch, 0.0)
        self._sp = {}

    def on_estop(self) -> None:
        try:
            if self.hw is not None:
                self._all_zero(self.hw)
        except Exception:                             # noqa: BLE001  must not raise
            pass
