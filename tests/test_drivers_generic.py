"""The declarative drivers a package can use with no code: serial ASCII (parse rules, ENQ/ACK),
SCPI over VISA/TCP/serial, and Modbus; plus the base's reserved signals (self-state and runtime)."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["OPENMHP_HOME"] = tempfile.mkdtemp(prefix="openmhp-generic-")   # job records are durable (C11); keep this run's own

from openmhp.client import LocalDevice, RemoteError            # noqa: E402
from openmhp.drivers.modbus import ModbusDriver, decode, encode  # noqa: E402
from openmhp.drivers.scpi_visa import ScpiVisaDriver           # noqa: E402
from openmhp.drivers.serial_ascii import SerialAsciiDriver     # noqa: E402
from openmhp.package import load_driver                        # noqa: E402

PKG_MD = """---
mhp: "2026-09-12"
id: {id}
class: {cls}
make: Test
model: T1
location: bench
tags: [test]
description: A test instrument used to exercise the declarative {cls} driver with a fake link; pick it in tests only.
driver: driver.py:Device
sim: sim.py:Sim
---
# Test

## Operating procedure

1. Read the signals. 2. Write a setpoint. 3. Invoke start. The lid must be closed before a run starts and the tray
   is where a robot places the sample; a person opens the door only when the run has ended and the drive stopped.
"""


def _package(tmp: Path, cls: str, descriptor: str, driver: str, sim: str, config: dict | None = None) -> Path:
    d = tmp / f"pkg-{cls}"
    d.mkdir()
    (d / "DEVICE.md").write_text(PKG_MD.format(id=f"test-{cls.replace('_', '-')}-01", cls=cls))
    (d / "descriptor.yaml").write_text(descriptor)
    (d / "driver.py").write_text(driver)
    (d / "sim.py").write_text(sim)
    if config is not None:
        (d / "config.json").write_text(json.dumps(config))
    return d


# ---------------------------------------------------------------- serial: parse rules, ENQ/ACK, reserved signals
SERIAL_DESC = """
signals:
  - {name: mass_flow, type: number, unit: L/min, notes: "4th field of the Alicat data frame"}
  - {name: setpoint_echo, type: number, unit: L/min}
  - {name: pressure, type: number, unit: mbar, notes: "Pfeiffer TPG reply '0,+1.2345E-03'"}
  - {name: robot_access_ready, type: boolean, notes: "true when the tray is out and parked"}
  - {name: state, type: string, source: runtime}
  - {name: busy, type: boolean, source: runtime}
  - {name: connected, type: boolean, source: runtime}
  - {name: calibration_status, type: string, source: record}
  - {name: calibration_due, type: string, source: record, nullable: true}
  - {name: qualification_status, type: string, source: record}
  - {name: usage_count, type: integer, source: record, notes: jobs completed here}
settings:
  - {name: setpoint, type: number, unit: L/min, limits: {min: 0, max: 10}, resolution: 0.01, approval: auto}
actions:
  - name: start
    duration: short
    approval: auto
    interlocks: [robot_access_ready]
  - name: ramp
    duration: long
    approval: auto
    params:
      target: {type: number, unit: L/min, limits: {min: 0, max: 10}}
      hold_s: {type: number, unit: s, limits: {min: 0, max: 60}, default: 1}
    required: [target]
    returns: {type: object, properties: {replies: {type: array, items: {type: string}}}}
    examples: [{target: 2.5}]
safety:
  estop: true
  interlocks: []
  watchdog_s: 30
  notes: stop zeroes the setpoint
serial:
  port: /dev/null
  read:    {mass_flow: "A", setpoint_echo: "A", pressure: "PR1", robot_access_ready: "TRAY?"}
  write:   {setpoint: "AS{value}"}
  actions: {start: ["A$$R"], ramp: ["AS{target}", "HOLD {hold_s}"]}
  estop:   ["AS0"]
  parse:
    mass_flow: {field: 4}
    setpoint_echo: {regex: "SP=([-+0-9.]+)", group: 1}
    pressure: {field: 2}
  booleans:
    robot_access_ready: {true: ["OUT"], false: ["IN", "MOVING"]}
"""

SERIAL_DRIVER = "from openmhp.drivers.serial_ascii import SerialAsciiDriver as Device\n"
SERIAL_SIM = """
from openmhp.drivers.serial_ascii import SerialAsciiDriver

class _Port:
    is_open = True
    def __init__(self): self.sp = 0.0; self.tray = "OUT"; self._r = b""; self.sent = []
    def write(self, b):
        c = b.decode().strip(); self.sent.append(c)
        if c == "A": self._r = f"A +014.70 +025.00 +01.234 +{self.sp:06.3f} {self.sp:06.3f} Air SP={self.sp}\\r\\n".encode()
        elif c == "PR1": self._r = b"0,+1.2345E-03\\r\\n"
        elif c == "TRAY?": self._r = (self.tray + "\\r\\n").encode()
        elif c.startswith("AS"): self.sp = float(c[2:]); self._r = b"OK\\r\\n"
        else: self._r = b"OK\\r\\n"
    def readline(self): return self._r

class Sim(SerialAsciiDriver):
    link = _Port()
"""


def test_serial_parse_rules_reserved_signals_and_self_state():
    with tempfile.TemporaryDirectory() as td:
        folder = _package(Path(td), "flow_controller", SERIAL_DESC, SERIAL_DRIVER, SERIAL_SIM,
                          config={"self_state": {"calibration_due": "2099-01-01", "qualified": True}})
        drv = load_driver(folder, sim=True)
        dev = LocalDevice(drv)
        assert dev.read("mass_flow") == 0.0 and dev.read("pressure") == 1.2345e-03
        dev.write("setpoint", 2.5)
        assert dev.read("mass_flow") == 2.5 and dev.read("setpoint_echo") == 2.5
        # reserved runtime signals are answered by the base when the serial map has no command
        assert dev.read("state") == "idle" and dev.read("busy") is False and dev.read("connected") is True
        # self-state comes from config.json's record; calibration status is derived from the due date
        assert dev.read("calibration_status") == "valid" and dev.read("qualification_status") == "qualified"
        assert dev.read("calibration_due") == "2099-01-01" and dev.read("usage_count") == 0
        card = dev.call("device/describe", {"detail": "card"})
        assert card["self_state"] == {"calibration_status": "valid", "qualification_status": "qualified"}
        # the interlock reads through the boolean map
        drv.link.tray = "MOVING"
        try:
            dev.invoke("start"); raise AssertionError("expected InterlockOpen")
        except RemoteError as e:
            assert e.code == -32011
        drv.link.tray = "OUT"
        r = dev.wait(dev.invoke("ramp", target=3))
        assert r["state"] == "done" and r["defaulted"] == {"ramp.hold_s": 1} and "HOLD 1" in drv.link.sent
        assert dev.read("usage_count") == 1                                   # counted from the device's own jobs
        try:
            dev.write("setpoint", 2.505); raise AssertionError("expected InvalidValue off the resolution grid")
        except RemoteError as e:
            assert e.code == -32014
        # a twin answers fault injection; the base never needs package code for it
        assert dev.call("sim/fault", {"mode": "raise", "on": "read"})["armed"]["mode"] == "raise"
        try:
            dev.read("mass_flow"); raise AssertionError("expected the injected fault")
        except RemoteError:
            pass
        drv.close()


def test_serial_enq_ack_handshake():
    class Port:
        is_open = True
        def __init__(self): self.step = 0; self.log = []
        def write(self, b):
            self.log.append(b)
            self.step += 1
        def readline(self):
            return b"\x06\r\n" if self.step % 2 == 1 else b"0,+9.8765E+02\r\n"

    with tempfile.TemporaryDirectory() as td:
        desc = SERIAL_DESC.replace("serial:\n  port: /dev/null", "serial:\n  port: /dev/null\n  enq: \"\\\\x05\"")
        folder = _package(Path(td), "vacuum_gauge", desc, SERIAL_DRIVER, SERIAL_SIM)
        drv = load_driver(folder, sim=True)
        drv.link = Port()
        dev = LocalDevice(drv)
        assert dev.read("pressure") == 987.65
        assert drv.link.log == [b"PR1\r\n", b"\x05"]
        drv.close()


# ---------------------------------------------------------------- SCPI over an injected link
SCPI_DESC = """
signals:
  - {name: voltage, type: number, unit: V}
  - {name: output_on, type: boolean}
  - {name: state, type: string, source: runtime}
  - {name: busy, type: boolean, source: runtime}
  - {name: calibration_status, type: string, source: record}
  - {name: qualification_status, type: string, source: record}
settings:
  - {name: voltage_setpoint, type: number, unit: V, limits: {min: -10, max: 10}, approval: auto}
actions:
  - {name: reset, duration: short, approval: auto, interlocks: []}
safety: {estop: true, interlocks: [], watchdog_s: 20, notes: estop turns the output off}
scpi:
  resource: "tcp://127.0.0.1:5025"
  idn_match: KEITHLEY
  read:    {voltage: "MEAS:VOLT?", output_on: "OUTP?"}
  write:   {voltage_setpoint: "SOUR:VOLT {value}"}
  actions: {reset: ["*RST", "*CLS"]}
  estop:   ["OUTP OFF"]
"""
SCPI_DRIVER = "from openmhp.drivers.scpi_visa import ScpiVisaDriver as Device\n"
SCPI_SIM = """
from openmhp.drivers.scpi_visa import ScpiVisaDriver

class _Inst:
    is_open = True
    def __init__(self): self.v = 0.0; self.out = 1; self._r = b""; self.sent = []
    def write(self, b):
        c = b.decode().strip(); self.sent.append(c)
        if c == "MEAS:VOLT?": self._r = f"{self.v:.6E}\\n".encode()
        elif c == "OUTP?": self._r = f"{self.out}\\n".encode()
        elif c.startswith("SOUR:VOLT "): self.v = float(c.split()[1]); self._r = b""
        elif c == "OUTP OFF": self.out = 0; self._r = b""
        elif c == "*IDN?": self._r = b"KEITHLEY INSTRUMENTS,MODEL 2400,1,1\\n"
        else: self._r = b""
    def readline(self): return self._r

class Sim(ScpiVisaDriver):
    link = _Inst()
"""


def test_scpi_driver_over_injected_link():
    with tempfile.TemporaryDirectory() as td:
        folder = _package(Path(td), "source_meter", SCPI_DESC, SCPI_DRIVER, SCPI_SIM)
        drv = load_driver(folder, sim=True)
        dev = LocalDevice(drv)
        assert dev.read("voltage") == 0.0 and dev.read("output_on") is True
        dev.write("voltage_setpoint", 1.5)
        assert dev.read("voltage") == 1.5 and "SOUR:VOLT 1.5" in drv.link.sent
        r = dev.wait(dev.invoke("reset"))
        assert r["state"] == "done" and drv.link.sent[-2:] == ["*RST", "*CLS"]
        dev.estop()
        assert drv.link.out == 0 and dev.read("state") == "estop"
        assert dev.read("calibration_status") == "unknown"                     # no record yet: says so, never guesses
        drv.close()


# ---------------------------------------------------------------- Modbus over an injected link
MODBUS_DESC = """
signals:
  - {name: temperature, type: number, unit: Cel}
  - {name: door_closed, type: boolean}
  - {name: setpoint_echo, type: number, unit: Cel}
  - {name: state, type: string, source: runtime}
  - {name: busy, type: boolean, source: runtime}
  - {name: calibration_status, type: string, source: record}
  - {name: qualification_status, type: string, source: record}
settings:
  - {name: setpoint, type: number, unit: Cel, limits: {min: 4, max: 60}, approval: auto}
  - {name: heater_on, type: boolean, approval: auto}
actions:
  - {name: start, duration: short, approval: auto, interlocks: [door_closed]}
  - name: hold
    duration: long
    approval: auto
    interlocks: [door_closed]
    params: {target: {type: number, unit: Cel, limits: {min: 4, max: 60}}}
    required: [target]
    returns: {type: object, properties: {steps: {type: integer}}}
    examples: [{target: 37}]
safety: {estop: true, interlocks: [door_closed], watchdog_s: 60, notes: estop clears the run coil and zeroes the setpoint}
modbus:
  host: 127.0.0.1
  unit: 1
  read:
    temperature:   {reg: 100, kind: input, type: int16, scale: 0.1}
    door_closed:   {reg: 3, kind: discrete}
    setpoint_echo: {reg: 200, kind: holding, type: float32}
  write:
    setpoint:  {reg: 200, kind: holding, type: float32}
    heater_on: {reg: 10, kind: coil}
  actions:
    start: [{reg: 20, kind: coil, value: 1}]
    hold:  [{reg: 200, kind: holding, type: float32, value: "{target}"}, {reg: 20, kind: coil, value: 1}]
  estop: [{reg: 20, kind: coil, value: 0}, {reg: 200, kind: holding, type: float32, value: 0}]
"""
MODBUS_DRIVER = "from openmhp.drivers.modbus import ModbusDriver as Device\n"
MODBUS_SIM = """
from openmhp.drivers.modbus import ModbusDriver

class _Plc:
    is_open = True
    def __init__(self):
        self.coils = {10: 0, 20: 0}; self.discrete = {3: 1}; self.holding = {200: 0, 201: 0}; self.input = {100: 215}
    def read(self, kind, addr, count):
        table = {"coil": self.coils, "discrete": self.discrete, "holding": self.holding, "input": self.input}[kind]
        return [table.get(addr + i, 0) for i in range(count)]
    def write(self, kind, addr, values):
        table = {"coil": self.coils, "holding": self.holding}[kind]
        for i, v in enumerate(values): table[addr + i] = v

class Sim(ModbusDriver):
    link = _Plc()
"""


def test_modbus_driver_over_injected_link():
    assert decode(encode(37.5, "float32"), "float32") == 37.5
    assert decode(encode(-12, "int16"), "int16") == -12 and decode(encode(70000, "uint32"), "uint32") == 70000
    with tempfile.TemporaryDirectory() as td:
        folder = _package(Path(td), "incubator", MODBUS_DESC, MODBUS_DRIVER, MODBUS_SIM)
        drv = load_driver(folder, sim=True)
        dev = LocalDevice(drv)
        assert dev.read("temperature") == 21.5 and dev.read("door_closed") is True
        dev.write("setpoint", 37.5)
        assert dev.read("setpoint_echo") == 37.5
        dev.write("heater_on", True)
        assert drv.link.coils[10] == 1
        try:
            dev.write("setpoint", 99); raise AssertionError("expected LimitViolation")
        except RemoteError as e:
            assert e.code == -32010
        r = dev.wait(dev.invoke("hold", target=30))
        assert r["state"] == "done" and r["result"] == {"steps": 2} and drv.link.coils[20] == 1
        drv.link.discrete[3] = 0
        try:
            dev.invoke("start"); raise AssertionError("expected InterlockOpen")
        except RemoteError as e:
            assert e.code == -32011
        dev.estop()
        assert drv.link.coils[20] == 0 and dev.read("setpoint_echo") == 0.0
        drv.close()


def test_validate_and_rubric_see_the_new_conventions():
    from openmhp.rubric import score
    from openmhp.validate import validate_path
    with tempfile.TemporaryDirectory() as td:
        folder = _package(Path(td), "flow_controller", SERIAL_DESC, SERIAL_DRIVER, SERIAL_SIM)
        v = validate_path(str(folder))
        assert v["ok"], v["errors"]
        assert not [w for w in v["warnings"] if "self-state" in w or "robot_access_ready" in w or "returns" in w], v["warnings"]
        r = score(folder)
        grades = {c["id"]: c["grade"] for c in r["criteria"]}
        assert grades["C12"] == "Pass" and grades["C20"] == "Pass" and grades["C5"] == "Pass" and grades["C14"] == "Pass"
        assert grades["C2"] == "Pass" and grades["C15"] == "Pass" and grades["C21"] == "Pass"
        # a package that mentions a lid but declares no robot_access_ready, and no self-state, is told so
        bare = SERIAL_DESC.replace("  - {name: robot_access_ready, type: boolean, notes: \"true when the tray is out and parked\"}\n", "")
        bare = "\n".join(ln for ln in bare.splitlines() if "source: record" not in ln and "robot_access_ready" not in ln) + "\n"
        folder2 = _package(Path(td) / "b", "pump", bare, SERIAL_DRIVER, SERIAL_SIM) if (Path(td) / "b").mkdir() is None else None
        v2 = validate_path(str(folder2))
        assert any("self-state" in w for w in v2["warnings"]) and any("robot_access_ready" in w for w in v2["warnings"]), v2["warnings"]
        g2 = {c["id"]: c["grade"] for c in score(folder2)["criteria"]}
        assert g2["C12"] == "Fail" and g2["C20"] == "Fail"
        # an unknown class is named with its nearest known one
        v3 = validate_path(str(_package(Path(td) / "c", "chromatograf", SERIAL_DESC, SERIAL_DRIVER, SERIAL_SIM))) if (Path(td) / "c").mkdir() is None else None
        assert any("chromatograph" in w for w in v3["warnings"]), v3["warnings"]



def test_serial_checksum_hook_and_modbus_string_registers():
    """Materials wave: Laurell/Retsch-style frame checksums and Nabertherm/Eurotherm ASCII register blocks."""
    drv = SerialAsciiDriver.__new__(SerialAsciiDriver)
    drv.cfg, drv.eol = {}, "\r"
    assert drv._encode("SPIN") == b"SPIN\r"                                   # no checksum block: unchanged
    drv.cfg = {"checksum": {"kind": "xor", "prefix": "*"}}
    assert drv._encode("SPIN") == b"SPIN*" + f"{ord('S') ^ ord('P') ^ ord('I') ^ ord('N'):02X}".encode() + b"\r"
    drv.cfg = {"checksum": {"kind": "sum8", "format": "{:03d}"}}
    assert drv._encode("AB") == b"AB" + f"{(65 + 66) & 0xFF:03d}".encode() + b"\r"
    drv.cfg = {"checksum": {"kind": "crc99"}}
    try:
        drv._encode("AB"); raise AssertionError("expected InvalidValue")
    except Exception as e:                                                   # noqa: BLE001
        assert type(e).__name__ == "InvalidValue"
    words = [0x5369, 0x6E74, 0x6572, 0x2000, 0x0000]                         # "Sinter " then NUL padding
    assert decode(words, "string") == "Sinter"
    plc = _PlcString()
    class D(ModbusDriver):
        link = plc
    d = D.__new__(D); d.link = plc; d.word_order = "big"
    import threading; d._io = threading.Lock()
    assert d._read_reg({"reg": 300, "kind": "holding", "type": "string", "length": 5}) == "Sinter"
    try:
        d._write_reg({"reg": 300, "kind": "holding", "type": "string"}, "x"); raise AssertionError("expected InvalidValue")
    except Exception as e:                                                   # noqa: BLE001
        assert type(e).__name__ == "InvalidValue"


class _PlcString:
    is_open = True
    def read(self, kind, addr, count):
        assert kind == "holding" and addr == 300 and count == 5
        return [0x5369, 0x6E74, 0x6572, 0x2000, 0x0000]
    def write(self, kind, addr, values):
        raise AssertionError("must not write")


if __name__ == "__main__":
    import traceback
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print("ok ", name)
            except Exception:                                          # noqa: BLE001
                failed += 1; print("FAIL", name); traceback.print_exc()
    print(f"{failed} failed")
    sys.exit(1 if failed else 0)
