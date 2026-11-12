"""Declarative Modbus driver (TCP or RTU): registers from descriptor.yaml, no code in the package.

    modbus:
      host: 192.168.1.50          # TCP; or port: /dev/ttyUSB0 + baud for RTU (config.json overrides both)
      port: 502
      unit: 1
      read:
        temperature:  {reg: 100, kind: input,   type: int16,   scale: 0.1}
        door_closed:  {reg: 3,   kind: discrete}
        setpoint:     {reg: 200, kind: holding, type: float32}
      write:
        setpoint:     {reg: 200, kind: holding, type: float32}
        heater_on:    {reg: 10,  kind: coil}
      actions:
        start: [{reg: 20, kind: coil, value: 1}]
        stop:  [{reg: 20, kind: coil, value: 0}]
      estop:   [{reg: 20, kind: coil, value: 0}, {reg: 200, kind: holding, type: float32, value: 0}]

`kind` is coil | discrete | holding | input; `type` is int16 | uint16 | int32 | uint32 | float32
(big-endian word order unless `word_order: little`). A read value is `raw * scale + offset`; a
written value is `(value - offset) / scale`, rounded to the register type. A signal with no
register that is one of the reserved self-state or runtime names (SPEC 4.6) is answered by the
base. pymodbus is imported lazily; a `link` with read(kind, addr, count) -> list[int] and
write(kind, addr, values) may be injected for a twin.
"""
from __future__ import annotations

import struct
import threading

from ..driver import Driver, InvalidValue, Job

KINDS = ("coil", "discrete", "holding", "input")
WORDS = {"int16": 1, "uint16": 1, "int32": 2, "uint32": 2, "float32": 2}


class _PymodbusLink:
    def __init__(self, client, unit: int):
        self.client, self.unit = client, unit
        self.is_open = client.connect()

    def read(self, kind: str, addr: int, count: int) -> list[int]:
        c, u = self.client, self.unit
        kw = {"slave": u}
        if kind == "coil":
            r = c.read_coils(addr, count=count, **kw); return [int(b) for b in r.bits[:count]]
        if kind == "discrete":
            r = c.read_discrete_inputs(addr, count=count, **kw); return [int(b) for b in r.bits[:count]]
        if kind == "holding":
            r = c.read_holding_registers(addr, count=count, **kw); return list(r.registers)
        r = c.read_input_registers(addr, count=count, **kw); return list(r.registers)

    def write(self, kind: str, addr: int, values: list[int]) -> None:
        c, u = self.client, self.unit
        if kind == "coil":
            c.write_coil(addr, bool(values[0]), slave=u)
        elif len(values) == 1:
            c.write_register(addr, values[0], slave=u)
        else:
            c.write_registers(addr, values, slave=u)

    def close(self) -> None:
        self.is_open = False
        self.client.close()


def encode(value, typ: str, word_order: str = "big") -> list[int]:
    if typ in ("int16", "uint16"):
        v = int(round(value))
        if typ == "int16" and v < 0:
            v += 1 << 16
        return [v & 0xFFFF]
    if typ in ("int32", "uint32"):
        v = int(round(value))
        words = list(struct.unpack(">HH", struct.pack(">i" if typ == "int32" else ">I", v)))
    else:
        words = list(struct.unpack(">HH", struct.pack(">f", float(value))))
    return words[::-1] if word_order == "little" else words


def decode(words: list[int], typ: str, word_order: str = "big"):
    if typ == "string":                                     # ASCII packed two characters per register
        return b"".join(struct.pack(">H", w & 0xFFFF) for w in words).split(b"\x00", 1)[0].decode("ascii", errors="replace").strip()
    if typ in ("int16", "uint16"):
        v = words[0] & 0xFFFF
        return v - (1 << 16) if typ == "int16" and v >= 0x8000 else v
    w = words[:2][::-1] if word_order == "little" else words[:2]
    raw = struct.pack(">HH", *w)
    if typ == "int32":
        return struct.unpack(">i", raw)[0]
    if typ == "uint32":
        return struct.unpack(">I", raw)[0]
    return struct.unpack(">f", raw)[0]


class ModbusDriver(Driver):
    link = None                       # injectable

    def setup(self):
        self.cfg = self.descriptor.get("modbus", {})
        self.word_order = self.cfg.get("word_order", "big")
        self._io = threading.Lock()
        if self.link is None:
            self.link = self.open_link()

    def open_link(self):
        cfg = {**self.cfg, **self.config()}
        unit = int(cfg.get("unit", 1))
        if cfg.get("host"):
            from pymodbus.client import ModbusTcpClient                     # noqa: PLC0415
            return _PymodbusLink(ModbusTcpClient(cfg["host"], port=int(cfg.get("port", 502)),
                                                 timeout=float(cfg.get("timeout", 2))), unit)
        if cfg.get("serial_port") or (isinstance(cfg.get("port"), str) and not str(cfg["port"]).isdigit()):
            from pymodbus.client import ModbusSerialClient                  # noqa: PLC0415
            return _PymodbusLink(ModbusSerialClient(cfg.get("serial_port") or cfg["port"],
                                                    baudrate=int(cfg.get("baud", 9600)),
                                                    timeout=float(cfg.get("timeout", 2))), unit)
        raise RuntimeError("no Modbus endpoint: set `host` (TCP) or `serial_port` (RTU) in config.json")

    def is_connected(self) -> bool:
        return bool(getattr(self.link, "is_open", self.link is not None))

    @classmethod
    def probe(cls, cfg: dict) -> str | None:
        if not (cfg.get("host") or cfg.get("serial_port")):
            return None
        import socket                                                       # noqa: PLC0415
        if cfg.get("host"):
            with socket.create_connection((cfg["host"], int(cfg.get("port", 502))), timeout=2):
                return f"{cfg['host']}:{cfg.get('port', 502)} accepts Modbus TCP connections"
        return f"serial port {cfg['serial_port']} named"

    # ---- registers ------------------------------------------------------ #
    def _spec(self, table: str, name: str) -> dict:
        spec = (self.cfg.get(table) or {}).get(name)
        if spec is None:
            raise InvalidValue(f"no Modbus {table} register for {name}")
        if spec.get("kind", "holding") not in KINDS:
            raise InvalidValue(f"{name}: kind must be one of {KINDS}")
        return spec

    def _read_reg(self, spec: dict):
        kind, typ = spec.get("kind", "holding"), spec.get("type", "uint16")
        if kind in ("coil", "discrete"):
            count = 1
        elif typ == "string":                                # `length` registers of packed ASCII (program names)
            count = int(spec.get("length", 8))
        else:
            count = WORDS[typ]
        with self._io:
            words = self.link.read(kind, int(spec["reg"]), count)
        if kind in ("coil", "discrete"):
            return bool(words[0])
        if typ == "string":
            return decode(words, typ)
        return decode(words, typ, self.word_order) * float(spec.get("scale", 1)) + float(spec.get("offset", 0))

    def _write_reg(self, spec: dict, value) -> None:
        kind, typ = spec.get("kind", "holding"), spec.get("type", "uint16")
        if kind in ("coil",):
            words = [1 if value else 0]
        elif kind in ("discrete", "input"):
            raise InvalidValue(f"register {spec['reg']} is read-only ({kind})")
        elif typ == "string":
            raise InvalidValue(f"register {spec['reg']} is a string block; writing names is not supported")
        else:
            raw = (float(value) - float(spec.get("offset", 0))) / float(spec.get("scale", 1))
            words = encode(raw, typ, self.word_order)
        with self._io:
            self.link.write(kind, int(spec["reg"]), words)

    # ---- hooks ---------------------------------------------------------- #
    def on_read(self, name):
        spec = self._spec("read", name)
        value = self._read_reg(spec)
        typ = self._index["signals"].get(name, {}).get("type", "number")
        if typ == "boolean":
            return bool(value)
        if typ == "integer":
            return int(round(value))
        return value

    def on_write(self, name, value):
        self._write_reg(self._spec("write", name), int(value) if isinstance(value, bool) else value)

    def validate_params(self, action: str, params: dict) -> None:
        steps = (self.cfg.get("actions") or {}).get(action)
        if not steps:
            raise InvalidValue(f"no Modbus steps configured for action {action}")
        for s in steps:
            v = s.get("value")
            if isinstance(v, str) and v.startswith("{") and v.endswith("}") and v[1:-1] not in params:
                raise InvalidValue(f"{action}: step needs parameter '{v[1:-1]}'")

    def on_invoke(self, job: Job):
        steps = (self.cfg.get("actions") or {}).get(job.action) or []
        for i, s in enumerate(steps):
            self.checkpoint(job)
            v = s.get("value")
            if isinstance(v, str) and v.startswith("{") and v.endswith("}"):
                v = job.params[v[1:-1]]
            self._write_reg(s, v)
            self.progress(job, (i + 1) / len(steps))
        return {"steps": len(steps)}

    def on_estop(self):
        steps = self.cfg.get("estop") or []
        if not steps:
            raise RuntimeError("no Modbus estop steps configured")
        errors = []
        for s in steps:
            try:
                self._write_reg(s, s.get("value", 0))
            except Exception as e:                                          # noqa: BLE001  keep trying the rest
                errors.append(f"reg {s.get('reg')}: {type(e).__name__}: {e}")
        if errors:
            raise RuntimeError("stop writes failed: " + "; ".join(errors))
